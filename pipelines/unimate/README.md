# pipelines/unimate —— UniMate 抽卡产线

> 这是**产线封装**，不是上游模型仓库。上游在 `$UNIMATE_HOME`（只读，不改）。

本目录负责用 UniMate 生成动作、把生成结果做成可循环片段、导出成引擎能吃的 FBX/GLB；
同时也负责把**动作库片段**接进同一套骨架（复用同一批 rig_preprocess / animate 能力，
所以没有单独拆目录）。

## 入口（脚本）

| 脚本 | 干什么 | 典型场景 |
|---|---|---|
| `unimate-inspect.sh` | 骨架体检：关节数、蒙皮、朝向 | 接新资产第一步 |
| `unimate-simplify.sh` | 精简骨架（Mixamo 65→22 等） | 关节超限 |
| `unimate-pipeline.sh` | 一条龙：体检 → 精简 → 打标签 → 采样 → 导出 | 给角色出整套动作 |
| `unimate-sample.sh` | 只采样（抽卡） | 补采、换 prompt 试 |
| `unimate-animate.sh` | 只导出（动作特征 → 带动画 FBX/GLB） | 已有 npy 想重导 |
| `unimate-loop.sh` | 循环化 + 原地化 + 打包 Unity + 写 action.json | 走跑待机要循环 |
| `unimate-import-clip.sh` | 动作库片段接入（精简→特征→对齐→驱动→闸门） | 模型做不出的动作 |
| `unimate-import-batch.sh` | 批量接入一个目录 | 一次下了一批库片段 |
| `unimate-pack.sh` | 打包两版交付（调 `deliver_pack.py`） | 交付前 |
| `install_blender_shim.sh` | 装 blender 命令的 shim（用 bpy 代替） | 一次性 |

## 工具（`tools/`）

| 工具 | 职责 |
|---|---|
| `unimate_api.py` | **唯一** import UniMate 内部的文件 |
| `make_loop.py` | **编排层**：解析参数、逐条跑流程、写 `loop_report.json`（228 行） |
| `cycle_search.py` | 找周期：四足按四肢轨迹、两足按全身旋转；含静止保护、行程约束、候选打分（260 行） |
| `loop_cut.py` | 切循环：裁剪、接缝淡化、接缝指标、一句判定（126 行） |
| `loop_close.py` | 让模型把末帧收回首帧（待机这类没有周期时用） |
| `flatten_root.py` | 根位移拉平，变原地动作 |
| `add_root_spin.py` | 给根骨补旋转（只适合刚体） |
| `bundle_unity.py` | 整理 Unity 目录 + 导入说明 |
| `inspect_rig.py` / `simplify_rig.py` | 体检 / 精简 |
| `gait_report.py` | 多足步态速查（摆幅 + 相位） |
| `verify_anim.py` | 整体翻转与四肢动作分开量（质量闸门） |
| `roll_check.py` | 判断有没有真翻过去 |
| `cycle_candidates.py` | 列出候选循环区间（帧号 + 脚差） |
| `deliver_pack.py` | 打包两版交付：`anim/`（循环版）+ `full/`（完整序列 + 候选帧清单） |
| `remap_motion_joints.py` | 库片段与角色关节顺序对齐 |
| `rig_joints.py` | 四肢识别（gait_report 与 make_loop 共用） |
| `caption_stats.py` | 查某个动作在训练分布里的占比 |

## 常用命令

`````````bash
# 给一个已绑定的角色出整套动作
bash pipelines/unimate/scripts/unimate-pipeline.sh --input "Arts/models/Dog_001.fbx" \
    --name Dog_001 --exp-dir models/unimate_uniml3d_f60_v3 --reps 3 \
    --prompt "An object stands still." --prompt "An object walks forward." \
    --prompt "An object runs forward." --out outputs/samples/Dog_001

# 循环化 + 交付
bash pipelines/unimate/scripts/unimate-loop.sh --samples outputs/samples/Dog_001 \
    --name Dog_001 --rig outputs/rig/Dog_001/Dog_001.glb \
    --out outputs/actions/Dog_001_locomotion

# 动作库补一条
bash pipelines/unimate/scripts/unimate-import-clip.sh \
    --clip "Arts/mixamo/Sprinting Forward Roll.fbx" \
    --rig outputs/rig/X_Bot --name X_Bot --expect roll --action act_roll_fwd
`````````

## 边界

- 模型做不出的动作（整圈翻转等）：看 `docs/动作能力清单.md` 与 `docs/待补动作清单.md`。
- 交付契约与命名：`docs/动作产线规范.md`。
- 循环点怎么定、两版交付（循环版 + 完整序列）：`docs/动物动作交付.md`。