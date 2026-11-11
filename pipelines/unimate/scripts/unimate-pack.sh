#!/bin/bash
# 打包两版交付：anim/（循环版）+ full/（完整序列 + 候选帧清单）。
#
# 用法：
#   bash pipelines/unimate/scripts/unimate-pack.sh \
#       --samples outputs/samples/Dog_001 --loop-dir tmp/accept_Dog_001 \
#       --name Dog_001 --out outputs/actions/Dog_001_pack
#
# 参数原样转给 tools/deliver_pack.py；--help 看完整列表。
source "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")/../../../core/env.sh"
exec "$PY" "$UM_TOOLS/deliver_pack.py" "$@"
