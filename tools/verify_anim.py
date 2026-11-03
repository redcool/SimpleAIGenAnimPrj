#!/usr/bin/env python3
"""核对一段导出的动画：是不是真在动，是不是真翻了。

两个容易混淆的事分开量：
  1. **整体翻转** —— 根骨累计转角 + 主轴（横轴 = 前/后滚翻）
  2. **四肢有没有动** —— 手/脚/头相对根节点的位置变化幅度

只有 1 没有 2，说明是"整体转了一圈但姿态没变"（看着像躺着被转了个圈）。

用法
----
  python tools/verify_anim.py --input <FBX/GLB 目录或单文件>
  python tools/verify_anim.py --input outputs/samples/roll_compare/anim
"""

from __future__ import annotations

import argparse
import glob
import os

import bpy
import numpy as np

LIMB_HINTS = ("hand", "foot", "toe", "head", "paw", "hoof", "wing", "tail")


def measure(path):
    bpy.ops.wm.read_factory_settings(use_empty=True)
    if path.lower().endswith(".fbx"):
        bpy.ops.import_scene.fbx(filepath=path)
    else:
        bpy.ops.import_scene.gltf(filepath=path)
    arms = [o for o in bpy.data.objects if o.type == "ARMATURE"]
    acts = list(bpy.data.actions)
    if not arms or not acts:
        return None
    arm, act = arms[0], acts[0]
    f0, f1 = int(act.frame_range[0]), int(act.frame_range[1])
    root = [pb for pb in arm.pose.bones if pb.parent is None][0]

    limb_bones = [pb for pb in arm.pose.bones
                  if pb.name != root.name and any(h in pb.name.lower() for h in LIMB_HINTS)]
    if not limb_bones:
        limb_bones = [pb for pb in arm.pose.bones if pb.name != root.name][:6]

    rots, limb_tracks, heights = [], {pb.name: [] for pb in limb_bones}, []
    for f in range(f0, f1 + 1):
        bpy.context.scene.frame_set(f)
        bpy.context.view_layer.update()
        rm = arm.matrix_world @ root.matrix
        rots.append(np.array(rm.to_quaternion().to_matrix()))
        heights.append(float(rm.translation.z))
        rpos = np.array(rm.translation)
        rrot = np.array(rm.to_quaternion().to_matrix())
        for pb in limb_bones:
            p = np.array((arm.matrix_world @ pb.matrix).translation)
            # 关键：转到根骨自己的坐标系里再比。
            # 整体翻滚会让四肢在世界里绕圈，但相对身体的姿势不变；
            # 只有"姿势在变"才是真的四肢动作。
            limb_tracks[pb.name].append(rrot.T @ (p - rpos))

    def angle(a, b):
        return float(np.degrees(np.arccos(np.clip((np.trace(a.T @ b) - 1) / 2, -1, 1))))

    total = sum(angle(rots[t], rots[t + 1]) for t in range(len(rots) - 1))
    best_t = max(range(1, len(rots)), key=lambda t: angle(rots[0], rots[t]))
    rel = rots[0].T @ rots[best_t]
    w = np.array([rel[2, 1] - rel[1, 2], rel[0, 2] - rel[2, 0], rel[1, 0] - rel[0, 1]])
    ax = w / (np.linalg.norm(w) + 1e-9)

    arts = {n: float(np.linalg.norm(np.array(v) - np.mean(v, axis=0), axis=1).mean())
            for n, v in limb_tracks.items()}
    # 骨架尺度：根到最远肢体的平均距离，用来把幅度归一化
    radius = float(np.mean([np.linalg.norm(v, axis=1).mean() for v in limb_tracks.values()]))
    return {
        "file": os.path.basename(path),
        "frames": f1 - f0 + 1,
        "root_rotation_deg": total,
        "axis": ax,
        "height_min": min(heights),
        "height_max": max(heights),
        "limb_amp": float(np.mean(list(arts.values()))) if arts else 0.0,
        "limb_rel": (float(np.mean(list(arts.values()))) / radius) if radius else 0.0,
        "limbs": arts,
    }


