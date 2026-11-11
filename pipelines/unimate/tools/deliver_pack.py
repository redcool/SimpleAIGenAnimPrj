#!/usr/bin/env python3
"""把一次循环化的结果打包成"两版交付"：anim/（循环版）+ full/（完整序列）。

为什么要两版（用户 2026-11-04 定）
--------------------------------
自动切的循环不一定对：节奏可能少一拍、脚可能没接上。人工需要拿到**未处理**的
完整序列自己找循环段。所以每个动作目录同时给两个版本，外加一份候选帧清单。

产物结构
--------
  <out>/
  ├── <name>_character.fbx      角色本体（从 unity/ 目录取）
  ├── anim/<kind>.fbx           循环版（程序切的，可直接用）
  ├── full/<kind>_full.fbx      完整序列·原地版（默认用这个）
  ├── full/<kind>_full_motion.fbx 完整序列·带根位移（对照）
  ├── full/cycle_candidates.txt 候选循环点（帧号 + 脚差）
  └── action.json               动作契约（source/qa/picks）

用法
----
  python tools/deliver_pack.py --samples outputs/samples/Dog_001 \
      --loop-dir tmp/accept_Dog_001 --name Dog_001 \
      --out outputs/actions/Dog_001_pack
"""

from __future__ import annotations

import argparse
import glob
import json
import os
import re
import shutil
import subprocess
import sys

# tools -> unimate -> pipelines -> 仓库根（少算一层会把 core/ 指到 pipelines/core）
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(HERE)))
sys.path.insert(0, os.path.join(ROOT, "core"))

KINDS = (("stands_still", "idle"), ("walks_forward", "walk"), ("runs_forward", "run"))


def log(message: str) -> None:
    print(message, flush=True)


def parse_gait(path: str) -> dict:
    """读 gait_report.txt：{clip: (最大摆幅, 判定)}。没有就当空表。"""
    if not os.path.isfile(path):
        return {}
    text = open(path, encoding="utf-8").read()
    out = {}
    for block in re.split(r"^=== ", text, flags=re.M)[1:]:
        name = block.split(" ===")[0].strip()
        verdict = re.search(r"判定: (.*)", block)
        amps = [float(x) for x in re.findall(r"竖直摆幅 ([0-9.]+)", block)]
        out[name] = (max(amps) if amps else 0.0, verdict.group(1) if verdict else "?")
    return out


def pick_looped(loop_dir: str, kind: str, gait: dict):
    """挑循环版：真实周期优先，其次接缝接近 1，再其次幅度大的。"""
    report_path = os.path.join(loop_dir, "loop_report.json")
    if not os.path.isfile(report_path):
        return None
    items = json.load(open(report_path, encoding="utf-8"))["items"]
    best = None
    for name, info in items.items():
        if kind not in name:
            continue
        fbx = os.path.join(loop_dir, "animated_inplace", name.replace(".npy", ".fbx"))
        if not os.path.isfile(fbx):
            continue
        real = info["period_detected"] < info["frames_in"]
        seam = info.get("foot_seam_ratio")
        score = 3.0 if real else 0.0
        if real and seam is not None:
            score += max(0.0, 1.5 - abs(seam - 1.0))
        verdict = gait.get(name, (0.0, ""))[1]
        if "袭步" in verdict or "小跑" in verdict:
            score += 2.0
        elif "不典型" in verdict:
            score += 0.5
        if best is None or score > best[0]:
            best = (score, fbx, name, seam, info["period_detected"])
    return best


def pick_full(samples_dir: str, kind: str):
    """挑完整序列：目录里第一个匹配的原始导出（未做任何循环处理）。"""
    for fbx in sorted(glob.glob(os.path.join(samples_dir, "animated", "*.fbx"))):
        if kind in os.path.basename(fbx):
            return fbx
    return None


def flatten(source: str, out_dir: str) -> str:
    """调 flatten_root.py 做原地版，返回产出文件路径。"""
    os.makedirs(out_dir, exist_ok=True)
    subprocess.run([sys.executable, os.path.join(HERE, "flatten_root.py"),
                    "--input", source, "--out", out_dir],
                   check=True, capture_output=True, text=True)
    made = glob.glob(os.path.join(out_dir, "*.fbx"))
    return made[0] if made else ""


