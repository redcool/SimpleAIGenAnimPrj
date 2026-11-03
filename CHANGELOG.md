# 变更记录

版本号规则（见 Agent工作纪律.md 第 6 条）：
x 世代版本（人手）、y 大版本（人手）、z 大功能（agent 可动）、w 小改动（agent 可动）。

## 1.0.1.0

把工程从"两条命令"升级成"一条产线"：统一入口、统一契约、统一闸门。

- 新增 `docs/动作产线规范.md`：决策流程（先查分布 → 库 → 机械补 → 手工/微调）、
  两条产线的命令、输出契约、命名规范（gen_/lib_/act_/loc_）、三道质量闸门、Unity 侧字段约定。
- 新增 `tools/action_meta.py`：写统一的 `action.json`（name/source/origin/rig/frames/
  loopable/in_place/qa/files），两条产线共用。模型产线会在循环化结束时自动写。
- `tools/verify_anim.py` 增加 `--expect motion|roll` 与 `--json`，并返回非零退出码，
  可以直接当闸门用。
- `unimate-import-clip.sh` 增加第 5 步质量闸门 + 自动写 `action.json`；
  同时修了重复运行的两个问题：精简结果写进工作目录（不再往素材目录堆 _v2），
  rig_preprocess 加 `--overwrite`。
- `tools/simplify_rig.py` 增加 `--force`（显式允许覆盖，默认仍不覆盖）。

## 1.0.0.9

- 新增 `tools/verify_anim.py`：把"整体翻转"和"四肢在不在动"**分开量**。
  四肢幅度在根骨坐标系里计算，这样整体旋转不会污染姿态测量。
  实测：动作库版 49.9%、程序补旋转版 7.4% —— 后者就是"躺着被转一圈"。
- 修正 AGENTS.md 5.6：程序补旋转只适合刚体（车轮/滚筒）或基础片段四肢动作已很足的情况；
  有四肢的动作请走动作库（5.8）。上一版把它写成通用补救方案是错的。
- `docs/动作能力清单.md` 增 5.5 实测教训：只看累计转角会误判，必须同时量四肢动作。

## 1.0.0.8

- 新增 `scripts/unimate-import-clip.sh`：把动作库片段接到自己的角色上（精简骨架 →
  转特征 → 关节顺序对齐 → 驱动导出），一条命令跑完。
- 新增 `tools/remap_motion_joints.py`：同一套骨架不同导出时，左右兄弟骨顺序可能相反，
  按骨名把关节轴重排到目标骨架（UniMate 的 check_canonical_order 会直接报错）。
- 实测 Mixamo 的 Sprinting Forward Roll（36 帧）驱动 X Bot：根骨累计 484°、主轴横向、
  髋部 0.135~0.843，是真翻滚。两版对比放在 outputs/samples/roll_compare/。
- `scripts/_env.sh` 的 abs_path 依次在 当前目录 / 工程根 / 工程上一级 查找，
  这样 Arts/ 这类放在工程外的素材也能直接传相对路径。
- `docs/动作能力清单.md` 新增第 5 节：能不能靠继续训练补上 ——
  加 Mixamo 数据没用（已在训练集里）；表示层限制（整圈翻转）加多少数据都学不会，
  必须改特征并重训；真正划算的是稀有但可表示的类别（手势、爬行）做微调。

## 1.0.0.7

- 新增 `docs/动作能力清单.md`：基于 UniML3D 全部 13,769 条 caption 统计出 16 个类别及占比，
  给出「>5% 稳 / 1~5% 多采 / <1% 边缘 / 查不到没学过」的判定线，
  以及做不到时的处理办法（多采 / 程序补 / 外部库 / 手工）。
- 新增 `tools/caption_stats.py`：复现上述统计，可 `--grep` 查单个动作。
- 查清翻滚的结构性原因：根朝向由关节位置的水平投影算出（只含偏航），
  根骨旋转又被朝向四元数顶替，所以整圈翻转在表示层不可表达
  —— 数据里有 191 条 roll/flip 也生成不出来，与实测「根骨偏转 ≤26°」一致。
- AGENTS.md 新增 5.7：先查分布再动手。

## 1.0.0.6

- 新增 `tools/roll_check.py`：判断一段动作有没有真翻过去（根骨累计转角 + 主轴方向）。
- 新增 `tools/add_root_spin.py`：给已有动画的根骨叠加旋转（前滚翻 / 转身 / 侧翻），
  世界侧旋转换算到骨骼局部，支持圈数、轴向、缓入缓出。
- `AGENTS.md` 新增 5.6：实测所有生成动作的根骨偏转 ≤26° 且只会偏航，
  所以 360° 翻滚模型做不出来（四种说法 8 条采样，累计 9°~126°），给了混合方案。
