#!/usr/bin/env python3
"""把生成动作做成可循环的片段（Unity 里 Loop Time 不用再硬凑）。

为什么要做
----------
模型固定生成 60 帧，起点是随机噪声，训练时也没有"首尾相接"这个约束，
所以第 0 帧和第 59 帧接不上。直接用 Unity 的 Loop Time 会在接缝处跳一下。

做法
----
1. **找周期**：在 [min, max] 帧范围里找一帧 L，使它的姿态最接近第 0 帧
   （只比旋转通道，旋转决定姿态，位置会因为原地漂移而对不齐）。
2. **切一刀**：取前 L 帧作为一个周期。
3. **接缝交叉淡化**：把开头 K 帧朝 x[L..L+K) 混合，让"第 L-1 帧 -> 第 0 帧"
   这一步变成和普通帧间一步一样。K 帧之后完全用原始数据。
4. **去掉根位移**（默认开）：减去这一周期内的线性漂移，让人在原点走，
   位移交给 Unity 的 CharacterController。否则循环时会往回弹。

判定不出周期时（比如待机），退回"整段 + 接缝淡化"，并在报告里说明。

特征布局：(T, J, 12) = 位置 3 + 相对 T-pose 的旋转 6 + 速度 3。
驱动网格时只用到根节点位置和每根骨头的旋转 6 维，速度通道不参与。

用法
----
  python tools/make_loop.py --samples UniMate/outputs/samples/X_Bot_locomotion
  python tools/make_loop.py --samples <dir> --only walks_forward --seam 6
  python tools/make_loop.py --samples <dir> --period 32 --no-detrend

产出
----
  <out>/motions/*.npy      循环后的动作（帧数 = 周期）
  <out>/manifest.json      复制原清单，条目指向新文件（run_animate_motion.sh 直接能用）
  <out>/loop_report.json   每个动作的周期、接缝指标、漂移量
"""

from __future__ import annotations

import argparse
import json
import math
import os
import shutil

import numpy as np

try:                                    # 版本号统一来自仓库根的 VERSION
    import pipeline_config as _cfg
    __version__ = _cfg.version()
except Exception:                       # 单独拷走这个文件也能跑
    __version__ = "0.0.0.0"

import sys
# 允许直接运行（不设 PYTHONPATH 也能 import 同目录模块）
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
try:                                    # 四肢识别与步态检查共用一套规则
    from rig_joints import find_limbs
except Exception:
    find_limbs = None

POS = slice(0, 3)
ROT = slice(3, 9)
VEL = slice(9, 12)


def log(msg: str) -> None:
    print(msg, flush=True)


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


def smoothstep(w: float) -> float:
    return w * w * (3.0 - 2.0 * w)


