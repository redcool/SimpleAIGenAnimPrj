#!/usr/bin/env python3
"""写一份动作元数据 action.json —— 每个动作目录的统一"身份证"。

两条产线（模型生成、动作库接入）都写同一个格式，
下游（Unity 打包、状态机、资产盘点）只需要认这一份。

字段
----
  name        动作名（建议 gen_* / lib_* / act_* / cap_*，见 docs/动作产线规范.md）
  source      model | library | hybrid | capture
  origin      模型产线写 prompt；库产线写片段文件名；动补写视频文件名
  rig         角色名
  frames/fps  时长
  loopable    是否可循环
  in_place    是否原地动作
  qa          质量检查结果（verify_anim / 循环报告）
  files       目录里的 fbx/glb

用法
----
  python tools/action_meta.py --dir outputs/actions/act_roll_fwd \
      --name act_roll_fwd --source library --rig X_Bot \
      --origin "Sprinting Forward Roll.fbx" --qa outputs/actions/act_roll_fwd/qa.json

  # 模型生成的动作，从循环报告取帧数与接缝
  python tools/action_meta.py --dir outputs/samples/X_Bot_locomotion_cycle \
      --name gen_locomotion --source model --rig X_Bot --origin "walks/runs/stands" \
      --loop-report outputs/samples/X_Bot_locomotion_cycle/loop_report.json
"""

from __future__ import annotations

import argparse
import datetime
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import pipeline_config as cfg
from action_schema import KIND, SOURCES, validate


def main():
    ap = argparse.ArgumentParser(description="写动作元数据 action.json")
    ap.add_argument("--dir", required=True, help="动作输出目录")
    ap.add_argument("--name", required=True, help="动作名")
    # 取值来源是 core/action_schema.py，加新来源只改那一处
    ap.add_argument("--source", required=True, choices=sorted(SOURCES),
                    help="动作来源：%s" % "，".join("%s=%s" % (k, v) for k, v in SOURCES.items()))
    ap.add_argument("--rig", default=None, help="角色名")
    ap.add_argument("--origin", default=None, help="prompt 或片段文件名")
    ap.add_argument("--loopable", action="store_true", help="可循环")
    ap.add_argument("--not-in-place", action="store_true", help="带根位移（默认原地）")
    ap.add_argument("--qa", default=None, help="verify_anim 产的 qa.json")
    ap.add_argument("--loop-report", default=None, help="make_loop 产的 loop_report.json")
    ap.add_argument("--capture-run", default=None,
                    help="动补产线的 run 目录（读 run.json 与 diagnostics.json 填 qa）")
    args = ap.parse_args()

    out = os.path.abspath(args.dir)
    if not os.path.isdir(out):
        raise SystemExit("目录不存在：%s" % out)

    qa = {}
    if args.qa and os.path.isfile(args.qa):
        with open(args.qa, encoding="utf-8") as fh:
            data = json.load(fh)
        item = (data.get("items") or [{}])[0]
        qa = {
            "check": "verify_anim",
            "expect": data.get("expect"),
            "ok": item.get("ok"),
            "note": item.get("note"),
            "root_rotation_deg": item.get("root_rotation_deg"),
            "limb_rel": item.get("limb_rel"),
        }
    elif args.loop_report and os.path.isfile(args.loop_report):
        with open(args.loop_report, encoding="utf-8") as fh:
            data = json.load(fh)
        items = data.get("items", {})
        ratios = [v.get("seam_ratio_before") for v in items.values()
                  if isinstance(v, dict) and v.get("seam_ratio_before") is not None]
        frames = [v.get("frames_out") for v in items.values()
                  if isinstance(v, dict) and v.get("frames_out")]
        qa = {
            "check": "loop_report",
            "clips": len(items),
            "best_seam_ratio": round(min(ratios), 2) if ratios else None,
            "worst_seam_ratio": round(max(ratios), 2) if ratios else None,
            "frames": sorted({int(f) for f in frames}) if frames else [],
        }
    elif args.capture_run and os.path.isdir(args.capture_run):
        # 动补产线没有循环接缝的概念，质量看三件事：自穿插、脚锁修正、是否已落地
        qa = {"check": "motion_capture"}
        run_json = os.path.join(args.capture_run, "run.json")
        diagnostics_json = os.path.join(args.capture_run, "diagnostics.json")
        if os.path.isfile(run_json):
            with open(run_json, encoding="utf-8") as fh:
                run_data = json.load(fh)
            intersection = ((run_data.get("diagnostics") or {}).get("self_intersection") or {})
            foot_lock = run_data.get("foot_lock") or {}
            frame_count = run_data.get("n_frames")
            qa.update({
                "frames": frame_count,
                "fps": round(float(run_data.get("fps") or 0.0), 2),
                "self_intersection_frames": intersection.get("frame_count"),
                "self_intersection_share": (round(float(intersection.get("frame_count") or 0) / frame_count, 4)
                                            if frame_count else None),
                "self_intersection_max_cm": intersection.get("max_depth_cm"),
                "foot_lock_mean_cm": foot_lock.get("mean_correction_cm"),
                "foot_lock_max_cm": foot_lock.get("max_correction_cm"),
            })
        if os.path.isfile(diagnostics_json):
            with open(diagnostics_json, encoding="utf-8") as fh:
                diagnostics_data = json.load(fh)
            summary = ((diagnostics_data.get("summary") or {}).get("self_intersection") or {})
            qa["self_intersection_issues"] = summary.get("issue_count")
        qa["grounded_variant"] = os.path.isfile(os.path.join(args.capture_run, "mixamo_character_grounded.glb"))

    # 动作文件可能在一层子目录里（animated/、animated_inplace/、anim/），一并收进来
    files = []
    for name in sorted(os.listdir(out)):
        full = os.path.join(out, name)
        if name.endswith((".fbx", ".glb")):
            files.append(name)
        elif os.path.isdir(full):
            for sub in sorted(os.listdir(full)):
                if sub.endswith((".fbx", ".glb")):
                    files.append(os.path.join(name, sub))
    meta = {
        "kind": KIND,
        "version": cfg.version(),
        "name": args.name,
        "source": args.source,
        "origin": args.origin,
        "rig": args.rig,
        "loopable": bool(args.loopable),
        "in_place": not args.not_in_place,
        "files": files,
        "qa": qa,
        "created": datetime.date.today().isoformat(),
    }
    problems = validate(meta)
    if problems:
        raise SystemExit("action.json 不符合契约：%s" % "；".join(problems))

    path = os.path.join(out, "action.json")
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(meta, fh, indent=2, ensure_ascii=False)
    print("已写出 %s（source=%s, files=%d）" % (path, args.source, len(files)))


if __name__ == "__main__":
    main()