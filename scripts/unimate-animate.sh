#!/bin/bash
# 动画导出封装：动作 -> 带动画的 GLB/FBX。
#   bash scripts/unimate-animate.sh <采样目录> [输出目录]
source "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")/_env.sh"

# 路径先转绝对：UniMate 的脚本在 UNIMATE_HOME 下按相对路径找 <dir>/manifest.json，
# 传相对路径会被当成 DATASET_TYPE 而报错。
SAMPLES="$(abs_path "${1:?用法: unimate-animate.sh <采样目录> [输出目录]}")"
OUT="${2:-}"
[ -n "$OUT" ] && OUT="$(abs_path "$OUT")"

cd "$UNIMATE_HOME" || exit 1
if [ -n "$OUT" ]; then
  exec bash scripts/run_animate_motion.sh "$SAMPLES" "$OUT"
else
  exec bash scripts/run_animate_motion.sh "$SAMPLES"
fi
