#!/bin/bash
# 兼容层：环境脚本已迁移到 core/env.sh
echo "[弃用提示] scripts/_env.sh 已迁移到 core/env.sh" >&2
source "$(dirname "$(readlink -f "$BASH_SOURCE[0]}")")/../core/env.sh"
