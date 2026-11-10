#!/bin/bash
# 采样封装：文本 -> 动作。参数原样传给 unimate.inference.sample。
#   bash pipelines/unimate/scripts/unimate-sample.sh --asset <rig 目录> --prompt "An object walks forward."
# 权重目录默认取 config.env 的 UNIMATE_EXP，可用 EXP_DIR 环境变量覆盖。
source "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")/../../../core/env.sh"
# 相对路径按本工程根解析：UniMate 的 sampler 会在 UNIMATE_HOME 下运行，
# 直接传 "outputs/rig/X_Bot" 会被当成 UniMate 仓库里的路径而报找不到。
ARGS=()
while [ $# -gt 0 ]; do
  case "$1" in
    --asset|--cond_path)
      ARGS+=("$1"); shift
      while [ $# -gt 0 ] && [ "${1:0:1}" != "-" ]; do
        ARGS+=("$(from_project "$1")"); shift
      done
      ;;
    --exp-dir|--exp_dir|--model-path|--model_path|--output_dir|--test_cases_json|--test_cases_txt)
      ARGS+=("$1")
      [ $# -ge 2 ] && { ARGS+=("$(from_project "$2")"); shift 2; } || shift ;;
    *)
      ARGS+=("$1"); shift ;;
  esac
done

cd "$UNIMATE_HOME" || exit 1
exec "$PY" -m unimate.inference.sample --exp_dir "$EXP_DIR" "${ARGS[@]}"