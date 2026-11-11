#!/usr/bin/env python3
"""从关节名里认出四肢末端 —— 步态检查和循环检测都要用同一套规则。

为什么单独抽出来：不同资产命名差别很大（Hand/Foot、LowerLeg、Wing、Fin、Paw），
两处各写一份必然漂移。统一规则：

1. **腿脚优先**（foot/toe/leg/paw/hoof/shin/thigh）——翅膀和鳍是前肢的替代，
   只有在一条腿都找不到时才用（否则鸡会被判成"前脚是翅膀"）。
2. 标签只有"前/后 + 左/右"四种组合。**两足（人）和鸟的双腿都会被归到"后肢"**，
   因为它们没有参与步态的前肢；下游（make_loop / gait_report）只看下标，不受影响。
   四足才有"前"这一组，靠 front/arm/hand/fore 这些词区分。
2. 每侧、每前/后肢各取**链条最深**的那根（Shoulder < Upper < Lower < Foot）。
"""

from __future__ import annotations

LEG_HINTS = ("foot", "toe", "leg", "paw", "hoof", "shin", "thigh", "calf")
ARM_HINTS = ("hand", "arm", "fin", "wing")
ALL_HINTS = LEG_HINTS + ARM_HINTS


def _side(low: str):
    if ".l" in low or "left" in low or "_l_" in low or low.endswith("_l"):
        return "左"
    if ".r" in low or "right" in low or "_r_" in low or low.endswith("_r"):
        return "右"
    return None


def _depth(low: str) -> int:
    order = [("shoulder", 0), ("hip", 0), ("upper", 1), ("forearm", 2), ("shin", 2),
             ("lower", 3), ("hand", 4), ("foot", 4), ("paw", 4), ("hoof", 4),
             ("toe", 5), ("fetlock", 3)]
    d = 0
    for key, val in order:
        if key in low:
            d = max(d, val)
    return d


def find_limbs(joint_names):
    """返回 {标签: 关节下标}，标签形如 '前左' / '后右'。

    找不到任何腿脚时，退而用翅膀/鳍/手（鸟、鱼）。
    """
    use = LEG_HINTS
    if not any(any(h in n.lower() for h in LEG_HINTS) for n in joint_names):
        use = ALL_HINTS

    best = {}
    for i, n in enumerate(joint_names):
        low = n.lower()
        if not any(h in low for h in use):
            continue
        side = _side(low)
        if side is None:
            continue
        front = any(k in low for k in ("front", "arm", "hand", "fore", "wing", "fin"))
        back = any(k in low for k in ("back", "rear", "hind", "leg", "foot", "hoof", "toe"))
        if front and not back:
            kind = "前"
        elif back and not front:
            kind = "后"
        else:
            kind = "前" if front else "后"
        label = kind + side
        d = _depth(low)
        if label not in best or d > best[label][0]:
            best[label] = (d, i)
    return {k: v[1] for k, v in best.items()}
