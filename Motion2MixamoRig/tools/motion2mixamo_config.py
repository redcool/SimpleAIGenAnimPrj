"""动补产线的配置:路径与可执行文件都从这里取,代码里不写死机器路径。

解析顺序(先命中先用):
    1. 环境变量(临时覆盖,便于 CI / 一次性的不同机器)
    2. Motion2MixamoRig/config.env(本机配置,不入库;模板是 config.example.env)
    3. 从当前工作目录逐级向上查找,认「含 motion2mixamorig/ 的目录」为引用库根
    4. 都找不到就明确报错,并打印该怎么配 —— 不静默回落到假路径

约定:
    引用库(Motion2MixamoRig)只读;本模块只读它的包与 assets,不写它。
    产物落本工程 outputs/video_cap;临时文件落 Motion2MixamoRig/tmp。
"""
from __future__ import annotations

import logging
import os
import pathlib
import sys

LOGGER = logging.getLogger("motion2mixamo.config")

# Motion2MixamoRig/ —— 本模块所在目录的上一级
MODULE_ROOT = pathlib.Path(__file__).resolve().parent.parent
# AIGenAnimPrj/ —— 主工程根
PROJECT_ROOT = MODULE_ROOT.parent

REFERENCE_PACKAGE_NAME = "motion2mixamorig"


def _load_config_file() -> None:
    """把 config.env 读进环境变量;已存在的环境变量优先,不被文件覆盖。"""
    path = MODULE_ROOT / "config.env"
    if not path.is_file():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


_load_config_file()


def _looks_like_repository(path: pathlib.Path) -> bool:
    """引用库的判定:同时有包目录和 assets 目录。"""
    return (path / REFERENCE_PACKAGE_NAME / "__init__.py").is_file()


def _find_repository_from_working_directory() -> pathlib.Path | None:
    """从当前工作目录向上找引用库根。"""
    for candidate in [pathlib.Path.cwd(), *pathlib.Path.cwd().parents]:
        if _looks_like_repository(candidate):
            return candidate
    return None


def motion2mixamo_home() -> pathlib.Path:
    """引用库根目录(Motion2MixamoRig)。"""
    configured = os.environ.get("MOTION2MIXAMO_HOME", "").strip()
    if configured:
        home = pathlib.Path(configured).expanduser()
        if not home.is_absolute():
            home = (pathlib.Path.cwd() / home).resolve()
        if not _looks_like_repository(home):
            raise SystemExit(
                "MOTION2MIXAMO_HOME 指向的目录不是引用库(缺 %s/):%s" % (REFERENCE_PACKAGE_NAME, home))
        return home

    found = _find_repository_from_working_directory()
    if found is not None:
        return found

    raise SystemExit(
        "找不到引用库 Motion2MixamoRig。三种修法任选其一:\n"
        "  1. 在 Motion2MixamoRig/config.env 里写 MOTION2MIXAMO_HOME=<绝对路径>\n"
        "  2. 设置环境变量 MOTION2MIXAMO_HOME=<绝对路径>\n"
        "  3. 把当前工作目录切到引用库根目录(或其子目录)后再运行")


def ensure_reference_package_importable() -> pathlib.Path:
    """把引用库放进 sys.path,返回它的根目录。重复调用是幂等的。"""
    home = motion2mixamo_home()
    if str(home) not in sys.path:
        sys.path.insert(0, str(home))
    return home


def _configurable_path(key: str, default_under_home: str) -> pathlib.Path:
    """读一个以引用库根为基准的可配置路径。"""
    value = os.environ.get(key, "").strip() or default_under_home
    candidate = pathlib.Path(value).expanduser()
    return candidate if candidate.is_absolute() else (motion2mixamo_home() / candidate)