def find_cycle(x: np.ndarray, lo: int, hi: int, start_max: int = None):
    """同时搜"起点 s"和"周期 L"，找姿态 + 速度都最接得上的那一段。

    为什么不能从第 0 帧开始搜：完整周期可能落在轨道中间，
    从 0 帧切会把一次周期切成两半，接缝自然对不上。

    Returns:
        (start, L, err_pose, err_vel, 候选表)
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
            # 速度项：下一帧是否也接得上（只有 s+L+1 在范围内才算）
            e_vel = 0.0
            if s + L + 1 < T:
                e_vel = rot_dist(rot[s + 1], rot[s + L + 1])
            cands.append((e_pose + 0.5 * e_vel, s, L, e_pose, e_vel))

    cands.sort(key=lambda c: c[0])
    best = cands[0]
    # 代价接近时优先更短的周期，其次更靠前的起点
    near = [c for c in cands if c[0] <= best[0] * 1.15 + 1e-6]
    best = min(near, key=lambda c: (c[2], c[1]))
    return best[1], best[2], best[3], best[4], [(c[1], c[2], round(c[0], 4)) for c in cands[:5]]


def find_cycle_feet(x: np.ndarray, feet, lo: int, hi: int, start_max: int = None):
    """按四肢末端的轨迹找周期 —— 循环点由脚决定，而不是全身姿态。

    一段步态里脚回到同一位置就意味着一轮结束：在整段里找两帧"几只脚几乎相同"，
    前一帧当起点、后一帧当终点。躯干晃动不干扰判断。

    Returns:
        (start, L, 脚误差, 速度项误差, 候选表)
    """
    T = x.shape[0]
    pos = x[:, list(feet.values()), POS].astype(np.float64)
    hi = min(hi, T - 2)
    if lo > hi:
        return 0, T, float("nan"), float("nan"), []
    if start_max is None:
        start_max = T - 2

    cands = []
    for L in range(max(lo, 2), hi + 1):
        for s in range(0, min(start_max, T - L - 1) + 1):
            if s + L >= T:
                break
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


def foot_range(x: np.ndarray, feet) -> float:
    """四肢在整段里的活动范围（每只脚 max-min 的均值）。

    判定"两帧像不像"必须拿这个当尺子：同样的绝对误差，
    对大步跑的狗是小误差，对小幅摆动的猫可能就是半个行程。
    """
    if not feet:
        return 0.0
    pos = x[:, list(feet.values()), POS].astype(np.float64)
    rng = pos.max(0) - pos.min(0)                  # (F, 3)
    return float(np.linalg.norm(rng, axis=-1).mean())


def foot_step(x: np.ndarray, feet) -> float:
    """每帧四肢末端的平均位移（把周期误差换算成相对量用）。"""
    if not feet:
        return 0.0
    pos = x[:, list(feet.values()), POS].astype(np.float64)
    steps = np.linalg.norm(pos[1:] - pos[:-1], axis=-1).mean(-1)
    return float(np.median(steps)) if steps.size else 0.0


def make_loop(x: np.ndarray, period: int, seam: int, detrend: bool) -> tuple[np.ndarray, dict]:
    """把 (T, J, 12) 的动作做成一段可循环的片段。

    有周期（L < T）：取前 L 帧，把开头 K 帧朝 x[L .. L+K) 混合，
      于是"第 L-1 帧 -> 第 0 帧"等于原始数据里相邻的一步 —— 接缝不可见。
    无周期（L = T）：整段保留，把最后 K 帧朝第 0 帧收拢，
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


def median_step(x: np.ndarray) -> float:
    rot = orthonormalize(x[:, :, ROT])
    steps = [rot_dist(rot[t], rot[t + 1]) for t in range(len(rot) - 1)]
    return float(np.median(steps)) if steps else 0.0


def seam_metrics(x: np.ndarray, looped: np.ndarray, period: int) -> dict:
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