def main() -> None:
    ap = argparse.ArgumentParser(description="打包两版交付（anim/ + full/）")
    ap.add_argument("--samples", required=True, help="采样目录（含 animated/）")
    ap.add_argument("--loop-dir", required=True, help="循环化产物目录（含 loop_report.json）")
    ap.add_argument("--name", required=True, help="角色名")
    ap.add_argument("--out", required=True, help="输出目录（动作包）")
    ap.add_argument("--source", default="model", help="动作来源，见 core/action_schema.py")
    ap.add_argument("--origin", default=None, help="prompt 或片段名")
    ap.add_argument("--work", default=None, help="拉平原地的临时目录，默认 <out>/.flatten")
    ap.add_argument("--character", default=None,
                    help="角色本体 FBX；不给就在循环目录/采样目录里找 *_character.fbx")
    args = ap.parse_args()

    samples = os.path.abspath(args.samples)
    loop_dir = os.path.abspath(args.loop_dir)
    out = os.path.abspath(args.out)
    work = os.path.abspath(args.work or os.path.join(out, ".flatten"))

    anim_dir = os.path.join(out, "anim")
    full_dir = os.path.join(out, "full")
    for d in (anim_dir, full_dir):
        os.makedirs(d, exist_ok=True)

    gait = parse_gait(os.path.join(loop_dir, "gait_report.txt"))
    picks, full_picks = {}, {}

    for kind, label in KINDS:
        chosen = pick_looped(loop_dir, kind, gait)
        if chosen:
            shutil.copy(chosen[1], os.path.join(anim_dir, label + ".fbx"))
            picks[label] = {"clip": chosen[2],
                            "loop_seam": chosen[3],
                            "period": chosen[4]}

        source = pick_full(samples, kind)
        if not source:
            log("  [缺] %s：采样目录里没有 %s 片段" % (label, kind))
            continue
        shutil.copy(source, os.path.join(full_dir, label + "_full_motion.fbx"))
        flat = flatten(source, os.path.join(work, label))
        if flat:
            shutil.copy(flat, os.path.join(full_dir, label + "_full.fbx"))
            full_picks[label] = os.path.basename(source)

    # 候选循环点清单：人工据此在完整序列里自己切
    candidates = subprocess.run(
        [sys.executable, os.path.join(HERE, "cycle_candidates.py"),
         "--samples", samples, "--top", "6"],
        capture_output=True, text=True)
    if candidates.stdout.strip():
        with open(os.path.join(full_dir, "cycle_candidates.txt"), "w", encoding="utf-8") as fh:
            fh.write(candidates.stdout)

    character = args.character
    if not character:
        # 依次在循环目录、采样目录里找（两处都可能没有，那就明确告诉用户）
        for base in (loop_dir, samples):
            found = glob.glob(os.path.join(base, "**", "*_character.fbx"), recursive=True)
            if found:
                character = found[0]
                break
    if character and os.path.isfile(character):
        shutil.copy(character, os.path.join(out, "%s_character.fbx" % args.name))
    else:
        log("  [警告] 没找到角色本体 FBX：Unity 里请直接用 rig 目录下的 %s.glb 建 Avatar" % args.name)

    meta_cmd = [sys.executable, os.path.join(ROOT, "core", "action_meta.py"),
                "--dir", out, "--name", "gen_%s_pack" % args.name,
                "--source", args.source, "--rig", args.name,
                "--origin", args.origin or ("samples: %s" % args.samples),
                "--loopable",
                "--loop-report", os.path.join(loop_dir, "loop_report.json")]
    done = subprocess.run(meta_cmd, capture_output=True, text=True)
    if done.returncode != 0:
        raise SystemExit("写 action.json 失败：%s" % done.stderr.strip())

    log("打包完成：%s" % out)
    log("  anim/ %d 个    full/ %d 个（含候选清单）" % (
        len(os.listdir(anim_dir)), len(os.listdir(full_dir))))
    for label, info in picks.items():
        log("  %-5s <- %s（接缝 %s）" % (label, info["clip"][:44], info["loop_seam"]))


if __name__ == "__main__":
    main()