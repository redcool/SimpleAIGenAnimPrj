"""本工程对 Motion2MixamoRig 的唯一切入点(库保持只读,不做任何修改)。

作用有两个:
1. 把相机焦距注入 GVHMR —— 上游 m2mr 没有把它透出来,但它是最主要的深度/尺度误差源;
2. 作为统一的命令行入口,后续任何补丁式增强都加在这里,而不是改引用库。

做法是在运行时给 `gvhmr.recover` 套一层,读取环境变量后补上 f_px / f_mm,
再调用 m2mr 自己的命令行。引用库与 site-packages 都不落地任何改动。

环境变量:
    MOTION2MIXAMO_FOCAL_PIXELS       相机焦距(像素),优先级最高
    MOTION2MIXAMO_FOCAL_MILLIMETRES  相机等效焦距(mm),由上游换算成像素
用法:
    <m2mr venv python> motion2mixamo_command.py run --video x.mp4 --device cuda
"""
from __future__ import annotations

import logging
import os
import sys
from typing import Any, Callable

LOGGER = logging.getLogger("motion2mixamo")

FOCAL_PIXELS_ENV_NAME = "MOTION2MIXAMO_FOCAL_PIXELS"
FOCAL_MILLIMETRES_ENV_NAME = "MOTION2MIXAMO_FOCAL_MILLIMETRES"


def _read_focal_override() -> dict[str, float]:
    """读取焦距覆盖参数;像素优先于毫米;都没有就返回空(上游走启发式)。"""
    pixels_text = os.environ.get(FOCAL_PIXELS_ENV_NAME, "").strip()
    millimetres_text = os.environ.get(FOCAL_MILLIMETRES_ENV_NAME, "").strip()
    if pixels_text:
        return {"f_px": float(pixels_text)}
    if millimetres_text:
        return {"f_mm": float(millimetres_text)}
    return {}


def _report_focal_state() -> None:
    """没有焦距时要说出来 —— 否则用户不知道世界尺度是按 43mm 估的。"""
    if _read_focal_override():
        return
    LOGGER.warning(
        "未提供相机焦距:世界位移会按 ~43mm 等效镜头估算(手机主摄约高估 65%%)。"
        "可用 --focal-pixels / MOTION2MIXAMO_FOCAL_PIXELS 或在 config.env 里配置。")


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
        override = _read_focal_override()
        if override:
            LOGGER.info("注入相机焦距 %s", override)
            for key, value in override.items():
                kwargs.setdefault(key, value)
        else:
            _report_focal_state()
        return original_recover(video, **kwargs)

    recover_with_focal._motion2mixamo_focal_wrapped = True  # type: ignore[attr-defined]
    gvhmr.recover = recover_with_focal


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="[%(name)s] %(message)s", stream=sys.stdout)
    install_focal_injection()
    from motion2mixamorig.cli import main as m2mr_main

    return int(m2mr_main() or 0)


if __name__ == "__main__":
    raise SystemExit(main())
