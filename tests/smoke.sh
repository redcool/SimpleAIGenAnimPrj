#!/bin/bash
# 冒烟测试入口：找对解释器，跑 smoke.py，把退出码透出去。
#   bash tests/smoke.sh
set -uo pipefail
HERE="$(cd "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")" && pwd)"
ROOT="$(dirname "$HERE")"

# 优先用 config.env 里配的解释器（bpy/torch 都在那个环境）
PY="${UNIMATE_PYTHON:-}"
if [ -z "$PY" ] && [ -f "$ROOT/config.env" ]; then
  PY="$(grep -E "^UNIMATE_PYTHON=" "$ROOT/config.env" | head -1 | cut -d= -f2-)"
fi
[ -n "$PY" ] || PY=python3

export PYTHONPATH="$ROOT/core:$ROOT/pipelines/unimate/tools:${PYTHONPATH:-}"
exec "$PY" "$HERE/smoke.py" "$@"