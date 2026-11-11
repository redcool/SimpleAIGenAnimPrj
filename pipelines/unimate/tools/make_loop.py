#!/usr/bin/env python3
"""把生成动作做成可循环的片段 —— 命令行编排层。

这里只做三件事：解析参数、逐个文件跑流程、写报告。
真正的算法在：
    cycle_search.py   找周期（按四肢轨迹 / 按全身旋转 / 静止保护 / 候选打分）
    loop_cut.py       切片段（裁剪、接缝淡化、接缝指标、判定）

为什么要拆：这段逻辑改过四轮（锚定 → 双端点 → 按脚 → 行程约束），
全塞在一个 470 行的文件里时，每次改算法都要通读"怎么切"和"怎么写报告"。

特征布局：(T, J, 12) = 位置 3 + 相对 T-pose 的旋转 6 + 速度 3。
驱动网格时只用到根节点位置和每根骨头的旋转 6 维，速度通道不参与。

用法
----
  python pipelines/unimate/tools/make_loop.py --samples <采样目录>
  python pipelines/unimate/tools/make_loop.py --samples <dir> --only walks_forward --seam 6
  python pipelines/unimate/tools/make_loop.py --samples <dir> --period 32 --basis rot

产出
----
  <out>/motions/*.npy      循环后的动作（帧数 = 周期）
  <out>/manifest.json      复制原清单，条目指向新文件
  <out>/loop_report.json   每个动作的周期、接缝指标、判定
"""

from __future__ import annotations

import argparse
import json
import math
import os
import shutil
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

try:                                    # 版本号统一来自仓库根的 VERSION
    import pipeline_config as _cfg
    __version__ = _cfg.version()
except Exception:                       # 单独拷走这个文件也能跑
    __version__ = "0.0.0.0"

try:                                    # 四肢识别与步态检查共用一套规则
    from rig_joints import find_limbs
except Exception:
    find_limbs = None

from cycle_search import (               # noqa: E402  拆出去的两块算法
    POS, ROT, VEL, CycleOptions, choose_cycle, find_cycle, find_cycle_feet,
    foot_range, foot_step, median_step, orthonormalize, rot_dist,
)
from loop_cut import (                   # noqa: E402
    cut_loop, foot_seam, loop_verdict, seam_metrics, smoothstep,
)

# 旧名字兼容：外部脚本与测试还在 import make_loop / find_cycle_feet 等
make_loop = cut_loop


def log(msg: str) -> None:
    print(msg, flush=True)


def load_manifest(src_dir: str):
    """读采样清单（关节名、prompt、权重都在里面），没有就返回 None。"""
    path = os.path.join(src_dir, "manifest.json")
    if not os.path.isfile(path):
        return None
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def feet_for(manifest, name: str, joint_count: int) -> dict:
    """按关节名认出四肢末端；认不出就返回空字典（退回按旋转）。"""
    if not (find_limbs and manifest):
        return {}
    asset = (manifest.get("samples", {}).get(name, {}) or {}).get("asset", "")
    if not asset:
        return {}
    names = (manifest.get("assets", {}).get(asset, {}) or {}).get("joint_names")
    if not names or len(names) != joint_count:
        return {}
    return find_limbs(names)


