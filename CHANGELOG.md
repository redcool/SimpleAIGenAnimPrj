# 变更记录

版本号规则（见 Agent工作纪律.md 第 6 条）：
x 世代版本（人手）、y 大版本（人手）、z 大功能（agent 可动）、w 小改动（agent 可动）。

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