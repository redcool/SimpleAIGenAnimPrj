"""兼容层：本文件已迁移，这里只转发到新位置。"""
import os
import runpy
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# 先让 core/ 在搜索路径最前，避免转发时又 import 回这个兼容层
sys.path.insert(0, os.path.join(_ROOT, "core"))
sys.path.insert(0, os.path.join(_ROOT, "pipelines", "unimate", "tools"))
_NEW = {
    "pipeline_config": "core/pipeline_config.py",
    "action_meta": "core/action_meta.py",
    "action_index": "core/action_index.py",
}.get("rig_joints", "pipelines/unimate/tools/rig_joints.py")
path = os.path.join(_ROOT, _NEW)
print("[弃用提示] tools/rig_joints.py 已迁移到 %s" % _NEW, file=sys.stderr)
sys.argv[0] = path
runpy.run_path(path, run_name="__main__")
