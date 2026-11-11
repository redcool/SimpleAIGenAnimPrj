"""画 v2(启发式焦距)与 v3(按距离反推焦距)的世界位移对比图。

左:俯视轨迹(世界 XZ),带 0.5m 网格;右:髋部高度随时间。
两张图共用同一坐标尺度,位移尺度差异一眼能看出来。
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

# 标签用英文:matplotlib 默认字体没有中文字形,画出来会是方块
CASES = [
    ("v2 heuristic focal (~43mm equiv, ~2050px)",
     Path(r"H:\aiworks\motionPrj\AIGenAnimPrj\outputs\video_cap\cap_punch_v2\skeleton_motion.npz"), "#d62728"),
    ("v3 focal from distance 3.4m (~1481px)",
     Path(r"H:\aiworks\motionPrj\AIGenAnimPrj\outputs\video_cap\cap_punch_v3\skeleton_motion.npz"), "#1f77b4"),
]
OUT = Path(r"H:\aiworks\motionPrj\AIGenAnimPrj\outputs\video_cap\cap_punch_v3\trajectory_compare.png")

figure, (left, right) = plt.subplots(1, 2, figsize=(14, 6))

for label, path, colour in CASES:
    if not path.exists():
        print("缺文件:", path)
        continue
    data = np.load(path, allow_pickle=True)
    joints = np.asarray(data["joints_3d"], dtype=np.float64)
    fps = float(np.asarray(data["fps"]).reshape(-1)[0])
    pelvis = joints[:, 0, :]
    travel = float(np.linalg.norm(pelvis[:, [0, 2]].max(0) - pelvis[:, [0, 2]].min(0)))
    left.plot(pelvis[:, 0], pelvis[:, 2], label="%s\ntravel %.2f m" % (label, travel), color=colour, linewidth=1.2)
    left.scatter([pelvis[0, 0]], [pelvis[0, 2]], marker="o", s=40, color=colour)
    left.scatter([pelvis[-1, 0]], [pelvis[-1, 2]], marker="X", s=60, color=colour)
    times = np.arange(len(pelvis)) / fps
    right.plot(times, pelvis[:, 1], label=label, color=colour, linewidth=1.0)
    print("%-46s travel %.2f m | pelvis Y %.3f~%.3f m | %d frames @ %.1ffps"
          % (label, travel, pelvis[:, 1].min(), pelvis[:, 1].max(), len(pelvis), fps))

left.set_title("Top view of pelvis path (world XZ, metres)")
left.set_xlabel("X (m)"); left.set_ylabel("Z (m)")
left.grid(True, which="both", alpha=0.3)
left.axis("equal")
left.legend(fontsize=8)

right.set_title("Pelvis height over time")
right.set_xlabel("time (s)"); right.set_ylabel("Y (m)")
right.grid(True, alpha=0.3)
right.legend(fontsize=8)

figure.suptitle("Motion2MixamoRig: heuristic focal (v2) vs distance-derived focal (v3)", fontsize=11)
figure.tight_layout()
OUT.parent.mkdir(parents=True, exist_ok=True)
figure.savefig(OUT, dpi=120)
print("写出", OUT)
