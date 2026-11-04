#!/bin/bash
# 批量接入动作库片段：把一个目录里的 FBX/GLB 逐个跑产线 B。
#
# 用法：
#   bash scripts/unimate-import-batch.sh \
#       --clips Arts/mixamo_rolls \
#       --rig outputs/rig/X_Bot --name X_Bot \
#       --expect roll --prefix act_
#
#   --clips <dir>     片段目录（.fbx/.glb）
#   --rig <dir>       rig_preprocess 产物目录
#   --name <str>      角色名
#   --out-root <dir>  每个动作一个子目录，默认 outputs/samples
#   --expect motion|roll
#   --prefix lib_|act_  动作名前缀，默认 act_
#   --mode mixamo|drop|keep，默认 mixamo
#   --dry-run
source "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")/_env.sh"

CLIPS=""; RIG=""; NAME=""; OUT_ROOT=""; EXPECT="auto"; PREFIX="act_"; MODE="mixamo"; DRY=0

need_val() { [ $# -ge 2 ] || { echo "参数 $1 需要一个值" >&2; exit 2; }; }
while [ $# -gt 0 ]; do
  case "$1" in
    --clips)    need_val "$@"; CLIPS="$2"; shift 2 ;;
    --rig)      need_val "$@"; RIG="$2"; shift 2 ;;
    --name)     need_val "$@"; NAME="$2"; shift 2 ;;
    --out-root) need_val "$@"; OUT_ROOT="$2"; shift 2 ;;
    --expect)   need_val "$@"; EXPECT="$2"; shift 2 ;;
    --prefix)   need_val "$@"; PREFIX="$2"; shift 2 ;;
    --mode)     need_val "$@"; MODE="$2"; shift 2 ;;
    --dry-run)  DRY=1; shift ;;
    -h|--help)  sed -n '2,20p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) echo "未知参数：$1" >&2; exit 2 ;;
  esac
done

[ -n "$CLIPS" ] || { echo "缺少 --clips" >&2; exit 2; }
[ -n "$RIG" ] || { echo "缺少 --rig" >&2; exit 2; }
CLIPS="$(abs_path "$CLIPS")"
RIG="$(abs_path "$RIG")"
[ -d "$CLIPS" ] || { echo "不是目录：$CLIPS" >&2; exit 2; }
[ -n "$NAME" ] || NAME="$(basename "$RIG")"
[ -n "$OUT_ROOT" ] || OUT_ROOT="$ACTIONS_HOME"

mapfile -t FILES < <(find "$CLIPS" -maxdepth 1 -type f \( -iname "*.fbx" -o -iname "*.glb" \) | sort)
[ ${#FILES[@]} -gt 0 ] || { echo "$CLIPS 里没有 fbx/glb" >&2; exit 2; }

echo "============================================================"
echo "片段目录: $CLIPS（${#FILES[@]} 个）"
echo "角色    : $NAME（$RIG）"
echo "闸门    : $EXPECT（auto=按名字判断）  前缀: $PREFIX"
echo "============================================================"

# --dry-run 用数组传，避免 ${DRY:+...} 对 "0" 也展开
DRYARG=()
[ "$DRY" = 1 ] && DRYARG+=(--dry-run)

ok=0; fail=0; FAILED=()
for f in "${FILES[@]}"; do
  stem="$(basename "${f%.*}")"
  slug="$(printf '%s' "$stem" | tr -c 'A-Za-z0-9' '_' | sed 's/__*/_/g; s/^_//; s/_$//' | tr 'A-Z' 'a-z')"
  action="${PREFIX}${slug}"
  out="$OUT_ROOT/${action}"
  # auto：名字里有翻滚/翻转词的走 roll 闸门，其余只要四肢在动
  exp="$EXPECT"
  if [ "$EXPECT" = "auto" ]; then
    case "$slug" in
      *roll*|*flip*|*cartwheel*|*somersault*|*tumble*) exp="roll" ;;
      *) exp="motion" ;;
    esac
  fi
  echo
  echo "---- $(basename "$f") -> $action ----"
  if bash "$PIPELINE_HOME/scripts/unimate-import-clip.sh" \
        --clip "$f" --rig "$RIG" --name "$NAME" \
        --out "$out" --expect "$exp" --action "$action" --mode "$MODE" \
        "${DRYARG[@]}" > "$PIPELINE_HOME/tmp/import_batch_$slug.log" 2>&1; then
    ok=$((ok+1))
    tail -3 "$PIPELINE_HOME/tmp/import_batch_$slug.log" | sed 's/^/    /'
  else
    fail=$((fail+1))
    FAILED+=("$(basename "$f")")
    echo "    失败（看 tmp/import_batch_$slug.log）"
    grep -E "判定|不通过|失败|Error" "$PIPELINE_HOME/tmp/import_batch_$slug.log" | tail -3 | sed 's/^/    /'
  fi
done

echo
echo "============================================================"
echo "成功 ${ok} 个，失败 ${fail} 个"
[ "$fail" = 0 ] || { echo "失败清单：${FAILED[*]}"; exit 1; }
echo "索引：PYTHONPATH=tools python tools/action_index.py"