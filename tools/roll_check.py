#!/usr/bin/env python3
"""判断一段动作到底有没有"翻"过去。

原理
----
绕横轴翻 360° 时，根节点（Hips）的姿态累计变化是一个整圈；只是蹲下或前倾的话
累计角很小。所以看两个数字：
  1. 累计转角 = 相邻帧之间相对转角之和（翻一圈 ≈ 360°）
  2. 旋转轴   = 累计旋转的主轴，应该接近横向（角色面朝 +Z 时横轴是 X）
另外看高度：地面翻滚时髋部会降到很低。

用法
----
  python tools/roll_check.py --samples outputs/samples/X_Bot_roll
"""

from __future__ import annotations

import argparse
import glob
import json
import os

import numpy as np

ROT = slice(3, 9)


def rot6_to_matrix(v):
    a = v[:3] / (np.linalg.norm(v[:3]) + 1e-9)
    b = v[3:] - np.dot(a, v[3:]) * a
    b = b / (np.linalg.norm(b) + 1e-9)
    c = np.cross(a, b)
    return np.stack([a, b, c], axis=1)      # 列向量拼成 R


def angle_between(r1, r2):
    """两个旋转矩阵之间的夹角（度）。"""
    rel = r1.T @ r2
    cos = (np.trace(rel) - 1.0) / 2.0
    return float(np.degrees(np.arccos(np.clip(cos, -1.0, 1.0))))


def axis_of(r1, r2):
    """相对旋转的转轴（在第一个坐标系里）。"""
    rel = r1.T @ r2
    w = np.array([rel[2, 1] - rel[1, 2], rel[0, 2] - rel[2, 0], rel[1, 0] - rel[0, 1]])
    n = np.linalg.norm(w)
    return w / n if n > 1e-9 else np.zeros(3)


def analyze(path):
    a = np.load(path)
    F, J, D = a.shape
    mats = [rot6_to_matrix(a[t, 0, ROT]) for t in range(F)]   # 关节 0 = Hips

    # 累计转角（相邻帧夹角之和）
    total = sum(angle_between(mats[t], mats[t + 1]) for t in range(F - 1))
    # 主轴（用首尾之间的大角度，靠得住一些）
    ax = axis_of(mats[0], mats[F // 2])
    # 高度（root 的 y 分量，canonical 帧里 +Y 向上）
    height = a[:, 0, 1]
    # 水平位移（用速度通道积分不直观，这里用根节点 xz 的跨度近似）
    return {
        "file": os.path.basename(path),
        "frames": F,
        "total_rotation_deg": round(total, 1),
        "half_axis": [round(float(x), 2) for x in ax],
        "height_min": round(float(height.min()), 3),
        "height_max": round(float(height.max()), 3),
        "strength": round(float(np.abs(a - a.mean(0, keepdims=True)).mean()), 4),
    }


def verdict(r):
    deg = r["total_rotation_deg"]
    ax = r["half_axis"]
    lateral = abs(ax[0]) if len(ax) == 3 else 0.0     # X = 横轴
    if deg >= 320:
        return "翻了一整圈（%.0f°）%s" % (deg, "，主轴横向" if lateral > 0.7 else "，但主轴偏了")
    if deg >= 240:
        return "转了 %.0f°，接近一圈但没闭合，可能是翻身/侧滚" % deg
    if deg >= 150:
        return "只转了 %.0f°，像是弯腰前倾，没有翻" % deg
    return "累计只有 %.0f°，基本没转" % deg


def main():
    ap = argparse.ArgumentParser(description="检查动作里有没有翻滚")
    ap.add_argument("--samples", required=True)
    ap.add_argument("--json", default=None)
    args = ap.parse_args()

    files = sorted(glob.glob(os.path.join(os.path.abspath(args.samples), "motions", "*.npy")))
    if not files:
        raise SystemExit("没有动作文件")

    rows = []
    for f in files:
        r = analyze(f)
        r["verdict"] = verdict(r)
        rows.append(r)
        print("=== %s" % r["file"])
        print("  累计转角 %.0f°   主轴(x,y,z) %s" % (r["total_rotation_deg"], r["half_axis"]))
        print("  髋部高度 %.3f ~ %.3f   整体强度 %.4f" % (r["height_min"], r["height_max"], r["strength"]))
        print("  判定: %s" % r["verdict"])
        print()

    if args.json:
        with open(args.json, "w", encoding="utf-8") as fh:
            json.dump(rows, fh, indent=2, ensure_ascii=False)
        print("已写出 %s" % args.json)


if __name__ == "__main__":
    main()
