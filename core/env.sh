#!/bin/bash
# 所有流水线脚本共用：定位仓库、加载 config.env、准备 Python 和工具路径。
# 用法：source "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")/_env.sh"
set -uo pipefail

PIPELINE_HOME="$(cd "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")/.." && pwd)"
export PIPELINE_HOME

# config.env 不入库；没有就用环境变量（CI 里直接 export）
CONFIG_FILE="${PIPELINE_CONFIG:-$PIPELINE_HOME/config.env}"
if [ -f "$CONFIG_FILE" ]; then
  set -a
  . "$CONFIG_FILE"
  set +a
fi

: "${UNIMATE_HOME:?没有配置 UNIMATE_HOME（复制 config.example.env 为 config.env）}"
export UNIMATE_HOME

UNIMATE_PYTHON="${UNIMATE_PYTHON:-python3}"
PY="$(readlink -f "$UNIMATE_PYTHON")"
export UNIMATE_PYTHON="$PY"

# 目录约定（按能力分目录，见 docs/目录重构说明.md）
#   core/                跨来源共用：配置、动作契约、索引
#   pipelines/unimate/   UniMate 抽卡与库片段接入（脚本 + 工具）
#   Motion2MixamoRig/    动补重定向（独立模块，保持原位）
CORE_HOME="$PIPELINE_HOME/core"
UM_PIPELINE="$PIPELINE_HOME/pipelines/unimate"
UM_SCRIPTS="$UM_PIPELINE/scripts"
UM_TOOLS="$UM_PIPELINE/tools"
# 兼容旧名字：老脚本里的 $TOOLS 指向新位置，不再指向已迁走的 tools/
TOOLS="$UM_TOOLS"
export CORE_HOME UM_PIPELINE UM_SCRIPTS UM_TOOLS TOOLS

# 让 python 工具能 import pipeline_config / rig_joints / unimate_api
export PYTHONPATH="$CORE_HOME:$UM_TOOLS:${PYTHONPATH:-}"

# 把 UniMate 环境的 bin 放到 PATH 前面：bpy 的 blender shim 等都在里面
PYBIN="$(dirname "$PY")"
[ -d "$PYBIN" ] && export PATH="$PYBIN:$PATH"

# UniMate 的 bash 脚本要靠 conda 环境名找到解释器
export CONDA_ENV="${CONDA_ENV:-unimate}"

# xet 下载后端在本机网络下会挂住，走普通 HTTP
export HF_HUB_DISABLE_XET="${HF_HUB_DISABLE_XET:-1}"

# 权重和产物都放在本工程里；相对路径按 PIPELINE_HOME 解析，统一导出成绝对路径，
# 这样后面不管 cd 到哪里都不会错。
from_project() {
  case "$1" in
    /*) printf '%s' "$1" ;;
    *)  printf '%s/%s' "$PIPELINE_HOME" "$1" ;;
  esac
}
# 相对路径依次在 当前目录 / 工程根 / 工程上一级 里找（Arts 这类素材常放在工程外）
abs_path() {
  case "$1" in /*) printf '%s' "$1"; return 0 ;; esac
  for base in "$PWD" "$PIPELINE_HOME" "$PIPELINE_HOME/.."; do
    if [ -e "$base/$1" ]; then readlink -f "$base/$1"; return 0; fi
  done
  readlink -f "$1" 2>/dev/null || printf '%s/%s' "$PWD" "$1"
}

EXP_DIR="$(from_project "${EXP_DIR:-${UNIMATE_EXP:-models/unimate_mixamo_f60_v2}}")"
SAMPLES_HOME="$(from_project "${SAMPLES_HOME:-${UNIMATE_SAMPLES:-outputs/samples}}")"
RIGS_HOME="$(from_project "${RIGS_HOME:-${UNIMATE_RIGS:-outputs/rig}}")"
# 已验收的动作（交付物）：每个动作一个目录，内含 action.json
ACTIONS_HOME="$(from_project "${ACTIONS_HOME:-outputs/actions}")"
export EXP_DIR SAMPLES_HOME RIGS_HOME ACTIONS_HOME