def main() -> None:
    ap = argparse.ArgumentParser(description="把生成动作做成可循环片段")
    ap.add_argument("--samples", required=True, help="采样目录（含 motions/ 和 manifest.json）")
    ap.add_argument("--out", default=None, help="输出目录，默认 <samples>_loop")
    ap.add_argument("--only", default=None, help="只处理文件名含此子串的动作")
    ap.add_argument("--min-period", type=int, default=20)
    ap.add_argument("--max-period", type=int, default=58)
    ap.add_argument("--seam", type=int, default=8, help="接缝交叉淡化帧数")
    ap.add_argument("--period", type=int, default=None, help="强制指定周期，跳过检测")
    ap.add_argument("--max-start", type=int, default=None,
                    help="起点搜索范围上限（默认到 T-L-1，即全片段）")
    ap.add_argument("--anchor", action="store_true",
                    help="退回旧行为：只从第 0 帧开始找周期")
    ap.add_argument("--no-detrend", action="store_true", help="（保留参数，已无作用；根位移交给 flatten_root.py）")
    ap.add_argument("--basis", choices=["auto", "feet", "rot"], default="auto",
                    help="找周期的依据：feet=按四肢末端轨迹（四足推荐），rot=按全身旋转，auto=能认出四肢就用 feet")
    ap.add_argument("--foot-min-period", type=int, default=8,
                    help="按脚找周期的最短周期（狗一轮跑步约 20~30 帧，太短会把噪声当周期）")
    ap.add_argument("--foot-tolerance", type=float, default=0.12,
                    help="按脚找周期时，两帧脚位差要小于「脚的行程」的这个比例才算循环（尺度无关）")
    ap.add_argument("--min-foot-motion", type=float, default=0.002,
                    help="四肢每帧平均位移低于此值当作静止（待机），不切周期")
    ap.add_argument("--period-tolerance", type=float, default=1.5,
                    help="检测到的周期误差超过中位步长的这个倍数时，判定为无周期")
    args = ap.parse_args()

    src_dir = os.path.abspath(args.samples)
    out_dir = os.path.abspath(args.out or (src_dir.rstrip("/\\\\") + "_loop"))
    motions_in = os.path.join(src_dir, "motions")
    if not os.path.isdir(motions_in):
        raise SystemExit(f"找不到 {motions_in}")
    motions_out = os.path.join(out_dir, "motions")
    os.makedirs(motions_out, exist_ok=True)

    manifest_path = os.path.join(src_dir, "manifest.json")
    manifest = None
    if os.path.isfile(manifest_path):
        with open(manifest_path, encoding="utf-8") as f:
            manifest = json.load(f)

    report = {"tool": "make_loop", "version": __version__,
              "samples": src_dir, "out": out_dir,
              "seam_requested": args.seam,
              "detrend": not args.no_detrend, "items": {}}

    files = sorted(f for f in os.listdir(motions_in) if f.endswith(".npy"))
    if args.only:
        files = [f for f in files if args.only in f]
    if not files:
        raise SystemExit("没有匹配的动作文件")

    new_samples = {}
    for name in files:
        x = np.load(os.path.join(motions_in, name)).astype(np.float32)
        T = x.shape[0]

        # 按关节名认出四肢末端（四足 / 鸟腿），据此决定用什么依据找周期
        feet = {}
        asset_key = ""
        if manifest:
            asset_key = (manifest.get("samples", {}).get(name, {}) or {}).get("asset", "")
        if find_limbs is not None and asset_key:
            jn = (manifest.get("assets", {}).get(asset_key, {}) or {}).get("joint_names")
            if jn and len(jn) == x.shape[1]:
                feet = find_limbs(jn)
        basis = args.basis
        if basis == "auto":
            basis = "feet" if len(feet) >= 2 else "rot"

        if args.period:
            start, L, err, verr, cands = 0, args.period, float("nan"), float("nan"), []
            cyclic = True
        elif basis == "feet":
            smax = 0 if args.anchor else args.max_start
            lo = args.min_period if args.anchor else args.foot_min_period
            med0 = foot_step(x, feet)
            rng = foot_range(x, feet)
            if med0 < args.min_foot_motion or rng <= 0:
                # 脚基本不动 = 待机。此时"两帧脚相同"到处都是，
                # 不设保护会切出几帧的假循环，把细微动作裁掉。
                start, L, err, verr, cands = 0, T, float("nan"), float("nan"), []
                cyclic = False
                basis = "feet(静止,整段)"
            else:
                start, L, err, verr, cands = find_cycle_feet(
                    x, feet, lo, min(args.max_period, T - 2), start_max=smax)
                # 周期误差小不等于接缝好看：先筛掉超容差的候选，
                # 再按"末帧到首帧那一步有多接近正常步长"挑一条。
                scored = []
                pos = x[:, list(feet.values()), POS].astype(np.float64)
                for s, Lc, cost in cands:
                    end = s + Lc - 1
                    if end >= T or s >= T or cost > args.foot_tolerance * rng:
                        continue
                    seam = float(np.linalg.norm(pos[end] - pos[s], axis=-1).mean()) / med0
                    scored.append((0.6 * abs(seam - 1.0) + cost / med0, seam, s, Lc, cost))
                if scored:
                    scored.sort()
                    _, seam_r, start, L, err = scored[0]
                    print("    [feet] 起点 %d 周期 %d 接缝比 %.2f（达标候选 %d 个）"
                          % (start, L, seam_r, len(scored)))
                else:
                    start, L = 0, T
                cyclic = L < T
        else:
            smax = 0 if args.anchor else args.max_start
            start, L, err, verr, cands = find_cycle(
                x, args.min_period, min(args.max_period, T - 2), start_max=smax)
            med0 = median_step(x)
            cyclic = (med0 > 0 and err < args.period_tolerance * med0)
            if not cyclic:
                start, L = 0, T

        looped, info = make_loop(x[start:] if L < T else x, L, args.seam, not args.no_detrend)
        info["start"] = int(start)
        x_seg = x[start:] if L < T else x
        m = seam_metrics(x_seg, looped, L)

        foot_seam_ratio = None
        if feet:
            fpos = looped[:, list(feet.values()), POS].astype(np.float64)
            if len(fpos) > 1:
                fstep = float(np.median(np.linalg.norm(fpos[1:] - fpos[:-1], axis=-1).mean(-1)))
                fseam = float(np.linalg.norm(fpos[-1] - fpos[0], axis=-1).mean())
                foot_seam_ratio = (fseam / fstep) if fstep else None

        np.save(os.path.join(motions_out, name), looped)
        report["items"][name] = {
            "frames_in": int(T), "frames_out": int(looped.shape[0]),
            "start_frame": int(info.get("start", 0)),
            "end_frame": int(info.get("start", 0) + info["period"]) if L < T else int(T),
            "period_detected": int(info["period"]), "cyclic": cyclic,
            "period_error": None if math.isnan(err) else round(err, 4),
            "velocity_error": None if math.isnan(verr) else round(verr, 4),
            "candidates": [{"start": c[0], "period": c[1], "cost": c[2]} for c in cands],
            "seam_frames": info["seam_frames"],
            "basis": basis,
            "foot_seam_ratio": None if foot_seam_ratio is None else round(foot_seam_ratio, 2),
            "foot_period_error": None if math.isnan(err) else round(err, 5),
            "feet": {k: v for k, v in (feet or {}).items()},
            "loop_mode": info["mode"],
            "root_drift_removed": [round(v, 4) for v in info["drift"]],
            "median_step": round(m["median_step"], 4),
            "seam_ratio_before": round(m["seam_before_ratio"], 2) if m["median_step"] else None,
            "seam_ratio_after": round(m["seam_after_ratio"], 2) if m["median_step"] else None,
        }
        if manifest and name in manifest.get("samples", {}):
            new_samples[name] = manifest["samples"][name]

        ratio_before = m["seam_before_ratio"] if m["median_step"] else float("nan")
        abs_before = m["seam_before"]
        ratio_after = m["seam_after_ratio"] if m["median_step"] else float("nan")
        hold = 1 if info["mode"] == "head-hold" else 0

        # 能不能循环：接缝原始误差越大，这条越难救
        if ratio_before <= 1.5:
            verdict = "好循环"
        elif ratio_before <= 3.0:
            verdict = "能循环，接缝靠淡化盖住"
        elif hold and abs_before <= 0.2:
            verdict = "整段收拢，接缝很小"
        elif hold:
            verdict = "整段收拢，但接缝明显，建议重新采样这条"
        else:
            verdict = "不适合循环，建议重新采样这条"

        # 按脚找的周期，如果脚在接缝处差得多，优先级最高：这正是"看着一顿"的原因
        if not hold and foot_seam_ratio is not None and foot_seam_ratio > 1.4:
            verdict = "接缝处脚差了 %.1f 倍步长，建议换一条或加采样" % foot_seam_ratio

        report["items"][name]["loop_verdict"] = verdict
        report["items"][name]["seam_before_abs"] = round(abs_before, 4)
        report["items"][name]["hold_frames"] = hold

        start_abs = int(info.get("start", 0))
        where = (f"片段 {start_abs}..{start_abs + info['period'] - 1}（{info['period']} 帧）"
                 if cyclic else "全片段收拢")
        log(f"  {name}")
        log(f"    {T} 帧 -> {looped.shape[0]} 帧，{where}  {verdict}")
        if m["median_step"]:
            log(f"    接缝：{ratio_before:.1f} 倍步长（绝对值 {abs_before:.3f}）-> "
                f"{ratio_after:.1f} 倍" + ("（收拢到同一帧）" if hold else ""))

    rows = sorted(
        ((k, v) for k, v in report["items"].items()),
        key=lambda kv: (kv[1]["seam_ratio_before"] if kv[1]["seam_ratio_before"] is not None else 9e9),
    )
    log("")
    log("循环质量（越小越好；同一条 prompt 挑这条用）：")
    for k, v in rows:
        rb = v["seam_ratio_before"]
        log(f"  {rb:>5.1f}  {v['frames_out']:>3d} 帧  {v['loop_verdict'][:16]:18s} {k}")

    if manifest is not None:
        manifest = dict(manifest)
        if new_samples:
            manifest["samples"] = new_samples
        manifest["looped_from"] = src_dir
        with open(os.path.join(out_dir, "manifest.json"), "w", encoding="utf-8") as f:
            json.dump(manifest, f, indent=2, ensure_ascii=False)

    with open(os.path.join(out_dir, "loop_report.json"), "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, ensure_ascii=False)

    log("")
    log(f"输出目录: {out_dir}")
    log("下一步（仓库根目录）：")
    log(f"  bash scripts/run_animate_motion.sh {out_dir}")


if __name__ == "__main__":
    main()