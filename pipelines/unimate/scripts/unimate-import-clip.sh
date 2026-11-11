#!/bin/bash
# 把动作库里的片段（Mixamo 等）接到自己的角色上 —— 不经过 UniMate 采样。
#
# 适用：模型做不出的动作（翻滚、攀爬…），但动作库里有现成的；
#       且片段与角色是同一套骨架（比如都是 Mixamo 22/65 关节）。
#
# 流程：精简到目标关节数 -> 转成 UniMate 特征 -> 关节顺序对齐 -> 驱动角色导出
#
# 用法：
#   bash pipelines/unimate/scripts/unimate-import-clip.sh \
#       --clip "Arts/Sprinting Forward Roll.fbx" \
#       --rig outputs/rig/X_Bot --name X_Bot --out outputs/samples/roll_on_xbot
#
#   --clip   动作片段（FBX/GLB，可以无蒙皮，只要有骨骼动画）
#   --rig    rig_preprocess 产物目录（含 cond.npy 和 <name>.glb）
#   --name   角色名（= rig 目录名 = cond 的 key）
#   --out    输出目录，默认 outputs/samples/<name>_clip
#   --mode   simplify 的模式：mixamo（默认）| drop | keep
#   --drop   配合 --mode drop 的正则
#   --keep   配合 --mode keep 的正则
#   --expect motion|roll  质量闸门：motion=四肢得在动（默认），roll=必须整圈翻
#   --action <名字>       动作名，默认由片段名推出
#   --loopable            标记为可循环动作（写进 action.json）
#   --dry-run             只打印命令
source "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")/../../../core/env.sh"

CLIP=""; RIG=""; NAME=""; OUT=""; MODE="mixamo"; DROPS=(); KEEPS=(); DRY=0
EXPECT="motion"; ACTION=""; LOOPABLE=0

need_val() { [ $# -ge 2 ] || { echo "参数 $1 需要一个值" >&2; exit 2; }; }
while [ $# -gt 0 ]; do
  case "$1" in
    --clip)   need_val "$@"; CLIP="$2"; shift 2 ;;
    --rig)    need_val "$@"; RIG="$2"; shift 2 ;;
    --name)   need_val "$@"; NAME="$2"; shift 2 ;;
    --out)    need_val "$@"; OUT="$2"; shift 2 ;;
    --mode)   need_val "$@"; MODE="$2"; shift 2 ;;
    --expect) need_val "$@"; EXPECT="$2"; shift 2 ;;
    --action) need_val "$@"; ACTION="$2"; shift 2 ;;
    --loopable) LOOPABLE=1; shift ;;
    --drop)   need_val "$@"; DROPS+=("$2"); shift 2 ;;
    --keep)   need_val "$@"; KEEPS+=("$2"); shift 2 ;;
    --dry-run) DRY=1; shift ;;
    -h|--help) sed -n '2,22p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) echo "未知参数：$1" >&2; exit 2 ;;
  esac
done

[ -n "$CLIP" ] || { echo "缺少 --clip" >&2; exit 2; }
[ -n "$RIG" ] || { echo "缺少 --rig" >&2; exit 2; }
CLIP="$(abs_path "$CLIP")"
RIG="$(abs_path "$RIG")"
[ -f "$CLIP" ] || { echo "找不到片段：$CLIP" >&2; exit 2; }
[ -f "$RIG/cond.npy" ] || { echo "$RIG 里没有 cond.npy（先跑 rig_preprocess）" >&2; exit 2; }

