"""本工程对 Motion2MixamoRig 的唯一切入点(库保持只读,不做任何修改)。

作用有两个:
1. 把相机焦距注入 GVHMR —— 上游 m2mr 没有把它透出来,但它是最主要的深度/尺度误差源;
2. 作为统一的命令行入口,后续任何补丁式增强都加在这里,而不是改引用库。

做法是在运行时给 `gvhmr.recover` 套一层,读取环境变量后补上 f_px / f_mm,
再调用 m2mr 自己的命令行。引用库与 site-packages 都不落地任何改动。

三种给"尺度"的方式,优先级从高到低:
    1. --focal-pixels（或 MOTION2MIXAMO_FOCAL_PIXELS）  相机焦距,像素
    2. --distance（或 MOTION2MIXAMO_DISTANCE_METRES）   人到相机的距离,米
       本入口会用 YOLO 量出画面里人的像素身高,按
       焦距 = 像素身高 × 距离 / 真人身高 反推焦距(真人身高默认 1.70m,可用
       --person-height 或 MOTION2MIXAMO_PERSON_HEIGHT_METRES 改)
    3. 都不给 —— 上游按 ~43mm 等效镜头估算(手机主摄会高估深度约 65%)

用法:
    <m2mr venv python> motion2mixamo_command.py run --video x.mp4 --device cuda --distance 3.4
"""
from __future__ import annotations

import logging
import os
import sys
from pathlib import Path
from typing import Any, Callable

TOOLS_ROOT = Path(__file__).resolve().parent
if str(TOOLS_ROOT) not in sys.path:
    sys.path.insert(0, str(TOOLS_ROOT))

import camera_distance as camera  # noqa: E402
import motion2mixamo_config as config  # noqa: E402

LOGGER = logging.getLogger("motion2mixamo")

FOCAL_PIXELS_ENV_NAME = "MOTION2MIXAMO_FOCAL_PIXELS"
FOCAL_MILLIMETRES_ENV_NAME = "MOTION2MIXAMO_FOCAL_MILLIMETRES"

# 同一个视频可能被 recover 调两次(校正 2D 后重跑抬升),推出焦距只算一次
_FOCAL_FROM_DISTANCE_CACHE: dict[str, float] = {}


def _read_focal_override() -> dict[str, float]:
    """读取焦距覆盖参数;像素优先于毫米;都没有就返回空(上游走启发式)。"""
    pixels_text = os.environ.get(FOCAL_PIXELS_ENV_NAME, "").strip()
    millimetres_text = os.environ.get(FOCAL_MILLIMETRES_ENV_NAME, "").strip()
    if pixels_text:
        return {"f_px": float(pixels_text)}
    if millimetres_text:
        return {"f_mm": float(millimetres_text)}
    return {}


def _focal_from_distance(video_path: str) -> dict[str, float]:
    """给了距离就用它反推焦距;量不到人就返回空,让上游走启发式。"""
    distance = config.distance_metres()
    if distance is None:
        return {}
    cached = _FOCAL_FROM_DISTANCE_CACHE.get(video_path)
    if cached is not None:
        return {"f_px": cached}
    weights = config.motion2mixamo_home() / "weights" / "yolo" / "yolov8x.pt"
    focal = camera.focal_pixels_from_distance_for_video(
        Path(video_path), distance, config.person_height_metres(), weights=weights)
    if focal is None:
        LOGGER.warning("给了距离 %.2fm 但没在画面里量到人,退回启发式焦距", distance)
        return {}
    _FOCAL_FROM_DISTANCE_CACHE[video_path] = focal
    LOGGER.info("由距离推出焦距 %.0f px（距离 %.2fm / 身高 %.2fm）",
                focal, distance, config.person_height_metres())
    return {"f_px": focal}


def _report_focal_state(video_path: str) -> None:
    """没有焦距时要说出来 —— 否则用户不知道世界尺度是按 43mm 估的。"""
    LOGGER.warning(
        "未提供相机焦距或距离:世界位移会按 ~43mm 等效镜头估算(手机主摄约高估 65%%)。"
        "可用 --focal-pixels / --distance,或写进 Motion2MixamoRig/config.env。")


def install_focal_injection() -> None:
    """给 gvhmr.recover 套一层,把焦距补进去。重复调用是幂等的。

    顺序很关键:gvhmr 在 import 时就把权重与体模的根目录固定下来,所以必须先让
    m2mr 的 paths 把 GVHMR_BODY_MODELS / GVHMR_CHECKPOINTS 导出,再 import gvhmr。
    否则会在 site-packages 下找 SMPL-X,报 "body model not found"。
    """
    from motion2mixamorig import paths

    paths.export_gvhmr_env()
    import gvhmr

    original_recover: Callable[..., Any] = gvhmr.recover
    if getattr(original_recover, "_motion2mixamo_focal_wrapped", False):
        return

    def recover_with_focal(video: str, **kwargs: Any) -> Any:
        override = _read_focal_override() or _focal_from_distance(str(video))
        if override:
            LOGGER.info("注入相机焦距 %s", override)
            for key, value in override.items():
                kwargs.setdefault(key, value)
        else:
            _report_focal_state(str(video))
        return original_recover(video, **kwargs)

    recover_with_focal._motion2mixamo_focal_wrapped = True  # type: ignore[attr-defined]
    gvhmr.recover = recover_with_focal


SCALE_ARGUMENTS = {
    "--distance": "MOTION2MIXAMO_DISTANCE_METRES",
    "--person-height": "MOTION2MIXAMO_PERSON_HEIGHT_METRES",
    "--focal-pixels": FOCAL_PIXELS_ENV_NAME,
}


def consume_scale_arguments(arguments: list[str]) -> list[str]:
    """摘掉本入口自己的尺度参数(写进环境变量),其余原样交给 m2mr 命令行。

    m2mr 的 CLI 不认识 --distance 这类参数,所以必须在委派之前摘掉。
    """
    remaining: list[str] = []
    index = 0
    while index < len(arguments):
        token = arguments[index]
        consumed = False
        for flag, env_name in SCALE_ARGUMENTS.items():
            if token == flag and index + 1 < len(arguments):
                os.environ[env_name] = arguments[index + 1]
                index += 2
                consumed = True
                break
            if token.startswith(flag + "="):
                os.environ[env_name] = token.split("=", 1)[1]
                index += 1
                consumed = True
                break
        if not consumed:
            remaining.append(token)
            index += 1
    return remaining


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="[%(name)s] %(message)s", stream=sys.stdout)
    sys.argv = [sys.argv[0]] + consume_scale_arguments(sys.argv[1:])
    install_focal_injection()
    from motion2mixamorig.cli import main as m2mr_main

    return int(m2mr_main() or 0)


if __name__ == "__main__":
    raise SystemExit(main())