def main() -> None:
    ap = argparse.ArgumentParser(description="把生成动作做成可循环片段")
    ap.add_argument("--samples", required=True, help="采样目录（含 motions/ 和 manifest.json）")
    ap.add_argument("--out", default=None, help="输出目录，默认 <samples>_loop")
    ap.add_argument("--only", default=None, help="只处理文件名含此子串的动作")
    ap.add_argument("--min-period", type=int, default=20)
    ap.add_argument("--max-period", type=int, default=58)
    ap.add_argument("--seam", type=int, default=8, help="接缝交叉淡化帧数")
    ap.add_argument("--period", type=int, default=None, help="强制指定周期，跳过检测")
    ap.add_argument("--max-start", type=int, default=None,
                    help="起点搜索范围上限（默认到 T-L-1，即全片段）")
    ap.add_argument("--anchor", action="store_true",
                    help="退回旧行为：只从第 0 帧开始找周期")
    ap.add_argument("--no-detrend", action="store_true",
                    help="（保留参数，已无作用；根位移交给 flatten_root.py）")
    ap.add_argument("--basis", choices=["auto", "feet", "rot"], default="auto",
                    help="找周期的依据：feet=按四肢末端轨迹（四足推荐），rot=按全身旋转，auto=能认出四肢就用 feet")
    ap.add_argument("--foot-min-period", type=int, default=8,
                    help="按脚找周期的最短周期（狗一轮跑步约 20~30 帧，太短会把噪声当周期）")
    ap.add_argument("--min-foot-travel", type=float, default=0.55,
                    help="一个周期内脚至少要走过「脚的行程」的这个比例，用来排除短窗口的假周期")
    ap.add_argument("--foot-tolerance", type=float, default=0.12,
                    help="按脚找周期时，两帧脚位差要小于「脚的行程」的这个比例才算循环（尺度无关）")
    ap.add_argument("--min-foot-motion", type=float, default=0.002,
                    help="四肢每帧平均位移低于此值当作静止（待机），不切周期")
    ap.add_argument("--period-tolerance", type=float, default=1.5,
                    help="检测到的周期误差超过中位步长的这个倍数时，判定为无周期")
    args = ap.parse_args()

    opts = CycleOptions(
        basis=args.basis, min_period=args.min_period, max_period=args.max_period,
        foot_min_period=args.foot_min_period, min_foot_travel=args.min_foot_travel,
        foot_tolerance=args.foot_tolerance, min_foot_motion=args.min_foot_motion,
        period_tolerance=args.period_tolerance, anchor=args.anchor,
        max_start=args.max_start, forced_period=args.period,
    )

    src_dir = os.path.abspath(args.samples)
    out_dir = os.path.abspath(args.out or (src_dir.rstrip("/\\") + "_loop"))
    motions_in = os.path.join(src_dir, "motions")
    if not os.path.isdir(motions_in):
        raise SystemExit("找不到 %s" % motions_in)
    motions_out = os.path.join(out_dir, "motions")
    os.makedirs(motions_out, exist_ok=True)

    manifest = load_manifest(src_dir)
    report = {"tool": "make_loop", "version": __version__,
              "samples": src_dir, "out": out_dir,
              "seam_requested": args.seam,
              "detrend": not args.no_detrend, "items": {}}

    files = sorted(f for f in os.listdir(motions_in) if f.endswith(".npy"))
    if args.only:
        files = [f for f in files if args.only in f]
    if not files:
        raise SystemExit("没有匹配的动作文件")

    new_samples = {}
    for name in files:
        x = np.load(os.path.join(motions_in, name)).astype(np.float32)
        T = x.shape[0]
        feet = feet_for(manifest, name, x.shape[1])

        choice = choose_cycle(x, feet, opts)
        seg = x[choice.start:] if choice.cyclic else x
        looped, info = cut_loop(seg, choice.period, args.seam, not args.no_detrend)
        info["start"] = int(choice.start)
        m = seam_metrics(seg, looped, choice.period)
        fseam = foot_seam(looped, feet, info["mode"])

        np.save(os.path.join(motions_out, name), looped)

        ratio_before = m["seam_before_ratio"] if m["median_step"] else float("nan")
        verdict = loop_verdict(ratio_before, m["seam_before"], info["mode"], fseam)
        if choice.basis == "feet" and choice.seam_ratio is not None and choice.cyclic:
            log("    [feet] 起点 %d 周期 %d 接缝比 %.2f"
                % (choice.start, choice.period, choice.seam_ratio))

        report["items"][name] = {
            "frames_in": int(T), "frames_out": int(looped.shape[0]),
            "start_frame": int(choice.start),
            "end_frame": int(choice.start + choice.period) if choice.cyclic else int(T),
            "period_detected": int(choice.period), "cyclic": bool(choice.cyclic),
            "period_error": None if math.isnan(choice.error) else round(choice.error, 4),
            "velocity_error": None if math.isnan(choice.velocity_error) else round(choice.velocity_error, 4),
            "candidates": [{"start": c[0], "period": c[1], "cost": c[2]} for c in choice.candidates],
            "seam_frames": info["seam_frames"],
            "basis": choice.basis,
            "foot_seam_ratio": None if fseam is None else round(fseam, 2),
            "foot_period_error": None if math.isnan(choice.error) else round(choice.error, 5),
            "feet": {k: v for k, v in (feet or {}).items()},
            "loop_mode": info["mode"],
            "root_drift_removed": [round(v, 4) for v in info["drift"]],
            "median_step": round(m["median_step"], 4),
            "seam_ratio_before": round(m["seam_before_ratio"], 2) if m["median_step"] else None,
            "seam_ratio_after": round(m["seam_after_ratio"], 2) if m["median_step"] else None,
            "loop_verdict": verdict,
            "seam_before_abs": round(m["seam_before"], 4),
            "hold_frames": 1 if info["mode"] == "head-hold" else 0,
        }

        if manifest and name in manifest.get("samples", {}):
            new_samples[name] = manifest["samples"][name]

        where = ("片段 %d..%d（%d 帧）"
                 % (choice.start, choice.start + choice.period - 1, choice.period)
                 if choice.cyclic else "全片段收拢")
        log("  %s" % name)
        log("    %d 帧 -> %d 帧，%s  %s" % (T, looped.shape[0], where, verdict))
        if m["median_step"]:
            log("    接缝：%.1f 倍步长（绝对值 %.3f）-> %.1f 倍%s"
                % (ratio_before, m["seam_before"], m["seam_after_ratio"],
                   "（收拢到同一帧）" if info["mode"] == "head-hold" else ""))

    rows = sorted(
        report["items"].items(),
        key=lambda kv: (kv[1]["seam_ratio_before"] if kv[1]["seam_ratio_before"] is not None else 9e9),
    )
    log("")
    log("循环质量（越小越好；同一条 prompt 挑这条用）：")
    for k, v in rows:
        log("  %5.1f  %3d 帧  %-18s %s"
            % (v["seam_ratio_before"] or 9e9, v["frames_out"],
               v["loop_verdict"][:16], k))

    if manifest is not None:
        manifest = dict(manifest)
        if new_samples:
            manifest["samples"] = new_samples
        manifest["motions_dir"] = "motions"
        with open(os.path.join(out_dir, "manifest.json"), "w", encoding="utf-8") as fh:
            json.dump(manifest, fh, indent=2, ensure_ascii=False)

    with open(os.path.join(out_dir, "loop_report.json"), "w", encoding="utf-8") as fh:
        json.dump(report, fh, indent=2, ensure_ascii=False)


if __name__ == "__main__":
    main()
