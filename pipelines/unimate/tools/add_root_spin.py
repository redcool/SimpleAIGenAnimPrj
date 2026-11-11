#!/usr/bin/env python3
"""给已有动画的根骨叠加一圈旋转（翻滚、侧翻、转身）。

为什么需要：UniMate 的根节点旋转通道只当"朝向"用（实测所有生成动作里，
根骨相对首帧的最大偏转 26°，轴永远是竖直方向 = 只做偏航）。
所以模型生成不出 360° 前滚翻。补救办法是拿模型生成的"倒在地上"的片段，
在导出前给根骨补一圈俯仰。

原理
----
把额外旋转 Q 叠加到根骨的世界朝向上：
    R_world' = Q @ R_world,  R_world = B @ R_bone
  => R_bone' = B⁻¹ @ Q @ B @ R_bone
B 是根骨的 rest 矩阵（只取旋转部分），所以旋转轴按骨架空间解释。

用法
----
  python tools/add_root_spin.py --input clip.fbx --turns 1
  python tools/add_root_spin.py --input <目录> --turns 1 --axis lateral --out <目录>_spin
  python tools/add_root_spin.py --input clip.fbx --turns 1 --axis vertical   # 转身
"""

from __future__ import annotations

import argparse
import glob
import json
import os
import re

import bpy
from mathutils import Matrix, Quaternion, Vector

try:                                    # 版本号唯一来源是仓库根的 VERSION
    import pipeline_config as _cfg
except Exception:
    _cfg = None

AXES = {
    "lateral": Vector((1.0, 0.0, 0.0)),    # 横轴：前滚翻 / 后滚翻
    "vertical": Vector((0.0, 0.0, 1.0)),   # 竖直轴：原地转身
    "forward": Vector((0.0, 1.0, 0.0)),    # 前后轴：侧翻
}


def log(msg):
    print(msg, flush=True)


def unique(path):
    if not os.path.exists(path):
        return path
    stem, ext = os.path.splitext(path)
    m = re.match(r"^(.*)_v(\d+)$", stem)
    base, n = (m.group(1), int(m.group(2)) + 1) if m else (stem, 2)
    while os.path.exists("%s_v%d%s" % (base, n, ext)):
        n += 1
    return "%s_v%d%s" % (base, n, ext)


