"""在 Blender 里给 GLB 加一块 z=0 的地板,渲染若干帧,用来看脚有没有真正贴地。

用法(Blender 无头模式):
    blender -b --factory-startup --python render_floor_contact_stills.py -- <输入.glb> <输出目录> <帧1,帧2,...> [前缀]

相机放在低角度三分之四视角:地面与鞋底之间的缝隙在这个角度最容易看出来。
"""
from __future__ import annotations

import logging
import os
import sys

import bpy
import mathutils

LOGGER = logging.getLogger("motion2mixamo.blender.stills")

CAMERA_LOCATION = (2.6, -2.6, 0.55)
CAMERA_TARGET = (0.0, 0.0, 0.12)
LENS_MILLIMETRES = 50
RESOLUTION_WIDTH = 900
RESOLUTION_HEIGHT = 700


def build_floor(plane_size: float = 6.0) -> None:
    """放一块 z=0 的地板,用中性灰,避免和角色糊在一起。"""
    bpy.ops.mesh.primitive_plane_add(size=plane_size, location=(0.0, 0.0, 0.0))
    floor = bpy.context.active_object
    floor.name = "Floor_z0"
    material = bpy.data.materials.new("floor_material")
    material.diffuse_color = (0.35, 0.35, 0.38, 1.0)
    floor.data.materials.append(material)


def build_camera() -> None:
    """低角度看向脚部与地面的交界。"""
    camera_data = bpy.data.cameras.new("Camera")
    camera = bpy.data.objects.new("Camera", camera_data)
    bpy.context.collection.objects.link(camera)
    camera.location = CAMERA_LOCATION
    direction = mathutils.Vector(CAMERA_TARGET) - mathutils.Vector(CAMERA_LOCATION)
    camera.rotation_euler = direction.to_track_quat("-Z", "Y").to_euler()
    camera_data.lens = LENS_MILLIMETRES
    bpy.context.scene.camera = camera


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="[%(name)s] %(message)s", stream=sys.stdout)
    arguments = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    if len(arguments) < 3:
        LOGGER.error("参数不足: 需要 <输入.glb> <输出目录> <帧列表> [前缀]")
        return 2
    glb_path, output_directory, frame_text = arguments[0], arguments[1], arguments[2]
    prefix = arguments[3] if len(arguments) > 3 else "shot"
    frames = [int(item) for item in frame_text.split(",") if item.strip()]

    bpy.ops.wm.read_factory_settings(use_empty=True)
    scene = bpy.context.scene
    scene.render.fps = 30
    scene.render.engine = "BLENDER_WORKBENCH"
    scene.render.resolution_x = RESOLUTION_WIDTH
    scene.render.resolution_y = RESOLUTION_HEIGHT

    bpy.ops.import_scene.gltf(filepath=glb_path)
    for obj in list(bpy.context.scene.objects):
        if obj.type == "MESH" and obj.name.startswith("Icosphere"):
            bpy.data.objects.remove(obj, do_unlink=True)

    build_floor()
    build_camera()

    os.makedirs(output_directory, exist_ok=True)
    for frame in frames:
        scene.frame_set(frame)
        scene.render.filepath = os.path.join(output_directory, f"{prefix}_f{frame:04d}.png")
        bpy.ops.render.render(write_still=True)
        LOGGER.info("已渲染 %s", scene.render.filepath)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