- 修 `unimate-sample.sh` / `unimate-animate.sh`：`--asset`、`--output_dir`、
  `<采样目录>` 这类路径参数先按本工程根解析再转绝对路径。
  原来传相对路径会被 UniMate 当成自己仓库里的路径（报 no such directory /
  unknown DATASET_TYPE），这是实际操作中最容易踩的一脚。

## 1.0.0.5

- 新增 `tools/gait_report.py`：从 .npy 直接算四条腿的竖直摆幅和相位相关系数，
  给一句判定（小跑 / 袭步 / 相当弱 / 有腿不动）。四足挑样本不用先看视频。
  实测 Fox（Khronos 示例）：walk 一条是对角同相的成型步态，另一条只剩 0.006 幅度；
  run 两条都是袭步。
- `unimate-pipeline.sh` 增加权重校验：资产不是 Mixamo 22 关节绑定却用了人体专用权重时，
  直接说明并提示改用 `--exp-dir models/unimate_uniml3d_f60_v3`，
  不再走到精简步骤才报「不是标准 Mixamo 绑定」。
- `AGENTS.md` 新增 5.5 四足检查清单：两个四足的标签质量实测、朝向对与脚趾这两处
  需要人工确认、权重选择、以及 gait_report 的用法。

## 1.0.0.4

- `AGENTS.md` 新增第 5 节「资产从哪来」：明确 UniMate **不做自动绑定**，
  `rig_preprocess` 的四步分别做什么、四条硬条件怎么查、支持的形体与三个权重的关节范围、
  外部绑定工具（Mixamo / Rigify / AccuRig 等）以及四足的前后腿标签约定。
- `AGENTS.md` 第 6 节「从零到出片」补上绑定前提和体检/精简这一步；后续小节编号顺延。
- `tools/inspect_rig.py` 增加绑定检查：报 armature 数量（>1 时警告）、
  按主网格判断是否绑定、列出未绑定的零碎对象。
- README 快速开始补上「前提：模型已经绑定好」。

## 1.0.0.3

- **权重和产物搬进本工程**：`models/`（权重）+ `outputs/`（rig 产物、采样结果），
  一起加进 `.gitignore`。理由：上游 UniMate 随时可能被重新克隆或清理，权重放它里面很危险。
- **配置语义变化**：`UNIMATE_EXP` / `UNIMATE_SAMPLES` / `UNIMATE_RIGS` 的相对路径基准
  从 `UNIMATE_HOME` 改成**本工程根目录**，并在 `_env.sh` 里统一转成绝对路径导出。
- 历史 `manifest.json` / 报告里的路径批量改写到新位置（16 个文件），已有产物不用重新采样。
- 新增 `scripts/install_blender_shim.sh`：UniMate 的导出脚本写死调用 `blender`，
  这个脚本把调用接到 pip 的 bpy 上（没有装 Blender 也能导出）。
- 新增 `AGENTS.md`：权重 / 数据集下载方式、产物结构、硬约束、排错速查。
- 修：`setup.sh` 的版本校验把注释行当成了 commit。

## 1.0.0.2

- 修：流水线的 rig / 采样目录改成绝对路径。原来打印相对路径，用户换个
  工作目录再跑下一步就会解析错（`abs_path` 是按当前目录解析的）。

## 1.0.0.1

- 文档迁移：`docs/快速上手.md` 里的脚本路径改到 `scripts/`，顶部加了迁移说明。
- 无代码改动。

## 1.0.0.0

首个版本。把此前散落在 UniMate 仓库里的工具拆成独立工程，UniMate 只作只读依赖。

### 功能

- `scripts/unimate-inspect.sh` 骨架体检：关节数、层级、蒙皮权重覆盖、动画数量。
- `scripts/unimate-simplify.sh` 骨架精简：按 Mixamo 22 根核心骨或自定义正则删骨，
  并把被删骨的蒙皮权重并入最近的保留祖先（实测 X Bot 65→22，0 个顶点失去权重）。
- `scripts/unimate-pipeline.sh` 一条龙：体检 → 超标才精简 → rig_preprocess → 采样 → 导出。
  目标关节数按权重自动定（人体专用权重固定 22，通用权重默认 71）。
- `scripts/unimate-loop.sh` 循环化，两条路线：
  - 后处理：起点与周期一起搜，剪切 + 接缝淡化（走/跑接缝 0.62~1.10）；
  - 模型闭环 `--close`：末 2 帧钉成首帧 + 速度外推，替换式采样重算中间（待机 1.36~2.21）。
- `tools/flatten_root.py` 拉平根位移，动作变原地。
- `tools/bundle_unity.py` 打包 Unity 目录：角色 FBX + `anim/<类别>_<序号>.fbx` + 带循环质量表的说明。

### 与上游的接口

- 只依赖 UniMate 的公开模块 + `sample.py` 的几个私有辅助函数，全部封装在
  `tools/unimate_api.py`；验证过的 commit 记在 `unimate_version.txt`，启动时不一致会警告。