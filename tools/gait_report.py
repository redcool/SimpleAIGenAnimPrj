#!/usr/bin/env python3
"""四足/多足步态速查：不用看视频，先用数字判断这条动作能不能用。

看三件事：
  1. 每条腿的竖直摆幅 —— 太小说明这条腿基本没动（动作废了）
  2. 四条腿之间的相位相关系数 —— 正=同相，负=反相
  3. 常见的合理步态模式（对角同相=小跑，前后同相=袭步）

用法：
  python tools/gait_report.py --samples outputs/samples/Fox
  python tools/gait_report.py --samples outputs/samples/Fox --only walks
"""

from __future__ import annotations

import argparse
import glob
import json
import os

import numpy as np

# 关节名里出现这些词就当作"脚"
# 四肢末端候选：名字里带这些词的骨头才算（不同资产的命名差别很大，
# 有 Foot/Hand，也有 LowerLeg / Hoof / Paw）
FOOT_HINTS = ("hand", "foot", "paw", "hoof", "toe", "leg", "arm", "fin", "wing")


def find_feet(joint_names):
    """从关节名里挑出四肢末端。

    不同资产命名差别很大（Hand/Foot、LowerLeg、Hoof、Paw），
    所以按"每一侧、每一前/后肢，取链条里最深的那根"来定位末端，
    而不是死认某个词。
    """
    def side_of(low):
        if ".l" in low or "left" in low or "_l_" in low:
            return "左"
        if ".r" in low or "right" in low or "_r_" in low:
            return "右"
        return None

    def depth_of(low):
        # 名字里越靠后的节数越深：shoulder < upper < lower < foot
        order = [("shoulder", 0), ("hip", 0), ("upper", 1), ("forearm", 2),
                 ("lower", 3), ("hand", 4), ("foot", 4), ("paw", 4),
                 ("hoof", 4), ("toe", 5), ("fetlock", 3)]
        d = 0
        for key, val in order:
            if key in low:
                d = max(d, val)
        return d

    best = {}
    for i, n in enumerate(joint_names):
        low = n.lower()
        if not any(h in low for h in FOOT_HINTS):
            continue
        side = side_of(low)
        if side is None:
            continue
        front = any(k in low for k in ("front", "arm", "hand", "fore", "wing"))
        back = any(k in low for k in ("back", "rear", "hind", "leg", "foot", "hoof", "fin"))
        # 前后都不明确时按"有没有 arm/hand"归前肢
        kind = "前" if front and not back else ("后" if back and not front else ("前" if front else "后"))
        label = kind + side
        d = depth_of(low)
        if label not in best or d > best[label][0]:
            best[label] = (d, i)
    return {k: v[1] for k, v in best.items()}


def analyze(path, names):
    a = np.load(path)
    F, J, D = a.shape
    feet = find_feet(names)
    out = {"file": os.path.basename(path), "frames": int(F),
           "strength": float(np.abs(a - a.mean(0, keepdims=True)).mean()), "limbs": {}}
    if len(feet) < 2:
        return out, feet

    series = {}
    for label, idx in feet.items():
        y = a[:, idx, 1]
        y = y - y.mean()
        series[label] = y
        out["limbs"][label] = {"joint": names[idx], "amplitude": float(y.std())}

    keys = list(series)
    phase = {}
    for i in range(len(keys)):
        for j in range(i + 1, len(keys)):
            if series[keys[i]].std() < 1e-9 or series[keys[j]].std() < 1e-9:
                continue
            c = float(np.corrcoef(series[keys[i]], series[keys[j]])[0, 1])
            phase["%s-%s" % (keys[i], keys[j])] = round(c, 2)
    out["phase"] = phase
    return out, feet


def verdict(res):
    """给一句人话判断。判断不了就说判断不了。"""
    limbs = res.get("limbs") or {}
    if not limbs:
        return "没找到脚关节，跳过"
    amps = [v["amplitude"] for v in limbs.values()]
    if max(amps) < 1e-3:
        return "几乎不动（这条废了，换一条）"
    # 幅度很小的先判掉：静止时相位是噪声，硬套步态结论会得出"待机=袭步"这种胡话
    if max(amps) < 0.012:
        return "动作幅度很小（待机级别，不是步态；待机动作本来就该这样）"
    if min(amps) < max(amps) * 0.15:
        return "有腿几乎不动（可能只动了半身）"

    ph = res.get("phase", {})

    def g(a, b):
        return ph.get("%s-%s" % (a, b))

    diag = [x for x in (g("后左", "前右"), g("后右", "前左")) if x is not None]
    lat = [x for x in (g("后右", "后左"), g("前右", "前左")) if x is not None]
    md = sum(diag) / len(diag) if diag else None
    ml = sum(lat) / len(lat) if lat else None

    if md is not None and ml is not None:
        if md > 0.4 and ml < -0.3:
            return "对角同相 + 左右反相 → 小跑/快走（对角 %+.2f，左右 %+.2f）" % (md, ml)
        if ml > 0.6:
            return "前后各自同相 → 袭步/跳跃式（左右 %+.2f），跑动正常" % ml
        if abs(md) < 0.25 and abs(ml) < 0.25:
            return "相位很弱，不像成型步态（建议多采几条挑）"

    if res.get("strength", 1.0) < 0.008:
        return "动作幅度很小，可能只是轻微晃动"
    return "相位不典型，需看视频确认"


def main():
    ap = argparse.ArgumentParser(description="多足动作的步态速查")
    ap.add_argument("--samples", required=True, help="采样目录（含 motions/ 和 manifest.json）")
    ap.add_argument("--only", default=None, help="只处理文件名含此子串的动作")
    ap.add_argument("--json", default=None, help="把结果写成 JSON")
    args = ap.parse_args()

    S = os.path.abspath(args.samples)
    man = json.load(open(os.path.join(S, "manifest.json"), encoding="utf-8"))
    asset = next(iter(man["assets"].values()))
    names = asset["joint_names"]

    files = sorted(glob.glob(os.path.join(S, "motions", "*.npy")))
    if args.only:
        files = [f for f in files if args.only in f]
    if not files:
        raise SystemExit("没有动作文件")

    rows = []
    for f in files:
        res, feet = analyze(f, names)
        res["verdict"] = verdict(res)
        rows.append(res)
        print("=== %s ===" % res["file"])
        print("  %d 帧  整体强度 %.4f" % (res["frames"], res["strength"]))
        for label, info in res["limbs"].items():
            print("    %s %-24s 竖直摆幅 %.4f" % (label, info["joint"], info["amplitude"]))
        if res.get("phase"):
            pairs = "  ".join("%s:%+.2f" % (k, v) for k, v in res["phase"].items())
            print("    相位 " + pairs)
        print("  判定: " + res["verdict"])
        print()

    if args.json:
        with open(args.json, "w", encoding="utf-8") as fh:
            json.dump(rows, fh, indent=2, ensure_ascii=False)
        print("已写出 %s" % args.json)


if __name__ == "__main__":
    main()