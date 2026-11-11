"""把角色真正压到 y = 0 的地面上。

上游 m2mr 的落地只按"主导权重属于脚骨的顶点"估计鞋底,而且只保证每段接触里
最低的那一帧贴地,实测仍有 34% 的帧浮空(最高 +4.9cm)、42% 的帧陷地(最深 -6cm)。

本工具改用 GLB 自身的蒙皮逐帧算**全部顶点**的最低 y(和观看者看到的一致),
着地帧压到 0,非着地帧在相邻着地帧之间插值并夹紧到不低于 0,再把这个偏移
写进 Hips 的 translation 通道。不触碰引用库。

用法:
    python ground_character_on_floor.py <run目录或glb> [--out 文件] [--always-ground] [--report]
"""
from __future__ import annotations

import argparse
import json
import logging
import struct
import sys
from pathlib import Path

import numpy as np

LOGGER = logging.getLogger("motion2mixamo.ground")

TOOLS_ROOT = Path(__file__).resolve().parent
if str(TOOLS_ROOT) not in sys.path:
    sys.path.insert(0, str(TOOLS_ROOT))

import motion2mixamo_config as config  # noqa: E402

config.ensure_reference_package_importable()
from motion2mixamorig.diagnose import SkinnedClip  # noqa: E402  (只读引用)

GLB_MAGIC = 0x46546C67
JSON_CHUNK_TYPE = 0x4E4F534A
BINARY_CHUNK_TYPE = 0x004E4942
FLOAT32_COMPONENT_TYPE = 5126
VECTOR_THREE_COMPONENTS = 3


def read_glb(path: Path) -> tuple[dict, bytearray]:
    """拆出 JSON 与 BIN 两个 chunk;只支持标准 GLB 2.0。"""
    data = path.read_bytes()
    magic, version, _length = struct.unpack_from("<III", data, 0)
    if magic != GLB_MAGIC:
        raise ValueError(f"不是 GLB 文件: {path}")
    offset = 12
    gltf_json: dict = {}
    binary = bytearray()
    while offset < len(data):
        chunk_length, chunk_type = struct.unpack_from("<II", data, offset)
        offset += 8
        chunk = data[offset : offset + chunk_length]
        if chunk_type == JSON_CHUNK_TYPE:
            gltf_json = json.loads(chunk.decode("utf-8"))
        elif chunk_type == BINARY_CHUNK_TYPE:
            binary = bytearray(chunk)
        offset += chunk_length
    return gltf_json, binary


def write_glb(path: Path, gltf_json: dict, binary: bytes) -> None:
    """按 GLB 2.0 重新打包。"""
    json_bytes = json.dumps(gltf_json, separators=(",", ":")).encode("utf-8")
    json_bytes += b" " * ((4 - len(json_bytes) % 4) % 4)
    binary_bytes = bytes(binary) + b"\x00" * ((4 - len(binary) % 4) % 4)
    total_length = 12 + 8 + len(json_bytes) + 8 + len(binary_bytes)
    payload = bytearray()
    payload += struct.pack("<III", GLB_MAGIC, 2, total_length)
    payload += struct.pack("<II", len(json_bytes), JSON_CHUNK_TYPE) + json_bytes
    payload += struct.pack("<II", len(binary_bytes), BINARY_CHUNK_TYPE) + binary_bytes
    path.write_bytes(bytes(payload))


def find_hips_node_index(gltf_json: dict) -> int:
    """找到 Hips 节点;骨骼名可能是 mixamorig:Hips。"""
    for index, node in enumerate(gltf_json.get("nodes", [])):
        name = (node.get("name") or "").split(":")[-1]
        if name == "Hips":
            return index
    raise KeyError("GLB 里找不到 Hips 节点")


def find_hips_translation_accessor(gltf_json: dict, hips_node_index: int) -> int:
    """定位 Hips 的 translation 动画通道输出。"""
    for animation in gltf_json.get("animations", []):
        for channel in animation.get("channels", []):
            target = channel.get("target", {})
            if target.get("node") == hips_node_index and target.get("path") == "translation":
                sampler = animation["samplers"][channel["sampler"]]
                return int(sampler["output"])
    raise KeyError("GLB 里没有 Hips 的 translation 通道")


def resolve_accessor_layout(gltf_json: dict, accessor_index: int) -> tuple[int, int, int, int]:
    """返回 (起始字节, 元素个数, 每元素分量数, 步长)。"""
    accessor = gltf_json["accessors"][accessor_index]
    if accessor["componentType"] != FLOAT32_COMPONENT_TYPE:
        raise ValueError("只支持 float32 的 Hips translation")
    buffer_view = gltf_json["bufferViews"][accessor["bufferView"]]
    component_count = {"SCALAR": 1, "VEC2": 2, "VEC3": 3, "VEC4": 4}[accessor["type"]]
    start_offset = buffer_view.get("byteOffset", 0) + accessor.get("byteOffset", 0)
    stride = buffer_view.get("byteStride") or (4 * component_count)
    return start_offset, int(accessor["count"]), component_count, int(stride)


