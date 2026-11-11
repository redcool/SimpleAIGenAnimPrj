#!/usr/bin/env python3
"""找周期：在一段动作里定位"一轮动作"的起点与长度。

职责边界（只做这一件事，不切片段、不写文件）
------------------------------------------
- 按**四肢末端轨迹**找（默认，能认出四肢时）：脚回到同一位置 = 一轮结束
- 按**全身旋转**找（兜底）：姿态最接近的两帧
- 静止保护：脚几乎不动时不报周期（否则到处都是"相同帧"）
- 候选打分：周期误差达标之后，再挑"末帧到首帧最接近一个正常步长"的那条

为什么拆出来：这段逻辑改过四轮（锚定 → 双端点 → 按脚 → 行程约束），
和"切片段/接缝淡化"混在 470 行里时每次改都要通读全文。

特征布局：(T, J, 12) = 位置 3 + 相对 T-pose 的旋转 6 + 速度 3。
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

POS = slice(0, 3)
ROT = slice(3, 9)
VEL = slice(9, 12)


# ---------------------------------------------------------------------------
# 姿态相关的纯函数
# ---------------------------------------------------------------------------

def orthonormalize(rot6: np.ndarray) -> np.ndarray:
    """rot6（两个 3 维列向量）做 Gram-Schmidt，回到合法旋转表示。"""
    a = rot6[..., :3]
    b = rot6[..., 3:]
    a = a / (np.linalg.norm(a, axis=-1, keepdims=True) + 1e-8)
    b = b - (a * b).sum(-1, keepdims=True) * a
    b = b / (np.linalg.norm(b, axis=-1, keepdims=True) + 1e-8)
    return np.concatenate([a, b], axis=-1)


def rot_dist(r_a: np.ndarray, r_b: np.ndarray) -> float:
    """两帧姿态的差：所有关节旋转 6 维的 L2 均值。"""
    return float(np.linalg.norm(r_a - r_b, axis=-1).mean())


def median_step(x: np.ndarray) -> float:
    """相邻帧姿态变化的中位数，用作"一步"的尺度。"""
    rot = orthonormalize(x[:, :, ROT])
    steps = [rot_dist(rot[t], rot[t + 1]) for t in range(len(rot) - 1)]
    return float(np.median(steps)) if steps else 0.0


def foot_range(x: np.ndarray, feet: dict) -> float:
    """四肢在整段里的活动范围（每只脚 max-min 的均值）。

    判定"两帧像不像"必须拿这个当尺子：同样的绝对误差，
    对大步跑的狗是小误差，对小幅摆动的猫可能就是半个行程。
    """
    if not feet:
        return 0.0
    pos = x[:, list(feet.values()), POS].astype(np.float64)
    rng = pos.max(0) - pos.min(0)
    return float(np.linalg.norm(rng, axis=-1).mean())


def foot_step(x: np.ndarray, feet: dict) -> float:
    """每帧四肢末端的平均位移（把周期误差换算成相对量用）。"""
    if not feet:
        return 0.0
    pos = x[:, list(feet.values()), POS].astype(np.float64)
    steps = np.linalg.norm(pos[1:] - pos[:-1], axis=-1).mean(-1)
    return float(np.median(steps)) if steps.size else 0.0


# ---------------------------------------------------------------------------
# 两种搜索
# ---------------------------------------------------------------------------

def find_cycle(x: np.ndarray, lo: int, hi: int, start_max: int = None):
    """按全身旋转搜"起点 + 周期"。

    为什么不能从第 0 帧开始搜：完整周期可能落在轨道中间，
    从 0 帧切会把一次周期切成两半，接缝自然对不上。
    """
    T = x.shape[0]
    rot = orthonormalize(x[:, :, ROT])
    hi = min(hi, T - 2)
    if lo > hi:
        return 0, T, float("nan"), float("nan"), []
    if start_max is None:
        start_max = T - 2

    cands = []
    for L in range(lo, hi + 1):
        for s in range(0, min(start_max, T - L - 1) + 1):
            if s + L >= T:
                break
            e_pose = rot_dist(rot[s], rot[s + L])
            e_vel = 0.0
            if s + L + 1 < T:
                e_vel = rot_dist(rot[s + 1], rot[s + L + 1])
            cands.append((e_pose + 0.5 * e_vel, s, L, e_pose, e_vel))

    cands.sort(key=lambda c: c[0])
    near = [c for c in cands if c[0] <= cands[0][0] * 1.15 + 1e-6]
    best = min(near, key=lambda c: (c[2], c[1]))
    return best[1], best[2], best[3], best[4], [(c[1], c[2], round(c[0], 4)) for c in cands[:5]]


def find_cycle_feet(x: np.ndarray, feet: dict, lo: int, hi: int,
                    start_max: int = None, min_travel: float = 0.0):
    """按四肢末端的轨迹搜周期。

    短窗口里脚本来就没怎么动，"两帧相同"是白送的，所以先要求这段窗口内
    脚确实走完了一段路（min_travel），再比位置差。
    """
    T = x.shape[0]
    pos = x[:, list(feet.values()), POS].astype(np.float64)
    hi = min(hi, T - 2)
    if lo > hi:
        return 0, T, float("nan"), float("nan"), []
    if start_max is None:
        start_max = T - 2

    step_t = np.linalg.norm(pos[1:] - pos[:-1], axis=-1).mean(-1)
    cum = np.concatenate([[0.0], np.cumsum(step_t)])

    cands = []
    for L in range(max(lo, 2), hi + 1):
        for s in range(0, min(start_max, T - L - 1) + 1):
            if s + L >= T:
                break
            if (cum[s + L] - cum[s]) < min_travel:
                continue
            e = float(np.linalg.norm(pos[s] - pos[s + L], axis=-1).mean())
            ev = 0.0
            if s + 1 < T and s + L + 1 < T:
                ev = float(np.linalg.norm(pos[s + 1] - pos[s + L + 1], axis=-1).mean())
            cands.append((e + 0.5 * ev, s, L, e, ev))

    if not cands:
        return 0, T, float("nan"), float("nan"), []
    cands.sort(key=lambda c: c[0])
    near = [c for c in cands if c[0] <= cands[0][0] * 1.15 + 1e-9]
    best = min(near, key=lambda c: (c[2], c[1]))
    return best[1], best[2], best[3], best[4], [(c[1], c[2], round(c[0], 4)) for c in cands[:8]]


# ---------------------------------------------------------------------------
# 决策：把上面的搜索结果收敛成一个结论
# ---------------------------------------------------------------------------

@dataclass
class CycleOptions:
    """一次搜索的全部参数（从 CLI 传来的都是这些）。"""
    basis: str = "auto"                 # auto | feet | rot
    min_period: int = 20
    # None = 按片段长度自动放宽。60 帧的老素材仍按 58 算（历史行为不变），
    # 160 帧的长片段允许找到更长的周期，否则真周期会被上限切掉。
    max_period: int | None = None
    foot_min_period: int = 8
    min_foot_travel: float = 0.55
    foot_tolerance: float = 0.12
    min_foot_motion: float = 0.002
    period_tolerance: float = 1.5
    anchor: bool = False
    max_start: int | None = None
    forced_period: int | None = None


@dataclass
class CycleChoice:
    """搜索结论 + 过程数据，供上层写报告。"""
    start: int
    period: int
    cyclic: bool
    basis: str
    error: float = float("nan")
    velocity_error: float = float("nan")
    candidates: list = field(default_factory=list)
    seam_ratio: float | None = None      # 候选打分时算出的接缝比


def period_ceiling(x: np.ndarray, opts: CycleOptions) -> int:
    """周期搜索的上限：显式给了就用；没给就按片段长度放宽。

    历史默认 58 是给 60 帧素材定的；长片段（如 160 帧的串接）如果还按 58，
    真正的 70~90 帧周期会被直接切掉，表现成"找不到周期"。
    """
    T = x.shape[0]
    if opts.max_period:
        return int(opts.max_period)
    return int(max(58, T * 0.9))


def choose_cycle(x: np.ndarray, feet: dict, opts: CycleOptions) -> CycleChoice:
    """按依据选周期；静止或找不到时返回"整段"（period = 总帧数）。"""
    T = x.shape[0]
    ceiling = period_ceiling(x, opts)
    basis = opts.basis
    if basis == "auto":
        basis = "feet" if len(feet) >= 2 else "rot"

    if opts.forced_period:
        return CycleChoice(start=0, period=int(opts.forced_period), cyclic=True, basis=basis)

    if basis == "feet":
        smax = 0 if opts.anchor else opts.max_start
        lo = opts.min_period if opts.anchor else opts.foot_min_period
        med0 = foot_step(x, feet)
        rng = foot_range(x, feet)
        if med0 < opts.min_foot_motion or rng <= 0:
            # 脚基本不动 = 待机。此时"两帧脚相同"到处都是，
            # 不设保护会切出几帧的假循环，把细微动作裁掉。
            return CycleChoice(start=0, period=T, cyclic=False, basis="feet(静止,整段)")

        start, L, err, verr, cands = find_cycle_feet(
            x, feet, lo, min(ceiling, T - 2), start_max=smax,
            min_travel=opts.min_foot_travel * rng)

        # 周期误差小不等于接缝好看：先筛掉超容差的候选，
        # 再按"末帧到首帧那一步有多接近正常步长"挑一条。
        scored = []
        pos = x[:, list(feet.values()), POS].astype(np.float64)
        for s, Lc, cost in cands:
            end = s + Lc - 1
            if end >= T or s >= T or cost > opts.foot_tolerance * rng:
                continue
            seam = float(np.linalg.norm(pos[end] - pos[s], axis=-1).mean()) / med0
            scored.append((0.6 * abs(seam - 1.0) + cost / med0, seam, s, Lc, cost))

        seam_ratio = None
        if scored:
            scored.sort()
            _, seam_ratio, start, L, err = scored[0]
        else:
            start, L = 0, T
        return CycleChoice(start=int(start), period=int(L), cyclic=L < T, basis=basis,
                           error=err, velocity_error=verr, candidates=cands,
                           seam_ratio=seam_ratio)

    smax = 0 if opts.anchor else opts.max_start
    start, L, err, verr, cands = find_cycle(
        x, opts.min_period, min(ceiling, T - 2), start_max=smax)
    med0 = median_step(x)
    cyclic = bool(med0 > 0 and err < opts.period_tolerance * med0)
    if not cyclic:
        start, L = 0, T
    return CycleChoice(start=int(start), period=int(L), cyclic=cyclic, basis=basis,
                       error=err, velocity_error=verr, candidates=cands)