def venv_python() -> str:
    """跑引用库的 Python 解释器(装有 torch / gvhmr 的那个环境)。"""
    configured = os.environ.get("MOTION2MIXAMO_PYTHON", "").strip()
    if configured:
        return configured
    home = motion2mixamo_home()
    for relative in ("\.venv\Scripts\python.exe", ".venv/bin/python"):
        candidate = home / relative
        if candidate.is_file():
            return str(candidate)
    return sys.executable


def resolve_reference_python() -> str:
    """拿到并校验跑引用库的解释器;不存在就明确报错,不猜。"""
    python = venv_python()
    path = pathlib.Path(python)
    if not path.is_file():
        raise SystemExit(
            "跑引用库的 Python 不存在:%s\n"
            "请在 Motion2MixamoRig/config.env 里把 MOTION2MIXAMO_PYTHON 指向正确的解释器\n"
            "(通常是 <MOTION2MIXAMO_HOME>/.venv/Scripts/python.exe)" % python)
    return python


def assets_video() -> pathlib.Path:
    """素材视频目录(只读输入)。"""
    return _configurable_path("MOTION2MIXAMO_ASSETS_VIDEO", "assets/video")


def default_rig() -> pathlib.Path:
    """默认角色 FBX。"""
    return _configurable_path("MOTION2MIXAMO_DEFAULT_RIG", "assets/mixamo/X_Bot.fbx")


def video_cap_output_root() -> pathlib.Path:
    """视频动补交付根目录;默认落在主工程 outputs/video_cap。"""
    configured = os.environ.get("MOTION2MIXAMO_OUTPUT_ROOT", "").strip()
    if configured:
        candidate = pathlib.Path(configured).expanduser()
        return candidate if candidate.is_absolute() else (PROJECT_ROOT / candidate)
    return PROJECT_ROOT / "outputs" / "video_cap"


def module_tmp() -> pathlib.Path:
    """本模块临时目录(日志、脚本、试验产物)。"""
    path = MODULE_ROOT / "tmp"
    path.mkdir(parents=True, exist_ok=True)
    return path


def blender_executable() -> str:
    """Blender 可执行文件。"""
    return os.environ.get("BLENDER_EXECUTABLE", "").strip() or "blender"


def default_focal_pixels() -> float | None:
    """默认相机焦距(像素);没配就返回 None,由上游走启发式。"""
    text = os.environ.get("MOTION2MIXAMO_FOCAL_PIXELS", "").strip()
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        LOGGER.warning("MOTION2MIXAMO_FOCAL_PIXELS 不是数字(%s),忽略", text)
        return None


def distance_metres() -> float | None:
    """人到相机的距离(米)。设了就由它反推焦距,优先于启发式。"""
    text = os.environ.get("MOTION2MIXAMO_DISTANCE_METRES", "").strip()
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        LOGGER.warning("MOTION2MIXAMO_DISTANCE_METRES 不是数字(%s),忽略", text)
        return None


def person_height_metres() -> float:
    """画面里那个人的真实身高(米),默认 1.70。用于把距离换算成焦距。"""
    text = os.environ.get("MOTION2MIXAMO_PERSON_HEIGHT_METRES", "").strip() or "1.70"
    try:
        return float(text)
    except ValueError:
        LOGGER.warning("MOTION2MIXAMO_PERSON_HEIGHT_METRES 不是数字(%s),用 1.70", text)
        return 1.70


def describe() -> dict[str, str]:
    """把当前解析结果整理成一行键值,便于启动时自检。"""
    return {
        "reference_repository": str(motion2mixamo_home()),
        "python": venv_python(),
        "assets_video": str(assets_video()),
        "default_rig": str(default_rig()),
        "output_root": str(video_cap_output_root()),
        "blender": blender_executable(),
        "focal_pixels": str(default_focal_pixels()),
        "distance_metres": str(distance_metres()),
        "person_height_metres": str(person_height_metres()),
    }


def main() -> int:
    """命令行自检:打印当前解析结果,便于排查"为什么找错目录"。"""
    import json

    logging.basicConfig(level=logging.INFO, format="[%(name)s] %(message)s")
    print(json.dumps(describe(), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