def add_spin(path, turns, axis_name, out_dir, formats, ease):
    bpy.ops.wm.read_factory_settings(use_empty=True)
    if path.lower().endswith(".fbx"):
        bpy.ops.import_scene.fbx(filepath=path)
    else:
        bpy.ops.import_scene.gltf(filepath=path)

    arms = [o for o in bpy.data.objects if o.type == "ARMATURE"]
    if not arms:
        raise SystemExit("%s 里没有 armature" % path)
    arm = arms[0]
    roots = [pb for pb in arm.pose.bones if pb.parent is None]
    if not roots:
        raise SystemExit("找不到根骨")
    root = roots[0]

    act = arm.animation_data.action if arm.animation_data else None
    if act is None:
        raise SystemExit("%s 里没有动画" % path)
    f0, f1 = int(act.frame_range[0]), int(act.frame_range[1])
    n = max(1, f1 - f0)

    # 根骨 rest 朝向（骨架空间）
    B = root.bone.matrix_local.to_quaternion()
    B_inv = B.conjugated()
    axis = AXES[axis_name].normalized()

    # 找旋转曲线
    quat_curves = {fc.array_index: fc for fc in act.fcurves
                   if fc.data_path == 'pose.bones["%s"].rotation_quaternion' % root.name}
    euler_curves = {fc.array_index: fc for fc in act.fcurves
                    if fc.data_path == 'pose.bones["%s"].rotation_euler' % root.name}
    if not quat_curves and not euler_curves:
        raise SystemExit("根骨上没有旋转曲线（%s）" % root.name)

    use_quat = bool(quat_curves)
    log("  根骨 %s，用 %s 曲线，%d 帧，加 %.2f 圈（%s 轴）" % (
        root.name, "quaternion" if use_quat else "euler", n + 1, turns, axis_name))

    for f in range(f0, f1 + 1):
        t = (f - f0) / float(n)
        if ease == "smoothstep":
            t = t * t * (3.0 - 2.0 * t)
        angle = 2.0 * 3.141592653589793 * turns * t
        q_extra = Quaternion(axis, angle)
        # 世界侧叠加 -> 换算到骨骼局部侧
        q_add = B_inv @ q_extra @ B

        if use_quat:
            q = Quaternion([quat_curves[i].evaluate(f) if i in quat_curves else
                            (1.0 if i == 0 else 0.0) for i in range(4)])
            q_new = q_add @ q
            for i in range(4):
                fc = quat_curves[i]
                kp = next((k for k in fc.keyframe_points if abs(k.co[0] - f) < 0.5), None)
                if kp is None:
                    continue
                kp.co[1] = q_new[i]
                kp.handle_left[1] = q_new[i]
                kp.handle_right[1] = q_new[i]
        else:
            e = [euler_curves[i].evaluate(f) if i in euler_curves else 0.0 for i in range(3)]
            q = Quaternion(e)
            q_new = q_add @ q
            e_new = q_new.to_euler()
            for i in range(3):
                fc = euler_curves.get(i)
                if fc is None:
                    continue
                kp = next((k for k in fc.keyframe_points if abs(k.co[0] - f) < 0.5), None)
                if kp is None:
                    continue
                kp.co[1] = e_new[i]
                kp.handle_left[1] = e_new[i]
                kp.handle_right[1] = e_new[i]

    for fc in list(quat_curves.values()) + list(euler_curves.values()):
        fc.update()

    stem = os.path.splitext(os.path.basename(path))[0]
    outs = []
    for fmt in formats:
        target = unique(os.path.join(out_dir, "%s_spin.%s" % (stem, fmt)))
        if fmt == "fbx":
            bpy.ops.export_scene.fbx(filepath=target, use_selection=False,
                                     add_leaf_bones=False, bake_anim=True)
        else:
            bpy.ops.export_scene.gltf(filepath=target, export_format="GLB",
                                      export_animations=True, export_yup=True)
        outs.append(target)
    return {"input": path, "frames": n + 1, "turns": turns,
            "axis": axis_name, "outputs": outs}


def main():
    ap = argparse.ArgumentParser(description="给根骨叠加旋转（翻滚/转身）")
    ap.add_argument("--input", required=True, help="带动画的 FBX/GLB，或一个目录")
    ap.add_argument("--out", default=None, help="输出目录，默认 <输入>_spin")
    ap.add_argument("--turns", type=float, default=1.0, help="圈数，1 = 360°，负值反向")
    ap.add_argument("--axis", default="lateral", choices=sorted(AXES),
                    help="lateral=前滚翻，vertical=转身，forward=侧翻")
    ap.add_argument("--ease", default="linear", choices=["linear", "smoothstep"],
                    help="转速曲线，smoothstep 起止慢")
    ap.add_argument("--formats", default="fbx", help="逗号分隔：fbx,glb")
    args = ap.parse_args()

    src = os.path.abspath(args.input)
    if os.path.isdir(src):
        fbx = {os.path.splitext(os.path.basename(f))[0] for f in glob.glob(os.path.join(src, "*.fbx"))}
        files = sorted(glob.glob(os.path.join(src, "*.fbx")))
        files += [f for f in sorted(glob.glob(os.path.join(src, "*.glb")))
                  if os.path.splitext(os.path.basename(f))[0] not in fbx]
        out_dir = os.path.abspath(args.out or (src.rstrip("/") + "_spin"))
    else:
        files = [src]
        out_dir = os.path.abspath(args.out or (os.path.dirname(src) + "_spin"))
    os.makedirs(out_dir, exist_ok=True)

    formats = [f.strip().lstrip(".") for f in args.formats.split(",") if f.strip()]
    report = {"tool": "add_root_spin",
              "version": (_cfg.version() if _cfg else "0.0.0.0"), "items": []}
    for f in files:
        log("== %s" % os.path.basename(f))
        r = add_spin(f, args.turns, args.axis, out_dir, formats, args.ease)
        report["items"].append(r)
        for o in r["outputs"]:
            log("  -> %s" % o)

    with open(os.path.join(out_dir, "spin_report.json"), "w", encoding="utf-8") as fh:
        json.dump(report, fh, indent=2, ensure_ascii=False)
    log("")
    log("输出：%s" % out_dir)


if __name__ == "__main__":
    main()