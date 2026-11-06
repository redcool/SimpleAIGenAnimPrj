#!/usr/bin/env python3
"""给一条动作列出"可能的循环区间"，方便人工在完整序列里挑。

循环点由脚决定：找两帧几只脚几乎相同，前一帧当起点、后一帧当终点。
这里把候选按代价排出来，连帧号一起打印，人工可以直接说"用 44..80"。

用法
----
  python tools/cycle_candidates.py --samples outputs/samples/Tiger_001_long/motion_expand
  python tools/cycle_candidates.py --samples <dir> --top 12 --out <file.txt>
"""

from __future__ import annotations

import argparse
import glob
import json
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from rig_joints import find_limbs

POS = slice(0, 3)


def candidates(x, feet, top=8, min_period=8, max_period=None):
    T = x.shape[0]
    pos = x[:, list(feet.values()), POS].astype(np.float64)
    max_period = min(max_period or T - 2, T - 2)
    step_t = np.linalg.norm(pos[1:] - pos[:-1], axis=-1).mean(-1)
    cum = np.concatenate([[0.0], np.cumsum(step_t)])
    rng = float(np.linalg.norm(pos.max(0) - pos.min(0), axis=-1).mean())
    med = float(np.median(step_t)) if step_t.size else 0.0
    if rng <= 0:
        return []

    out = []
    for L in range(min_period, max_period + 1):
        for s in range(0, T - L):
            if cum[s + L] - cum[s] < 0.55 * rng:      # 脚得真走完一段路
                continue
            e = float(np.linalg.norm(pos[s] - pos[s + L], axis=-1).mean())
            out.append((e / rng, s, s + L, L, e / med if med else 0.0))
    out.sort()
    # 同一个起点只留最好的一条
    seen, kept = set(), []
    for row in out:
        if row[1] in seen:
            continue
        seen.add(row[1])
        kept.append(row)
        if len(kept) >= top:
            break
    return kept


def main():
    ap = argparse.ArgumentParser(description="列出动作的候选循环区间")
    ap.add_argument("--samples", required=True, help="含 motions/ 与 manifest.json 的目录")
    ap.add_argument("--top", type=int, default=8)
    ap.add_argument("--out", default=None, help="写成文本文件")
    args = ap.parse_args()

    src = os.path.abspath(args.samples)
    man = json.load(open(os.path.join(src, "manifest.json"), encoding="utf-8"))
    lines = []
    for f in sorted(glob.glob(os.path.join(src, "motions", "*.npy"))):
        name = os.path.basename(f)
        x = np.load(f).astype(np.float64)
        asset = (man.get("samples", {}).get(name, {}) or {}).get("asset", "")
        jn = (man.get("assets", {}).get(asset, {}) or {}).get("joint_names")
        if not jn or len(jn) != x.shape[1]:
            continue
        feet = find_limbs(jn)
        if len(feet) < 2:
            continue
        rows = candidates(x, feet, top=args.top)
        lines.append("=== %s   %d 帧   脚: %s" % (name, x.shape[0], list(feet)))
        if not rows:
            lines.append("    没有候选（脚几乎不动？）")
        for cost, s, e, L, seam in rows:
            lines.append("    起点 %3d  结束 %3d  长度 %3d 帧   脚差 %.2f（%.2f 倍步长）"
                         % (s, e, L, cost, seam))
        lines.append("")
    text = "\n".join(lines)
    if args.out:
        os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
        open(args.out, "w", encoding="utf-8").write(text)
        print("已写出 %s" % args.out)
    print(text)


if __name__ == "__main__":
    main()