def verdict(r):
    """分开判断"整体翻转"和"四肢在不在动"。

    阈值来自实测：真翻滚的四肢动作幅度约占骨架 50%，只有整体旋转的约 7%。
    """
    spin = r["root_rotation_deg"] >= 320
    axis_ok = abs(r["axis"][0]) > 0.6
    rel = r["limb_rel"]
    moving = rel >= 0.15              # 真在动
    weak = 0.08 <= rel < 0.15         # 有一点，但不像完整动作

    if spin and axis_ok and moving:
        return "真翻滚（整体翻转 + 四肢在动）"
    if spin and not (moving or weak):
        return "只转了整体：四肢几乎不动（%.0f%%），看着像躺着被转一圈" % (100 * rel)
    if spin and weak:
        return "整体翻转明确，但四肢动作偏小（%.0f%%）" % (100 * rel)
    if spin:
        return "整体在转，主轴不是横向（更像转身/侧滚）"
    if moving:
        return "四肢在动但没翻（最多是弯腰/趴下）"
    return "既没翻也没怎么动（%.0f%%）" % (100 * rel)


def check(r, expect):
    """按期望类型判定；返回 (ok, 说明)。"""
    rel = r["limb_rel"]
    spin = r["root_rotation_deg"]
    axis_ok = abs(r["axis"][0]) > 0.6

    if expect == "roll":
        if spin >= 320 and axis_ok and rel >= 0.15:
            return True, "真翻滚（转角 %.0f°、四肢 %.0f%%）" % (spin, 100 * rel)
        if spin >= 320 and rel < 0.15:
            return False, "只转了整体（四肢仅 %.0f%%），不是翻滚" % (100 * rel)
        return False, "没翻够（累计 %.0f°）" % spin

    if expect == "motion":
        if rel < 0.05:
            return False, "四肢几乎不动（%.0f%%），这条动作大概率是废的" % (100 * rel)
        return True, "动作有效（四肢 %.0f%%）" % (100 * rel)

    # any：只报告，不拦
    return True, verdict(r)


def main():
    ap = argparse.ArgumentParser(description="核对动画：整体翻转 + 四肢动作")
    ap.add_argument("--input", required=True, help="FBX/GLB 文件或目录")
    ap.add_argument("--json", default=None, help="把指标写成 JSON")
    ap.add_argument("--expect", default="any", choices=["any", "motion", "roll"],
                    help="motion=只要求四肢在动；roll=要求整圈翻转；any=只报告")
    args = ap.parse_args()

    src = os.path.abspath(args.input)
    if os.path.isdir(src):
        fbx = {os.path.splitext(os.path.basename(f))[0] for f in glob.glob(os.path.join(src, "*.fbx"))}
        files = sorted(glob.glob(os.path.join(src, "*.fbx")))
        files += [f for f in sorted(glob.glob(os.path.join(src, "*.glb")))
                  if os.path.splitext(os.path.basename(f))[0] not in fbx]
    else:
        files = [src]

    rows, failed = [], 0
    for f in files:
        r = measure(f)
        if r is None:
            print("%-28s 读取失败" % os.path.basename(f)); failed += 1; continue
        print("=== %s ===" % r["file"])
        print("  %d 帧   根骨累计转角 %.0f°   主轴 [%+.2f %+.2f %+.2f]" % (
            r["frames"], r["root_rotation_deg"], *r["axis"]))
        print("  髋部高度 %.3f ~ %.3f   四肢移动幅度 %.3f（相对骨架 %.1f%%）" % (
            r["height_min"], r["height_max"], r["limb_amp"], 100 * r["limb_rel"]))
        top = sorted(r["limbs"].items(), key=lambda kv: -kv[1])[:3]
        print("  动得最多的部位: " + ", ".join("%s %.3f" % (k, v) for k, v in top))
        ok, note = check(r, args.expect)
        # 显式转成 Python 原生类型，否则 numpy 值会让 json.dump 中途失败
        rows.append({
            "file": r["file"], "frames": int(r["frames"]),
            "root_rotation_deg": round(float(r["root_rotation_deg"]), 1),
            "axis": [round(float(x), 3) for x in r["axis"]],
            "height_min": round(float(r["height_min"]), 3),
            "height_max": round(float(r["height_max"]), 3),
            "limb_amp": round(float(r["limb_amp"]), 3),
            "limb_rel": round(float(r["limb_rel"]), 3),
            "ok": bool(ok), "note": note,
        })
        tag = "" if args.expect == "any" else ("通过 — " if ok else "不通过 — ")
        print("  判定: %s%s" % (tag, note))
        print()
        if not ok:
            failed += 1

    if args.json:
        with open(args.json, "w", encoding="utf-8") as fh:
            import json as _json
            _json.dump({"expect": args.expect, "items": rows}, fh,
                       indent=2, ensure_ascii=False)
        print("已写出 %s" % args.json)
    if failed:
        print("%d 个文件没通过检查（expect=%s）" % (failed, args.expect))
        raise SystemExit(1)


if __name__ == "__main__":
    main()