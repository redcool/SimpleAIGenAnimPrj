# AGENTS.md —— 给在这个工程里干活的 agent 看

本工程把 [UniMate](https://github.com/Friedrich-M/UniMate) 包成一条动画产线。
读这个文件的人（或 agent）默认要动代码或跑流程，所以先讲清楚边界和数据在哪。

## 0. 三条边界

1. **不改 UniMate**。它是只读依赖，用 commit 锁定（见 `unimate_version.txt`）。
   真需要改模型或采样逻辑，去 fork，另开补丁，不要动这里的依赖。
2. **权重、产物、数据集都不入库**。`models/`、`outputs/`、`dataset/` 都在 `.gitignore` 里。
   它们体积大，下载方式见本文第 2、3 节。
3. **临时文件进 `tmp/`，删文件进 `.trash/`，同名不覆盖（加 `_v2`）**；版本号遵循
   `Agent工作纪律.md` 第 6 条：x.y 由人定，z（大功能）和 w（小改动）由 agent 维护，
   唯一来源是 `VERSION`。

## 1. 目录

按能力分目录（v1.0.5.0 起，细节见 `docs/目录重构说明.md`）：

```
AIGenAnimPrj/
├── core/              跨来源共用：env.sh、pipeline_config、action_meta、action_index
├── pipelines/
│   └── unimate/       UniMate 抽卡与库片段接入（scripts/ 入口 + tools/ 实现）
├── Motion2MixamoRig/  动补重定向（独立模块，保持原位）
├── scripts/  tools/   兼容层：老命令仍可用，只转发到新位置并打印弃用提示
├── models/            ★ 权重，不入库          （本文第 2 节）
├── outputs/           ★ rig / samples / actions，不入库（本文第 4 节）
├── dataset/           ★ UniML3D 数据集，不入库，可选（本文第 3 节）
├── docs/  tmp/  .trash/
```

两个"UniMate"别混：`$UNIMATE_HOME` 指**外部只读仓库**，`pipelines/unimate/` 是**我们的封装**。

## 2. 下载权重（必做）

两个权重都发布在 HuggingFace 的 `Linzhan/UniMate`（model repo）：

| 目录 | 用途 | 关节 | 大小 | 需要的文件 |
|---|---|---|---|---|
| `models/unimate_mixamo_f60_v2` | 人体专用，**推荐** | 固定 22 | 约 730 MB | config.json、dataset_stats.npy、checkpoints/checkpoint_step_120000.pt |
| `models/unimate_uniml3d_f60_v3` | 通用，任意骨架 | 5~70 | 约 1.2 GB | config.json、dataset_stats.npy、checkpoints/checkpoint_step_150000.pt |
| `models/unimate_truebones_f60_v2` | **动物专用** | 5~85 | 约 730 MB | config.json、dataset_stats.npy、checkpoints/checkpoint_step_80000.pt |

### 用 Python（推荐，可控）

```bash
export HF_HUB_DISABLE_XET=1     # 必须：xet 后端在不少网络下会挂住，表现为"缓存 0 字节"

python - <<'EOF'
from huggingface_hub import snapshot_download

# 人体专用
snapshot_download("Linzhan/UniMate", repo_type="model", local_dir="models",
    allow_patterns=["unimate_mixamo_f60_v2/config.json",
                    "unimate_mixamo_f60_v2/dataset_stats.npy",
                    "unimate_mixamo_f60_v2/checkpoints/checkpoint_step_120000.pt"])

# 通用
snapshot_download("Linzhan/UniMate", repo_type="model", local_dir="models",
    allow_patterns=["unimate_uniml3d_f60_v3/config.json",
                    "unimate_uniml3d_f60_v3/dataset_stats.npy",
                    "unimate_uniml3d_f60_v3/checkpoints/checkpoint_step_150000.pt"])
EOF
```

### 用 hf 命令行

```bash
hf download Linzhan/UniMate --repo-type model --local-dir models \
    --include "unimate_mixamo_f60_v2/*.json" --include "unimate_mixamo_f60_v2/*.npy" \
    --include "unimate_mixamo_f60_v2/checkpoints/checkpoint_step_120000.pt"
```

### 三个坑

- **别下整个模型目录**。`unimate_mixamo_f60_v2/checkpoints/` 里有 13 个历史 checkpoint，
  每个约 765 MB，全下要 10 GB。只要最新的那一个。
- **必须带 `config.json` 和 `dataset_stats.npy`**。前者定义模型结构，后者是归一化统计，
  缺任何一个 sampler 都起不来。
- **网络慢**（实测国内约 1 MB/s）：可设 `HF_ENDPOINT=https://hf-mirror.com` 换镜像；
  下完核对：`du -sh models/*` 应接近上表体积。

### 校验下载结果

```bash
ls models/unimate_mixamo_f60_v2/checkpoints/checkpoint_step_120000.pt   # 必须存在
bash setup.sh                                                          # 6 项依赖 + 版本检查
```

## 3. 下载 UniML3D 数据集（可选）

只有两种情况需要：① 想用训练集的 caption 当 prompt 参考；② 想训练或做数据侧对比。
**日常生成动作不需要它。**

```bash
# 只要 caption（很小，写 prompt 时查用例）
hf download Linzhan/UniML3D --repo-type dataset --local-dir dataset \
    --include "features/*/captions*.json"

# 训练用的特征（几十 GB；README 给的完整下载见上游仓库）
hf download Linzhan/UniML3D --repo-type dataset --local-dir dataset \
    --include "features/*" --exclude "features/*/videos/*" --exclude "features/*/tpose/*"
```

全量约 88 GB。下载后目录是 `dataset/features/<dataset>/`，
其中 `captions*.json` 就是官方 prompt 的写法来源（`"An object ..."` 句式）。

## 4. 采样产物：自己生成，不用下载

`outputs/` 里的东西都是本地跑出来的，换机器要重跑，不要指望下载：

```
outputs/
├── rig/<资产名>/          rig_preprocess 产物：cond.npy、<资产名>.glb、preview.png、summary.json
│   └── motions/           （用 --save_clips 才有）资产自带的片段，供插帧/编辑用
└── samples/<批次>/
    ├── motions/*.npy      模型生成的 12 维动作特征（每帧 J×12）
    ├── animations/*.mp4   骨骼预览视频（--only_save_motion 可跳过）
    ├── animated/*.glb     ★ 带动画的网格，Unity 用这个（另有 .fbx）
    ├── manifest.json      这批用了哪个权重、哪个资产、什么 prompt
    └── captions.json      文件名 → prompt 的对照
```

想复刻别人的结果，靠的是 `manifest.json` 里的 `exp_dir / cond_path / prompt / cfg_scale`，
不是下载产物。注意 manifest 里存的是**绝对路径**，换机器后这些路径会失效，
需要重新采样（或者在 manifest 里改路径再跑 `unimate-animate.sh`）。

## 5. 资产从哪来：绑定这一步不在本工程里

**UniMate 不做自动绑定。** 它的输入必须已经是一个 armature + 蒙皮网格，输出只有动作。
手上只有没绑定的网格时，先在外部工具里把绑定做掉，再回到本工程。

### 5.1 rig_preprocess 不是「自动绑骨」

名字容易误会。它做四件事，没有一件是生成骨架：

| 步骤 | 做 | 不做 |
|---|---|---|
| 1 Export | 读入你的骨架，剪掉不带动画的辅助骨 | 不生成骨 |
| 2 Annotate | 把**已有**骨头映射到标签词表、选朝向对 | 不改骨名与层级 |
| 3 Features | 算 T-pose / 层级 / 拓扑，写 `cond.npy` | 不算蒙皮权重 |
| 4 Bake | 把网格与骨架烘到 canonical 帧（站地、朝 +Z） | 不改绑定拓扑 |

第 2 步默认停下来等 review（`REVIEW.md`、`annotation_preview.png`）。
标签或朝向错了整段动作就废——所以它不是全自动的。

### 5.2 四条硬条件

| 条件 | 怎么查 | 不过怎么办 |
|---|---|---|
| 关节数 5~70（模型吃 ≤71；truebones 权重到 85） | `unimate-inspect.sh` 的「关节数」 | `unimate-simplify.sh` |
| 单 armature（一个文件一套骨架） | inspect 输出的 armature 列表 | 先合并或删掉多余骨架 |
| 关节能映射到标签词表 | `REVIEW.md` 里 flagged 的骨头 | 手改 `annotation.json` 的 `label` |
| 朝向对可判定（两关节水平分开） | `annotation_preview.png` 的绿箭头 | `--face_r` / `--face_l` 手动指定 |

### 5.3 哪些形体支持

训练数据覆盖 bipedal（两足）、quadrupedal（四足）、avian（鸟）、marine（水生）、
insectoid（虫）、serpentine（蛇）、articulated rigid objects（带关节的刚体物件）。

| 权重 | 关节 | 说明 |
|---|---|---|
| `unimate_uniml3d_f60_v3` | 5–70 | 通用，推荐 |
| `unimate_mixamo_f60_v2` | 22 固定 | 只吃 Mixamo 22 关节人体 |
| `unimate_truebones_f60_v2` | 5–85 | 动物专用，能吃到 85 关节（唯一不支持 Dragon） |

实测过的四个：X Bot 65→22（两足）、Eagle 51（鸟）、shark 16（鱼）、unitree_go2 18（四足机器人）。

容易翻车的情况：比例极端、密集骨架（全套手指 + 表情）、部件语义模糊（抽象雕塑）、
rest pose 躺倒或倒置（加 `--rest_rotation x180` 摆正）、训练里稀有的体形。

### 5.4 外部绑定工具

| 工具 | 适合 | 出来之后怎么接 |
|---|---|---|
| Mixamo 自动绑定（免费） | 人形首选 | 65 关节 → `--mode mixamo` 削到 22 |
| Blender Rigify | 人形，可定制 | 骨名不固定 → `--mode keep/drop` 指定正则 |
| AccuRig / Meshy / Tripo | 人形、四足 | 视工具输出，先跑 `unimate-inspect.sh` 看关节数 |
| 手工绑定 | 蛇、虫、花等特殊体形 | 目前没有可靠的全自动方案 |

**四足特别提醒**：前腿按手臂标签（`Shoulder` / `Upper Arm` / `Forearm` / `Hand`），
后腿按腿标签（`Thigh` / `Shin` / `Foot` / `Toe`），朝向对仍取左右大腿。
完整规范在 UniMate 的 `data_process/rig_preprocess/AGENTS.md`，改标签前先读它。

### 5.5 四足检查清单（实测数据）

拿两个四足验过：一个机器人（`unitree_go2`，骨头是 `FR_hip` / `RL_calf` 这类编码名），
一个动物（Khronos glTF 示例的 Fox，骨头是 `b_RightUpperArm_06` / `b_LeftLeg01_015`）。

**标签质量**（`--annotate rule`，不走 LLM）：

| 资产 | 关节 | 结果 |
|---|---|---|
| unitree_go2 | 18 | 17/18 与官方标注一致；唯一分歧是根骨 `Body` vs `Root`，两个都是合法词 |
| Fox | 24 → 22 | 22 个标签全部来自 template 匹配（training rig 同构），0 个 flag |

**两处要人工确认**（两个资产都出现了）：

1. **朝向对**。规范首选左右大腿，但规则标注在 Go2 上选了前髋（官方标注自己也带告警），
   在 Fox 上选了前肢上臂（`source=upper arm`）。左右轴是对的，能用；
   但如果动作明显朝侧面走，用 `--face_r` / `--face_l` 显式指定**后腿大腿**。
2. **脚趾没拆开**。Fox 的 `b_LeftFoot01_017` 与 `b_LeftFoot02_018` 都被标成 `Left Foot`。
   规范里更合适的是 `Foot` + `Toe`。影响不大，但会丢一点踝部细节。

**权重必须换成通用版**。默认配置是人体专用（22 关节固定），四足会被判成"不是 Mixamo 绑定"。
v1.0.0.5 起管线会直接说清楚并退出，提示这样跑：

```bash
bash pipelines/unimate/scripts/unimate-pipeline.sh --input fox.glb --exp-dir models/unimate_uniml3d_f60_v3
```

**动作质量先用数字看，再决定要不要看视频**：

```bash
python pipelines/unimate/tools/gait_report.py --samples outputs/samples/Fox
```

输出四条腿的竖直摆幅 + 两两相位相关系数，并给一句判定：

| 判定 | 含义 |
|---|---|
| 对角同相 + 左右反相 | 小跑 / 快走，正常 |
| 前后各自同相 | 袭步 / 跳跃式，跑动正常 |
| 相位很弱 | 不像成型步态，多采几条挑 |
| 有腿几乎不动 / 几乎不动 | 这条废了，换一条 |

Fox 实测 4 条（2 prompt × 2 reps）：walk 一条是「对角同相 +0.59 / 左右 -0.78」的成型步态，
另一条整体强度只有 0.006（废条）；run 两条都是袭步（左右 +0.95 / +0.61）。
结论：**四足同样要按 `--reps` 多采、按指标挑**，不要指望第一条就能用。

### 5.5.1 动物骨架的实测边界

| 资产 | 关节 | 动作 | 结果 |
|---|---|---|---|
| Khronos Fox | 22（标准四足骨名） | walk/run | **出过成型步态**（对角同相 +0.59 / 左右 -0.78） |
| alpaca（用户提供） | 43（耳朵×3、脖子×5、带 IK 控制骨） | run/trot/gallop | **四腿同相 +0.93~1.00 = 整体弹跳**，换动物专用权重也一样 |
| alpaca | 43 | 待机 | 可用（幅度 0.004，符合待机） |

**Unity Store 动物包合格用**（Chicken / Deer / Dog / Horse / Kitty / Pinguin / Tiger，
20~45 关节、单 armature、蒙皮 1/1、骨名规范、自带动画）：规则标签 **0 个 flag**，
全部由骨名匹配。Dog 实测 `run` 4 条里有 1 条是成型袭步（左右 +0.94），
其余 3 条相位真实交替（后腿对 -0.73/-0.75，不是整体弹跳），待机幅度 0.0013 正确。
唯一注意：前腿被标成 `Left Front Thigh/Shin/Foot`（机器人式命名），
若步态看着别扭，可手工改成手臂链（Shoulder / Upper Arm / Forearm）。

结论：**骨架越接近训练里的标准四足（骨名干净、20~30 关节），步态越容易成型**；
耳朵/脖子一大串、带 IK 控制骨的复杂骨架，模型容易退化成整体起伏。
两条应对：① 换库里的四足步态；② 简化骨架（去掉耳朵/尾巴末节这类不参与步态的骨头）再跑。

### 5.6 模型做不出的动作：整圈翻转

实测：所有生成动作里根骨相对首帧的最大偏转只有 **26°**，旋转轴永远是竖直方向。
也就是说根节点旋转通道是"朝向"（偏航），训练数据里没有俯仰/侧倾翻转。

结论：**360° 前滚翻、后空翻、侧翻这类动作，模型生成不出来**，换 prompt 也没用
（试过 forward roll / combat roll / rolls on the ground / rolls and stands up 四种说法，
累计转角只有 9°~126°）。

补救有两条路，按实测效果排：

1. **用动作库（推荐）** —— 见 5.8。Mixamo 的 `Sprinting Forward Roll` 接到 X Bot 后实测：
   根骨累计 484°、主轴横向、四肢动作幅度 49.9%（相对骨架）—— 真翻滚。
2. **程序补旋转**（`add_root_spin.py`）—— 只适合**刚体**（车轮、滚筒、螺旋桨）或者
   基础片段本身四肢动作就很足的情况。实测把"贴地不动"的生成片段补一圈，
   四肢动作只有 **7.4%**，观感是"躺着被转一圈"，不能当翻滚用。

判断一段动画够不够好，用 `tools/verify_anim.py`：它**分开量**
整体翻转（根骨累计转角 + 主轴）和四肢动作（在根骨坐标系里的位置变化）。
只有两者都够才是真翻滚 —— 这一条是踩坑补上的：只看转角会把
"整体转一圈但姿势不动"判成合格。

### 5.7 动作能不能做：先查分布

模型只做训练分布内的动作。判定依据是 caption 占比（13,769 条统计，见
docs/动作能力清单.md）：

| caption 里的占比 | 判断 | 做法 |
|---|---|---|
| > 5% | 分布中心 | 直接用 |
| 1% ~ 5% | 学过但稀有 | `--reps 6` 以上 + 指标挑（gait_report / roll_check / 循环报告） |
| < 1% | 边缘 | 暴力多采，同时准备替代方案 |
| 查不到 | 没学过 | 别在 prompt 上耗，走替代方案 |

自查：`python pipelines/unimate/tools/caption_stats.py --meta tmp/meta --grep <动作词>`
（元数据几 MB，不用下 88 GB 数据集）。

**循环点怎么定**（v1.0.4.3 起，v1.0.5.6 调整）：**四足按脚、两足按姿态** ——
四条腿才用四肢末端轨迹（两个接触点太容易碰巧对上，上身可能拧着：
实测人形按脚时旋转接缝从 0.75 劣化到 1.4）；两条腿退回按全身旋转，结果与历史一致。
四足的规则是：
在整段里找两帧"几只脚几乎相同"，前一帧当起点、后一帧当终点
（`make_loop.py --basis feet`，四足默认走这条）。判"像不像"用的是**脚的行程比例**
（`--foot-tolerance 0.12`），不是绝对距离，否则大小体型不能用同一套阈值。
脚几乎不动时（待机）自动不切周期，避免切成几帧的假循环。
报告里的 `foot_seam_ratio` 是接缝处脚差了几倍正常步长 —— **≤1.1 才算能用**，
1.4 以上会在循环处看得见一顿。

已知的结构性边界：**整圈翻转不可表达**（根朝向由关节位置水平投影算出，只含偏航；
根骨旋转又被朝向顶替）。翻滚在数据里有 191 条也生成不出来——走动作库（5.8），
或者只在刚体场合用 `add_root_spin.py`（5.6）。

### 5.8 外部动作库接入（模型做不到时的第一选择）

库里有的动作，直接用；模型做不到的动作大多属于这一类（翻滚、攀爬、受击倒地）。

一条命令（片段与角色同一套骨架时）：

```bash
bash pipelines/unimate/scripts/unimate-import-clip.sh \
    --clip "Arts/Sprinting Forward Roll.fbx" \
    --rig outputs/rig/X_Bot --name X_Bot \
    --out outputs/samples/roll_lib_test
```

内部走四步：

1. `simplify_rig.py --mode mixamo` 把片段骨架削到目标关节数；
2. `rig_preprocess --save_clips` 把片段转成 UniMate 特征 npz；
3. `remap_motion_joints.py` 按骨名把关节顺序对齐到角色
   （同一套骨架不同导出，左右兄弟骨顺序可能相反，UniMate 会报
   "joint order is not the motion's"）；
4. 用角色的 cond + `run_animate_motion.sh` 驱动导出 GLB/FBX。

实测：Mixamo 的 `Sprinting Forward Roll`（36 帧）接到 X Bot 上，
根骨累计转角 484°、主轴横向、髋部 0.135~0.843 —— 是真正的翻滚。
两个版本（库 vs 模型+程序补）在 `outputs/samples/roll_compare/` 可以直接对比。

## 6. 从零到出片

前提：**资产已经绑定好**（没绑定先看第 5 节）。

```bash
cp config.example.env config.env      # 填 UNIMATE_HOME / UNIMATE_PYTHON
bash setup.sh                          # 依赖自检
bash pipelines/unimate/scripts/install_blender_shim.sh   # 一次性：让 UniMate 的 blender 调用走 bpy

# 0. （可选）先单独体检，避免跑完管线才发现关节不对
bash pipelines/unimate/scripts/unimate-inspect.sh --input /path/to/model.fbx --no-bones
#    超了先精简：Mixamo 绑定用 --mode mixamo，其它骨架用 --drop 正则
bash pipelines/unimate/scripts/unimate-simplify.sh --input /path/to/model.fbx --mode mixamo

# 1. 一条龙：体检 -> 精简（超标才跑）-> 打标签 -> 采样 -> 导出
bash pipelines/unimate/scripts/unimate-pipeline.sh --input /path/to/model.fbx --reps 3

# 2. 循环化 + 打包 Unity
bash pipelines/unimate/scripts/unimate-loop.sh --samples outputs/samples/<资产名> --name <资产名> \
    --rig outputs/rig/<资产名>/<资产名>.glb
```


## 7. 硬约束（踩过坑的）

| 约束 | 原因 / 后果 |
|---|---|
| Python 必须是 **3.10** | pip 的 `bpy` 只有 cp310 轮子，装不上就没有 GLB/FBX 导出 |
| torch 必须匹配 GPU | RTX 5090 是 sm_120，默认 cu124 会报 no kernel image，用 `env/requirements.cu128.txt` |
| 关节 ≤ 71（人体专用固定 22） | 超了 sampler 直接不吃；先跑 `unimate-simplify.sh` |
| 必须有 `blender` 命令 | UniMate 的导出脚本写死调用它；没有装 Blender 就用 shim |
| 模型吃的是**标签**不是骨名 | 标签错 = 动作错；每个资产都要看 `preview.png` 和 `REVIEW.md` |
| 动作是原地（in-place） | 位移交给引擎；不要期待根位移 |
| **资产必须已经绑定** | 本工程不建骨、不算权重；只有网格没有骨架的资产无处可动（第 5 节） |

## 8. 排错速查

| 现象 | 原因 | 处理 |
|---|---|---|
| `Fetching N files` 卡住、缓存 0 字节 | xet 后端 | `export HF_HUB_DISABLE_XET=1` |
| `No config.json in ...` | 权重只下了 .pt | 补 `config.json` 和 `dataset_stats.npy` |
| `blender: command not found` | 没装 shim | `bash pipelines/unimate/scripts/install_blender_shim.sh` |
| `fits=false` | 关节超 71 | 先精简 |
| 生成的动作"抖"或"不像" | prompt 风格不对 / cfg 太低 | 照 `An object ...` 句式；`--cfg_scale 5~7` |
| 循环处一跳 | 周期没找对 | 走 `unimate-loop.sh`；四足看 `loop_report.json` 的 `foot_seam_ratio`（>1.4 就是脚没接上，换一条） |

## 9. 两条产线与输出契约

**来源优先级（硬规则）**：先试模型，做不出/做不好再走库。库动作是候选，不是默认。
交付必须标来源（`action.json` 的 `source` / `origin`），索引表能直接看出来。

动作来源只有两类，**都要在 `AIGenAnimPrj` 里落成同一种产物**：

| 产线 | 命令 | 适用 |
|---|---|---|
| A 模型生成 | `unimate-pipeline.sh` → `unimate-loop.sh` | 训练分布内（≥1% caption 占比） |
| B 动作库接入 | `unimate-import-clip.sh` | 分布外、库里有的（翻滚/攀爬/受击） |

每个动作目录都要有 `action.json`（`core/action_meta.py` 写）：
记 `source`（model/library）、`origin`（prompt 或片段名）、`loopable`、`in_place`、`qa`。
**照着做事就打开 `docs/操作手册.md`**（五个场景：新角色出整套动作 / 补单条库动作 /
批量补库 / 盘点索引 / 判断该不该走库）。

完整规范（决策流程、命名、闸门、Unity 约定）见 `docs/动作产线规范.md`；
哪些动作该从库补、优先级怎么排，见 `docs/待补动作清单.md`。

动作目录：**`outputs/actions/<动作>/` 是交付物**（每个含 `action.json`），
`outputs/samples/` 只是采样中间产物。

**循环动作一律出两版**（用户 2026-11-04 定）：`anim/` 是程序处理过的循环版，
`full/` 是**未处理的完整序列**（Tiger/Horse 的 walk/run 是 160 帧 3 段串接）
外加 `cycle_candidates.txt` 列出候选循环点（帧号 + 脚差）。
人工发现循环不对时，按清单帧号在完整序列里自己切。
出这两版用一条命令（内部会挑片、拉平、写清单、写 action.json）：

```bash
bash pipelines/unimate/scripts/unimate-pack.sh \
    --samples outputs/samples/Dog_001 --loop-dir <循环化产物> \
    --name Dog_001 --out outputs/actions/Dog_001_pack
```

清单随时可重生成：`python pipelines/unimate/tools/cycle_candidates.py --samples <目录> --top 12`。

批量接入 + 索引：

```bash
bash pipelines/unimate/scripts/unimate-import-batch.sh --clips Arts/mixamo/rolls \
    --rig outputs/rig/X_Bot --name X_Bot --expect roll --prefix act_
python core/action_index.py
```

## 10. 改动本工程时

- 改完先跑 **冒烟测试**：`bash tests/smoke.sh`（48 项断言，约 7 秒；UniMate 解释器）。
  动了 `Motion2MixamoRig/` 再补跑一遍 m2mr 侧：
  `Motion2MixamoRig\.venv\Scripts\python.exe tests/smoke.py`（70 项，含第 7 节动补断言）。
  覆盖：关节识别、循环检测（合成周期数据）、静止保护、切循环语义、模块边界、
  动作契约字段、动作索引重名、工具可导入。
- 再跑 `bash -n`（脚本）和 `python -m py_compile`（工具）。
- 版本号只有一个来源 `VERSION`；工具里要版本就读 `pipeline_config.version()`，
  不许写死字面量（审核时抓到两处写死的，已修）。
- 失败要吵：读不到中间产物就 `exit` + 说明原因，不许回落默认值继续跑
  （`unimate-pipeline.sh` 的体检分支是范例）。
- 对上游的调用只允许出现在 `pipelines/unimate/tools/unimate_api.py`；其它文件不许 `import unimate`。
- 改循环算法去 `cycle_search.py`（找哪段），改切法去 `loop_cut.py`（怎么切），
  `make_loop.py` 只是编排层，不要往里加算法。
- 端到端回归：拿 `Arts/X Bot.fbx` 跑一次 `unimate-loop.sh`，接缝倍数应与上次一致
  （走/跑 0.6~1.3，待机走 `--close` 后 1.4~2.2）。
- **提交前先 `git status`**：只 `git add` 自己改过的文件（写显式路径，不用 `-A`）。
  这个仓库有多个会话并行改动，`-A` 会把别人未完成的改动一起提交（已经发生过两次）。
  看到不属于自己的改动就停下来问。
- 动作契约（`source` 允许值、必填字段、`loop_mode`）唯一出处是
  `core/action_schema.py`；加来源/加字段只改那里，工具与文档跟着走。
- 提交信息格式：`type: 一句话说明，vX.Y.Z.W`（type 用 feat/fix/refactor/test/docs/chore），
  版本号与 `VERSION` 一致；一次提交只做一件事。
- 版本号：字段改动 → w+1；新增能力 → z+1 并在 `CHANGELOG.md` 写清楚。