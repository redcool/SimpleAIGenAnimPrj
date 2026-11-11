#!/usr/bin/env python3
"""慢测:只在发版前手动跑,不进入 tests/smoke.sh。

为什么单独一个文件:这里要读真实的 GLB / 跑真实蒙皮,单次要十几秒到几分钟,
放进冒烟测试会让"改一行就跑一遍"变得难受。

跑法(必须用 m2mr 的解释器,要 numpy + 引用库):
    Motion2MixamoRig\.venv\Scripts\python.exe tests/slow.py
    Motion2MixamoRig\.venv\Scripts\python.exe tests/slow.py --clip <某个.glb>

测什么:
    1. 落地测量:向量化实现 vs 逐帧完整蒙皮的参考实现,逐帧偏差必须 < 1 微米
    2. 落地结果:逐帧最低点不得低于 0(不穿地),并打印统计
    3. 若给了 --clip,只测那一个;否则在 outputs/video_cap 下找一个 *_grounded.glb
"""

from __future__ import annotations

import argparse
import glob
import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TOOLS_DIR = os.path.join(ROOT, "Motion2MixamoRig", "tools")
sys.path.insert(0, TOOLS_DIR)

PASS, FAIL = [], []


def check(name: str, condition: bool, detail: str = "") -> None:
    """记一条断言结果,不抛异常,最后统一汇总。"""
    if condition:
        PASS.append(name)
        print("  [ok]   %s %s" % (name, detail))
    else:
        FAIL.append(name)
        print("  [FAIL] %s %s" % (name, detail))


def find_clip(explicit: str | None) -> str | None:
    """优先用显式给的路径,否则在交付目录里找一个 grounded 的 GLB。"""
    if explicit:
        return explicit if os.path.isfile(explicit) else None
    pattern = os.path.join(ROOT, "outputs", "video_cap", "*", "*grounded*.glb")
    found = sorted(glob.glob(pattern))
    return found[0] if found else None


def main() -> int:
    parser = argparse.ArgumentParser(description="动补产线慢测")
    parser.add_argument("--clip", default=None, help="要测的 GLB;缺省自动找")
    arguments = parser.parse_args()

    print("慢测（工程根 %s）" % ROOT)
    clip_path = find_clip(arguments.clip)
    if not clip_path:
        print("  [skip] 没有找到可测的 GLB（outputs/video_cap/*/*grounded*.glb）")
        print("\n结果：通过 0，失败 0（全部跳过）")
        return 0
    print("  待测文件 %s" % clip_path)

    try:
        import numpy as np
        import motion2mixamo_config as config

        config.ensure_reference_package_importable()
        from motion2mixamorig.diagnose import SkinnedClip
        import ground_character_on_floor as ground
    except (Exception, SystemExit) as exc:
        print("  [skip] 当前解释器拿不到动补依赖：%r" % (exc,))
        print("\n结果：通过 0，失败 0（全部跳过）")
        return 0

    print("\n1) 落地测量：向量化 vs 参考实现")
    clip = SkinnedClip(clip_path)
    started = time.time()
    reference = np.empty(clip.n_frames, dtype=np.float64)
    for frame in range(clip.n_frames):
        reference[frame] = min(float(part[:, 1].min()) for part in clip.skinned_positions(frame))
    reference_seconds = time.time() - started

    started = time.time()
    vectorised = ground.measure_lowest_vertex_per_frame(clip)
    vectorised_seconds = time.time() - started

    deviation_mm = float(np.abs(reference - vectorised).max()) * 1000.0
    check("逐帧偏差 < 1 微米", deviation_mm < 1e-3, "%.5f mm" % deviation_mm)
    check("帧数一致", len(reference) == len(vectorised) == clip.n_frames, str(clip.n_frames))
    print("  耗时：参考 %.1fs / 向量化 %.2fs（%.1f 倍）"
          % (reference_seconds, vectorised_seconds,
             reference_seconds / max(vectorised_seconds, 1e-9)))

    print("\n2) 落地结果")
    lowest_cm = vectorised * 100.0
    check("没有穿地帧（最低点 ≥ -0.01cm）", float(lowest_cm.min()) >= -0.01,
          "min=%.3fcm" % float(lowest_cm.min()))
    print("  最低点 min=%.2fcm 中位=%.2fcm max=%.2fcm；浮空>1cm %d 帧"
          % (lowest_cm.min(), float(np.median(lowest_cm)), lowest_cm.max(),
             int((lowest_cm > 1.0).sum())))

    print("\n结果：通过 %d，失败 %d" % (len(PASS), len(FAIL)))
    if FAIL:
        print("失败项：" + ", ".join(FAIL))
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
