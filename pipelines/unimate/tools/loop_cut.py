#!/usr/bin/env python3
"""切出循环片段：按给定周期裁一刀、补接缝、算接缝指标、下判定。

职责边界（只做这一件事，不找周期）
--------------------------------
- cut_loop：有周期就取这一段并把开头几帧朝后文混合；没周期就整段收拢
- seam_metrics：接缝差 = 几倍于"正常一步"
- foot_seam：接缝处脚差了几倍步长（四足/鸟才用）
- loop_verdict：一句人话判定

为什么要拆出来：这些是"怎么切"，和"切哪段"是两件事；混在一起时
改切法要读懂搜索逻辑，改搜索又要担心切法。
"""

from __future__ import annotations

import numpy as np

from cycle_search import POS, ROT, orthonormalize, rot_dist, median_step


def smoothstep(weight: float) -> float:
    """缓入缓出，让混合权重在两端变化慢、中间快。"""
    return weight * weight * (3.0 - 2.0 * weight)


def cut_loop(x: np.ndarray, period: int, seam: int, detrend: bool) -> tuple[np.ndarray, dict]:
    """把 (T, J, 12) 的动作做成一段可循环的片段。

    有周期（period < T）：取这一段，把开头 K 帧朝 x[period .. period+K) 混合，
      于是"最后一帧 -> 第 0 帧"等于原始数据里相邻的一步 —— 接缝不可见。
    无周期（period >= T）：整段保留，把最后 K 帧朝第 0 帧收拢，
      接缝处会有一帧停顿（1/30 秒），待机这种微动看不出来。
    """
    T, J, D = x.shape
    L = int(period)
    circular = L >= T
    K = int(min(seam, L // 2, (T - L) if not circular else L // 2))
    K = max(K, 0)

    src = x.copy()

    # 根节点的 XZ 位移不是存在位置通道里，而是由速度通道 [9]、[11] 积分出来的
    # （见 unimate/utils/motion_utils.recover_unimate_root_quat_and_pos），
    # 所以这里不动根位移；把动作做成原地由 tools/flatten_root.py 在导出后处理。
    drift = np.zeros(3, dtype=np.float32)

    out = src[:L].copy()

    if K > 0:
        for i in range(K):
            if circular:
                # 尾段朝第 0 帧收拢：out[L-1] 约等于 x[0]
                a = (i + 1) / float(K)
                j = T - K + i
                blend = src[j] * (1.0 - a) + src[0] * a
            else:
                # 头段朝尾巴靠：i=0 取 x[L]，i=K-1 取 x[K-1]
                w = smoothstep((K - i) / (K + 1.0))
                blend = src[L + i] * w + src[i] * (1.0 - w)
                j = i
            blend[:, ROT] = orthonormalize(blend[:, ROT])
            out[j] = blend

    out[:, :, ROT] = orthonormalize(out[:, :, ROT])
    return out, {"period": L, "seam_frames": K, "drift": drift.tolist(),
                 "mode": "head-hold" if circular else "periodic"}


def seam_metrics(x: np.ndarray, looped: np.ndarray, period: int) -> dict:
    """接缝前后差多少（都换算成"正常一步"的倍数）。"""
    rot0 = orthonormalize(x[:, :, ROT])
    med = median_step(x)
    before = rot_dist(rot0[0], rot0[min(period, len(rot0) - 1)])
    rl = orthonormalize(looped[:, :, ROT])
    after = rot_dist(rl[-1], rl[0])
    return {
        "median_step": med,
        "seam_before": before,
        "seam_after": after,
        "seam_before_ratio": (before / med) if med else float("nan"),
        "seam_after_ratio": (after / med) if med else float("nan"),
    }


def foot_seam(looped: np.ndarray, feet: dict, loop_mode: str) -> float | None:
    """接缝处脚差了几倍正常步长。

    整段收拢（head-hold）时首尾被强行拉平，这个值必然是 0，
    但那是"停一帧"而不是"接得完美"，所以这种情况返回 None，
    由 loop_verdict 用 loop_mode 单独说明。
    """
    if not feet:
        return None
    if loop_mode == "head-hold":
        return None
    pos = looped[:, list(feet.values()), POS].astype(np.float64)
    if len(pos) <= 1:
        return None
    step = float(np.median(np.linalg.norm(pos[1:] - pos[:-1], axis=-1).mean(-1)))
    if not step:
        return None
    seam = float(np.linalg.norm(pos[-1] - pos[0], axis=-1).mean())
    return seam / step


def loop_verdict(seam_ratio_before: float, seam_before_abs: float,
                 loop_mode: str, foot_seam_ratio: float | None) -> str:
    """给一句人话判断：先看脚（步态更看脚），再看旋转接缝。"""
    hold = loop_mode == "head-hold"

    if seam_ratio_before <= 1.5:
        verdict = "好循环"
    elif seam_ratio_before <= 3.0:
        verdict = "能循环，接缝靠淡化盖住"
    elif hold and seam_before_abs <= 0.2:
        verdict = "整段收拢，接缝很小"
    elif hold:
        verdict = "整段收拢，但接缝明显，建议重新采样这条"
    else:
        verdict = "不适合循环，建议重新采样这条"

    # 按脚找的周期，如果脚在接缝处差得多，优先级最高：这正是"看着一顿"的原因
    if not hold and foot_seam_ratio is not None and foot_seam_ratio > 1.4:
        verdict = "接缝处脚差了 %.1f 倍步长，建议换一条或加采样" % foot_seam_ratio
    return verdict