def measure_lowest_vertex_per_frame(clip: SkinnedClip) -> np.ndarray:
    """逐帧取所有蒙皮顶点的最低 y(米)。"""
    lowest = np.empty(clip.n_frames, dtype=np.float64)
    for frame_index in range(clip.n_frames):
        posed_parts = clip.skinned_positions(frame_index)
        lowest[frame_index] = min(float(part[:, 1].min()) for part in posed_parts)
    return lowest


def read_foot_contact(run_directory: Path, frame_count: int) -> np.ndarray | None:
    """读取上游写的 4 通道脚部接触概率;长度不符就当没有。"""
    skeleton_path = run_directory / "skeleton_motion.npz"
    if not skeleton_path.exists():
        return None
    with np.load(skeleton_path, allow_pickle=True) as payload:
        if "foot_contact" not in payload:
            return None
        contact = np.asarray(payload["foot_contact"], dtype=np.float64)
    return contact if len(contact) == frame_count else None


def compute_vertical_offsets(
    lowest_vertex: np.ndarray,
    contact: np.ndarray | None,
    always_ground: bool,
) -> np.ndarray:
    """算每帧要加给髋部的高度偏移(米)。"""
    frame_count = len(lowest_vertex)
    if always_ground or contact is None:
        planted = np.ones(frame_count, dtype=bool)
    else:
        planted = (contact[:, 1] > 0.5) | (contact[:, 3] > 0.5)

    offsets = np.zeros(frame_count, dtype=np.float64)
    offsets[planted] = -lowest_vertex[planted]
    planted_indices = np.flatnonzero(planted)
    if len(planted_indices) == 0:
        return -lowest_vertex
    if planted_indices[0] > 0:
        offsets[: planted_indices[0]] = offsets[planted_indices[0]]
    if planted_indices[-1] < frame_count - 1:
        offsets[planted_indices[-1] :] = offsets[planted_indices[-1]]
    for left, right in zip(planted_indices, planted_indices[1:]):
        if right - left <= 1:
            continue
        ramp = np.linspace(offsets[left], offsets[right], right - left + 1)[1:-1]
        offsets[left + 1 : right] = ramp
    # 不允许穿地
    return np.maximum(offsets, -lowest_vertex)


def describe(heights_centimetres: np.ndarray) -> str:
    """一行摘要,便于比对修复前后。"""
    return (
        f"min={heights_centimetres.min():+.2f}cm "
        f"median={np.median(heights_centimetres):+.2f}cm "
        f"p95={np.percentile(heights_centimetres, 95):+.2f}cm "
        f"max={heights_centimetres.max():+.2f}cm "
        f"| 浮空>1cm={int((heights_centimetres > 1).sum())} "
        f"陷地<-1cm={int((heights_centimetres < -1).sum())}"
    )


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="[%(name)s] %(message)s", stream=sys.stdout)
    parser = argparse.ArgumentParser()
    parser.add_argument("target", help="run 目录或 .glb")
    parser.add_argument("--out", default=None)
    parser.add_argument("--always-ground", action="store_true", help="每帧都贴地(适合原地动作)")
    parser.add_argument("--report", action="store_true", help="只报数,不写文件")
    arguments = parser.parse_args()

    target = Path(arguments.target)
    glb_path = target if target.suffix.lower() == ".glb" else target / "mixamo_character.glb"
    if not glb_path.exists():
        raise FileNotFoundError(glb_path)
    run_directory = glb_path.parent
    output_path = Path(arguments.out) if arguments.out else glb_path.with_name(f"{glb_path.stem}_grounded.glb")

    clip = SkinnedClip(glb_path)
    lowest_vertex = measure_lowest_vertex_per_frame(clip)
    contact = read_foot_contact(run_directory, clip.n_frames)
    offsets = compute_vertical_offsets(lowest_vertex, contact, arguments.always_ground)

    before = lowest_vertex * 100.0
    after = (lowest_vertex + offsets) * 100.0
    LOGGER.info("帧数=%d 着地帧=%d", clip.n_frames, int((offsets != 0).sum()))
    LOGGER.info("修复前 %s", describe(before))
    LOGGER.info("修复后 %s", describe(after))
    if arguments.report:
        return 0

    gltf_json, binary = read_glb(glb_path)
    hips_index = find_hips_node_index(gltf_json)
    accessor_index = find_hips_translation_accessor(gltf_json, hips_index)
    start, count, component_count, stride = resolve_accessor_layout(gltf_json, accessor_index)
    if component_count != VECTOR_THREE_COMPONENTS or count != clip.n_frames or stride != 12:
        raise ValueError(f"Hips translation 结构不符合预期: {component_count=} {count=} {stride=}")
    raw = np.frombuffer(bytes(binary[start : start + stride * count]), dtype=np.float32).reshape(count, 3).copy()
    raw[:, 1] += offsets.astype(np.float32)
    binary[start : start + stride * count] = raw.astype(np.float32).tobytes()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    write_glb(output_path, gltf_json, bytes(binary))
    LOGGER.info("已写出 %s (%.2f MB)", output_path, output_path.stat().st_size / 1048576)

    verification_clip = SkinnedClip(output_path)
    verified = measure_lowest_vertex_per_frame(verification_clip) * 100.0
    LOGGER.info("复核 %s", describe(verified))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
