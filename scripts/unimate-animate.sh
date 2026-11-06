#!/bin/bash
# 兼容层：本脚本已迁移，这里只转发到新位置。
echo "[弃用提示] scripts/unimate-animate.sh 已迁移到 pipelines/unimate/scripts/unimate-animate.sh" >&2
exec bash "$(dirname "$(readlink -f "$BASH_SOURCE[0]}")")/../pipelines/unimate/scripts/unimate-animate.sh" "$@"