clip_stem="$(basename "${CLIP%.*}")"
clip_key="$(printf '%s' "$clip_stem" | tr -c 'A-Za-z0-9_-' '_' | sed 's/__*/_/g; s/^_//; s/_$//')"
[ -n "$NAME" ] || NAME="$(basename "$RIG")"
[ -n "$ACTION" ] || ACTION="lib_$clip_key"
# 默认落到 outputs/actions/<动作名>：这是"已验收动作"的标准位置
[ -n "$OUT" ] || OUT="$ACTIONS_HOME/$ACTION"
case "$OUT" in /*) ;; *) OUT="$(from_project "$OUT")" ;; esac

WORK="$PIPELINE_HOME/outputs/rig/.clip_$clip_key"
mkdir -p "$WORK" "$OUT/motions"

run() { if [ "$DRY" = 1 ]; then echo "  [dry-run] $*"; return 0; fi; echo "  \$ $*"; "$@"; }

echo "============================================================"
echo "片段    : $CLIP"
echo "角色    : $NAME（$RIG）"
echo "输出    : $OUT"
echo "============================================================"

echo
echo "== [1/4] 精简片段骨架到 --mode $MODE =="
# 精简结果放进工作目录并用固定名，避免每次都往素材目录里堆 _v2/_v3
SIM=("$TOOLS/simplify_rig.py" --input "$CLIP" --mode "$MODE" --format glb \
     --output "$WORK/simplified.glb" --force)
for d in "${DROPS[@]:-}"; do [ -n "$d" ] && SIM+=(--drop "$d"); done
for k in "${KEEPS[@]:-}"; do [ -n "$k" ] && SIM+=(--keep "$k"); done
if [ "$DRY" = 1 ]; then echo "  [dry-run] $PY ${SIM[*]}"; SIM_OUT="$CLIP"; else
  SIM_OUT=$("$PY" "${SIM[@]}" 2>/dev/null | awk '/已写出/{print $NF}' | tail -1)
  [ -n "$SIM_OUT" ] || { echo "精简失败" >&2; exit 1; }
  echo "  -> $SIM_OUT"
fi

echo
echo "== [2/4] 转成 UniMate 特征（rig_preprocess --save_clips） =="
if [ "$DRY" = 1 ]; then
  echo "  [dry-run] (cd $UNIMATE_HOME && $PY -m data_process.rig_preprocess run --input $SIM_OUT --output_dir $WORK --name $clip_key --annotate rule --no_review --save_clips)"
else
  ( cd "$UNIMATE_HOME" && "$PY" -m data_process.rig_preprocess run \
      --input "$SIM_OUT" --output_dir "$WORK" --name "$clip_key" \
      --annotate rule --no_review --save_clips --overwrite ) > "$PIPELINE_HOME/tmp/import_clip.log" 2>&1 \
    || { echo "rig_preprocess 失败，看 tmp/import_clip.log" >&2; tail -5 "$PIPELINE_HOME/tmp/import_clip.log" >&2; exit 1; }
fi
NPZ=$(ls "$WORK/motions/"*.npz 2>/dev/null | head -1)
[ "$DRY" = 1 ] || [ -n "$NPZ" ] || { echo "没有产出 npz" >&2; exit 1; }

echo
echo "== [3/4] 关节顺序对齐到角色 =="
run "$PY" "$TOOLS/remap_motion_joints.py" --input "$NPZ" \
    --from-cond "$WORK/cond.npy" --to-cond "$RIG/cond.npy" \
    --out-dir "$OUT/motions" --name "${NAME}-${clip_key}.npz"

echo
echo "== [4/4] 驱动角色导出 GLB / FBX =="
if [ "$DRY" = 1 ]; then
  echo "  [dry-run] ANIM_PATH=... CHAR_PATH=$RIG/$NAME.glb COND_PATH=$RIG/cond.npy OUTPUT_DIR=$OUT bash data_process/scripts/run_animate_motion.sh general"
else
  ( cd "$UNIMATE_HOME" && \
    ANIM_PATH="$OUT/motions/${NAME}-${clip_key}.npz" \
    CHAR_PATH="$RIG/${NAME}.glb" \
    COND_PATH="$RIG/cond.npy" \
    OUTPUT_DIR="$OUT" \
    ASSET=export CANONICAL= EXTRA_BONES_STRATEGY=merge \
    bash data_process/scripts/run_animate_motion.sh general ) 2>&1 \
    | grep -vE "User property type|^FBX version|INFO|WARNING|Data are|glTF|export finished|Not freed|FBX export|bpy.data" | tail -4
fi

echo
echo "== [5/5] 质量闸门 + 动作元数据 =="
QA_JSON="$OUT/qa.json"
if [ "$DRY" = 1 ]; then
  echo "  [dry-run] $PY $TOOLS/verify_anim.py --input $OUT --expect $EXPECT --json $QA_JSON"
else
  "$PY" "$TOOLS/verify_anim.py" --input "$OUT" --expect "$EXPECT" --json "$QA_JSON" \
    | grep -E "===|判定" | sed 's/^/  /'
  # 闸门退出码在这里不需要（后面的 action.json 已经记录 qa.ok），去掉死代码
fi

if [ "$DRY" = 0 ]; then
  "$PY" - <<PYEOF
import json, os, sys, datetime
out = "$OUT"
qa = json.load(open("$QA_JSON", encoding="utf-8")) if os.path.isfile("$QA_JSON") else {"items": []}
item = qa["items"][0] if qa.get("items") else {}
meta = {
    "kind": "action",
    # 版本号从仓库根的 VERSION 读，避免和实际版本对不上
    "version": open(os.path.join("$PIPELINE_HOME", "VERSION"), encoding="utf-8").read().strip(),
    "name": "$ACTION",
    "source": "library",
    "origin": os.path.basename("$CLIP"),
    "rig": "$NAME",
    "frames": item.get("frames"),
    "fps": 30,
    "loopable": bool($LOOPABLE),
    "in_place": True,
    "files": sorted(f for f in os.listdir(out) if f.endswith((".fbx", ".glb"))),
    "qa": {
        "expect": qa.get("expect", "any"),
        "ok": item.get("ok"),
        "note": item.get("note"),
        "root_rotation_deg": round(item.get("root_rotation_deg", 0), 1),
        "limb_rel": round(item.get("limb_rel", 0), 3),
    },
    "created": datetime.date.today().isoformat(),
}
with open(os.path.join(out, "action.json"), "w", encoding="utf-8") as fh:
    json.dump(meta, fh, indent=2, ensure_ascii=False)
print("  动作元数据: %s/action.json（source=library, qa.ok=%s）" % (out, meta["qa"]["ok"]))
PYEOF
fi

echo
echo "============================================================"
echo "产物："
ls -la "$OUT"/*.fbx "$OUT"/*.glb 2>/dev/null | sed 's/^/  /'
echo "  （角色本体在 $RIG/$NAME.glb，Unity 里用同一套 Avatar）"