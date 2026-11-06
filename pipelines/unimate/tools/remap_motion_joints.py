#!/usr/bin/env python3
"""把一段动作的关节顺序重排成目标骨架的顺序（同一套骨架、不同排列时用）。

什么情况会用到
--------------
从动作库（比如 Mixamo）下的片段，和你的角色是同一套骨架、同样的骨名，
但导出时左右兄弟骨的排列顺序可能不同（LeftUpLeg 在前 还是 RightUpLeg 在前）。
UniMate 的 check_canonical_order 会直接报"joint order is not the motion's"。

这个工具按**骨名**把 npz 的关节轴重排到目标 cond 的顺序，不改任何数值。

用法
----
  python tools/remap_motion_joints.py \
      --input  outputs/rig/roll22/motions/roll22-mixamo_com-000.npz \
      --from-cond outputs/rig/roll22/cond.npy \
      --to-cond   outputs/rig/X_Bot/cond.npy \
      --out-dir   outputs/samples/roll_on_xbot/motions \
      --name      X_Bot-roll_lib-000.npz
"""

from __future__ import annotations

import argparse
import os

import numpy as np


def load_cond(path):
    d = np.load(path, allow_pickle=True).item()
    key = list(d)[0]
    return key, d[key]


def main():
    ap = argparse.ArgumentParser(description="按骨名重排动作的关节顺序")
    ap.add_argument("--input", required=True, help="要重排的 .npz")
    ap.add_argument("--from-cond", required=True, help="该 npz 对应的 cond.npy")
    ap.add_argument("--to-cond", required=True, help="目标骨架的 cond.npy")
    ap.add_argument("--out-dir", required=True, help="输出目录")
    ap.add_argument("--name", default=None, help="输出文件名，默认沿用原名")
    args = ap.parse_args()

    k_from, c_from = load_cond(args.from_cond)
    k_to, c_to = load_cond(args.to_cond)
    src_names = list(c_from["joint_names"])
    dst_names = list(c_to["joint_names"])

    missing = [n for n in dst_names if n not in src_names]
    if missing:
        raise SystemExit("目标骨架里有骨头在动作里找不到：%s" % missing)
    extra = [n for n in src_names if n not in dst_names]
    perm = [src_names.index(n) for n in dst_names]      # dst[i] <- src[perm[i]]

    print("源骨架 %s：%d 关节" % (k_from, len(src_names)))
    print("目标骨架 %s：%d 关节" % (k_to, len(dst_names)))
    if extra:
        print("动作里多出来的骨头（会被丢掉）：%s" % extra)
    print("重排映射（目标前 6 个）：%s" % [
        "%s<-%s" % (dst_names[i], src_names[perm[i]]) for i in range(min(6, len(perm)))])

    d = np.load(args.input)
    out = {}
    for key in d.files:
        arr = d[key]
        if arr.ndim >= 2 and arr.shape[1] == len(src_names):
            out[key] = arr[:, perm]                     # (T, J, ...) 重排关节轴
            print("  %-18s %s -> %s" % (key, arr.shape, out[key].shape))
        else:
            out[key] = arr
            print("  %-18s %s（不动）" % (key, arr.shape))

    os.makedirs(args.out_dir, exist_ok=True)
    name = args.name or os.path.basename(args.input)
    target = os.path.join(args.out_dir, name)
    np.savez(target, **out)
    print()
    print("写出：%s" % target)
    print("接下来用目标骨架的 cond 驱动：")
    print("  COND_PATH=%s ANIM_PATH=%s ..." % (args.to_cond, target))


if __name__ == "__main__":
    main()
