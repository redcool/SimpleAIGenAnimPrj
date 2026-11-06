"""把 m2mr 产出的 mixamo_character*.glb 转成二进制 FBX(Unity 原生可导入)。

用法(Blender 无头模式):
    blender -b --factory-startup --python export_character_fbx.py -- <输入.glb> <输出.fbx> [帧率]

做三件事:
1. 丢掉 glTF 导入器自带的 Icosphere 骨骼显示球,只导出骨架 + 带 Armature 修改器的网格;
2. 把动画统一到从第 0 帧开始,避免不同版本 Blender 的偏移差异;
3. 烘帧导出(每帧一个关键帧),保证 Unity 侧看到的是同一条动作。
"""
from __future__ import annotations

import json
import logging
import os
import sys

import bpy

LOGGER = logging.getLogger("motion2mixamo.blender.fbx")


def iter_action_fcurves(action) -> list:
    """取出一条 action 的全部 F-curve,兼容旧 API 与 4.4+/5.x 的分层 action。"""
    legacy = getattr(action, "fcurves", None)
    if legacy is not None:
        return list(legacy)
    collected = []
    for layer in getattr(action, "layers", []):
        for strip in getattr(layer, "strips", []):
            for slot in getattr(action, "slots", []):
                channelbag = strip.channelbag(slot)
                if channelbag is not None:
                    collected.extend(channelbag.fcurves)
    return collected


def shift_curves_to_zero(curves: list) -> tuple[float, float, float]:
    """把关键帧整体平移到从 0 开始,返回(平移前最小帧, 平移前最大帧, 平移量)。"""
    frames = [keyframe.co[0] for curve in curves for keyframe in curve.keyframe_points]
    if not frames:
        return 0.0, 0.0, 0.0
    smallest, largest = min(frames), max(frames)
    shift = -smallest if abs(smallest) > 1e-6 else 0.0
    if shift:
        for curve in curves:
            for keyframe in curve.keyframe_points:
                keyframe.co[0] += shift
                keyframe.handle_left[0] += shift
                keyframe.handle_right[0] += shift
    return smallest, largest, shift


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="[%(name)s] %(message)s", stream=sys.stdout)
    arguments = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    if len(arguments) < 2:
        LOGGER.error("参数不足: 需要 <输入.glb> <输出.fbx> [帧率]")
        return 2
    glb_path, fbx_path = arguments[0], arguments[1]
    frames_per_second = float(arguments[2]) if len(arguments) > 2 else 30.0

    bpy.ops.wm.read_factory_settings(use_empty=True)
    scene = bpy.context.scene
    scene.render.fps = int(round(frames_per_second))
    scene.render.fps_base = 1.0

    bpy.ops.import_scene.gltf(filepath=glb_path)
    imported_objects = list(bpy.context.scene.objects)
    armature = next((obj for obj in imported_objects if obj.type == "ARMATURE"), None)
    skinned_meshes = [obj for obj in imported_objects if obj.type == "MESH"
                      and any(modifier.type == "ARMATURE" for modifier in obj.modifiers)]
    helpers = [obj for obj in imported_objects if obj not in skinned_meshes and obj is not armature]
    for helper in helpers:
        bpy.data.objects.remove(helper, do_unlink=True)

    report: dict = {
        "glb": glb_path,
        "armature": armature.name if armature else None,
        "bone_count": len(armature.data.bones) if armature else 0,
        "skinned_meshes": [{"name": mesh.name, "vertices": len(mesh.data.vertices),
                            "polygons": len(mesh.data.polygons)} for mesh in skinned_meshes],
        "dropped_helpers": [helper.name for helper in helpers],
    }

    animation: dict = {}
    if armature and armature.animation_data and armature.animation_data.action:
        action = armature.animation_data.action
        curves = iter_action_fcurves(action)
        smallest, largest, shift = shift_curves_to_zero(curves)
        animation = {"action": action.name, "fcurve_count": len(curves),
                     "first_frame_before": smallest, "last_frame_before": largest,
                     "shift_applied": shift, "first_frame": smallest + shift,
                     "last_frame": largest + shift}
        scene.frame_start = 0
        scene.frame_end = int(round(largest + shift))
    report["animation"] = animation

    bpy.ops.object.select_all(action="DESELECT")
    for obj in ([armature] if armature else []) + skinned_meshes:
        obj.select_set(True)
    bpy.context.view_layer.objects.active = armature if armature else (skinned_meshes[0] if skinned_meshes else None)

    os.makedirs(os.path.dirname(fbx_path) or ".", exist_ok=True)
    bpy.ops.export_scene.fbx(
        filepath=fbx_path,
        use_selection=True,
        object_types={"ARMATURE", "MESH"},
        apply_scale_options="FBX_SCALE_NONE",
        axis_forward="-Z",
        axis_up="Y",
        global_scale=1.0,
        bake_anim=True,
        bake_anim_use_all_actions=False,
        bake_anim_use_nla_strips=False,
        bake_anim_force_startend_keying=True,
        bake_anim_step=1.0,
        bake_anim_simplify_factor=0.0,
        add_leaf_bones=False,
        primary_bone_axis="Y",
        secondary_bone_axis="X",
        mesh_smooth_type="FACE",
        use_mesh_modifiers=True,
        path_mode="COPY",
        embed_textures=False,
        use_custom_props=False,
    )
    report["fbx"] = fbx_path
    report["fbx_bytes"] = os.path.getsize(fbx_path)
    LOGGER.info("导出完成 %s", json.dumps(report, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
