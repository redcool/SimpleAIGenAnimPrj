"""把两个以上机位的 skeleton_motion.npz 融合成一份动作。

上游 m2mr 只做单目。双机位的第一步不是"各跑一遍再叠加",而是先分开拟合:
  * 姿态:去掉根位移后做 Procrustes(可选整体缩放);
  * 根轨迹:单独做刚体拟合(平移 + 旋转),因为它承载的是深度/焦距误差。
两者分开后,报告就能告诉你误差到底出在哪一类 —— 这是判断"要不要上多视
角三角化"的最便宜依据。

用法:
    python fuse_camera_views.py 输出.npz 机位1.npz 机位2.npz [--scale] [--smooth 3] [--no-root]
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

import numpy as np

LOGGER = logging.getLogger("motion2mixamo.fuse")

MOTION2MIXAMO_ROOT = Path(r"H:\aiworks\motionPrj\Motion2MixamoRig")
if str(MOTION2MIXAMO_ROOT) not in sys.path:
    sys.path.insert(0, str(MOTION2MIXAMO_ROOT))

from motion2mixamorig.extractors.base import SMPL_JOINT_NAMES  # noqa: E402  (只读引用)


def load_skeleton(path: Path) -> dict:
    with np.load(path, allow_pickle=True) as payload:
        return {key: payload[key] for key in payload.files}


def root_relative(joints: np.ndarray) -> np.ndarray:
    """把每帧的根关节移到原点,只保留相对姿态。"""
    return joints - joints[:, :1, :]


def fit_rotation_and_scale(source: np.ndarray, target: np.ndarray, allow_scale: bool) -> tuple[np.ndarray, float]:
    """最小二乘求把 source 转到 target 的旋转(可选均匀缩放),忽略质心。"""
    source_flat = source.reshape(-1, 3)
    target_flat = target.reshape(-1, 3)
    source_centred = source_flat - source_flat.mean(axis=0)
    target_centred = target_flat - target_flat.mean(axis=0)
    left, singular_values, right_transposed = np.linalg.svd(source_centred.T @ target_centred)
    correction = np.sign(np.linalg.det(right_transposed.T @ left.T))
    rotation = right_transposed.T @ np.diag([1.0, 1.0, correction]) @ left.T
    scale = 1.0
    if allow_scale:
        denominator = float((source_centred ** 2).sum())
        if denominator > 0:
            scale = float((singular_values * np.array([1.0, 1.0, correction])).sum() / denominator)
    return rotation, scale


def jerk_centimetres(points: np.ndarray) -> float:
    """三阶差分的平均幅值,用来衡量抖动;单位 cm。"""
    if len(points) < 4:
        return 0.0
    third_difference = points[3:] - 3 * points[2:-1] + 3 * points[1:-2] - points[:-3]
    return float(np.linalg.norm(third_difference, axis=-1).mean() * 100.0)


def smooth_trajectory(joints: np.ndarray, window: int) -> np.ndarray:
    """沿时间做滑动平均;window<=1 时原样返回。"""
    if window <= 1:
        return joints
    smoothed = joints.copy()
    kernel = np.ones(window) / window
    padding = window // 2
    for joint_index in range(joints.shape[1]):
        for axis_index in range(3):
            column = np.pad(smoothed[:, joint_index, axis_index], padding, mode="edge")
            smoothed[:, joint_index, axis_index] = np.convolve(column, kernel, mode="valid")[: len(smoothed)]
    return smoothed


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="[%(name)s] %(message)s", stream=sys.stdout)
    parser = argparse.ArgumentParser()
    parser.add_argument("output")
    parser.add_argument("inputs", nargs="+")
    parser.add_argument("--scale", action="store_true", help="为每个附加机位求一个整体缩放")
    parser.add_argument("--smooth", type=int, default=0, help="融合后的滑动平均窗口")
    parser.add_argument("--no-root", action="store_true", help="忽略根位移,只融合姿态")
    arguments = parser.parse_args()

    clips = [load_skeleton(Path(item)) for item in arguments.inputs]
    joint_names = [str(name) for name in clips[0]["joint_names"]]
    if list(joint_names) != list(SMPL_JOINT_NAMES):
        raise ValueError(f"关节顺序不是 24 关节 SMPL: {joint_names[:3]}")

    lengths = [len(clip["joints_3d"]) for clip in clips]
    frame_count = min(lengths)
    if len(set(lengths)) != 1:
        LOGGER.warning("各机位帧数不同 %s,截断到 %d", lengths, frame_count)

    base = np.asarray(clips[0]["joints_3d"][:frame_count], dtype=np.float64)
    base_relative = root_relative(base)
    base_root = base[:, 0, :].copy()

    relative_list = [base_relative]
    root_list = [base_root]
    report: dict = {"frames": frame_count, "inputs": [{"file": arguments.inputs[0], "role": "base"}]}

    for index, clip in enumerate(clips[1:], start=1):
        joints = np.asarray(clip["joints_3d"][:frame_count], dtype=np.float64)
        relative = root_relative(joints)
        rotation, scale = fit_rotation_and_scale(relative, base_relative, arguments.scale)
        aligned_relative = scale * (relative.reshape(-1, 3) @ rotation.T).reshape(relative.shape)

        root = joints[:, 0, :]
        aligned_root = scale * (root @ rotation.T)
        aligned_root = aligned_root + (base_root.mean(axis=0) - aligned_root.mean(axis=0))
        if arguments.no_root:
            aligned_root = base_root.copy()

        pose_error = np.linalg.norm(aligned_relative - base_relative, axis=-1)
        root_error = np.linalg.norm(aligned_root - base_root, axis=-1)
        per_joint = pose_error.mean(axis=0)
        relative_list.append(aligned_relative)
        root_list.append(aligned_root)
        report["inputs"].append({
            "file": arguments.inputs[index],
            "scale": round(scale, 4),
            "pose_rms_cm": round(float(np.sqrt((pose_error ** 2).mean()) * 100.0), 2),
            "pose_max_joint_cm": round(float(per_joint.max() * 100.0), 2),
            "worst_joints": [joint_names[i] for i in np.argsort(-per_joint)[:4]],
            "root_rms_cm": round(float(np.sqrt((root_error ** 2).mean()) * 100.0), 2),
            "root_travel_cm": round(float(np.linalg.norm(aligned_root.max(0) - aligned_root.min(0)) * 100.0), 1),
        })

    fused_relative = np.mean(np.stack(relative_list, axis=0), axis=0)
    fused_root = base_root if arguments.no_root else np.mean(np.stack(root_list, axis=0), axis=0)
    fused = smooth_trajectory(fused_relative + fused_root[:, None, :], arguments.smooth)

    output_path = Path(arguments.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    payload = dict(clips[0])
    payload["joints_3d"] = fused.astype(np.float32)
    payload["extractor"] = np.array(f"fused:{len(clips)}")
    payload["root_translation"] = fused_root.astype(np.float32)
    if "foot_contact" in payload and len(payload["foot_contact"]) != frame_count:
        payload.pop("foot_contact", None)
    if "timestamps" in payload and len(payload["timestamps"]) != frame_count:
        frames_per_second = float(np.asarray(clips[0]["fps"]).reshape(-1)[0])
        payload["timestamps"] = np.arange(frame_count, dtype=np.float64) / frames_per_second
    np.savez_compressed(output_path, **payload)

    report["base_jerk_cm"] = round(jerk_centimetres(base), 3)
    report["fused_jerk_cm"] = round(jerk_centimetres(fused), 3)
    report["base_root_travel_cm"] = round(float(np.linalg.norm(base_root.max(0) - base_root.min(0)) * 100.0), 1)
    LOGGER.info("融合报告\n%s", json.dumps(report, indent=2, ensure_ascii=False))
    LOGGER.info("已写出 %s", output_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
