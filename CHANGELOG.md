# 变更记录

版本号规则（见 Agent工作纪律.md 第 6 条）：
x 世代版本（人手）、y 大版本（人手）、z 大功能（agent 可动）、w 小改动（agent 可动）。

## 1.0.5.9

动补产线出**操作手册**,并把 punch 的 v3 升为正式条目。

- 新增 `docs/动补操作手册.md`:配置项全表、**尺度怎么给**(焦距/距离/启发式 + 针孔换算)、
  9 个可直接抄的命令配方、每个工具的参数总表、交付契约字段、排错表、已知边界。
  `Motion2MixamoRig/README.md` 顶部加了指向它的链接。
- `outputs/video_cap/cap_punch_v3/`:补齐 `action.json`(`name=cap_punch`, 当前版本)、
  `mixamo_character_grounded.glb/.fbx`(落地 937 帧陷地 → 0)。
  原 v2 改为 `name=cap_punch_v2` 作对照;索引现在有两条 capture:
  `cap_punch`(v3,脚锁 13.4cm)与 `cap_punch_v2`(脚锁 16.8cm)。

验证:`action_index.py` 的 `capture=2`;`tests/smoke.py` 73 通过 / 0 失败。

## 1.0.5.8

补两个对照用的辅助工具,并首次出 **v2/v3 并排对比视频**。

- `Motion2MixamoRig/tools/plot_trajectory_compare.py`:读两次 run 的 `skeleton_motion.npz`,
  画俯视轨迹(世界 XZ)与髋部高度随时间,标注各自位移;标签用英文(matplotlib 默认字体无中文字形)。
- `Motion2MixamoRig/tools/make_comparison_video.py`:把两次 run 的 `mixamo_character.mp4`
  并排合成一个 mp4,标签用 PIL 预生成 PNG 再 overlay —— 避开 Windows 下 ffmpeg drawtext
  字体路径的冒号转义坑。
- 实测(punch.mp4,75.3s):启发式焦距 travel **0.62m** / 脚锁 2.94–16.77cm / 穿模 77 帧;
  按距离 3.4m 反推焦距(~1481px)travel **0.50m** / 脚锁 2.38–13.39cm / 穿模 88 帧、最深 5.39cm。
  产物:`outputs/video_cap/cap_punch_v3/{compare_v2_v3.mp4,trajectory_compare.png}`。
- AGENTS §10 里 m2mr 侧冒烟条数 61 → 70。

## 1.0.5.7

动补尺度:**可以让用户直接给"人到相机的距离"**,不必知道焦距。

- 背景:GVHMR 的绝对深度由**焦距**决定;没给焦距时按 ~43mm 等效估,手机主摄
  (约 26mm)的深度会高估约 65%(实测同一段片子:给 f_px=1400 世界位移 32.6cm,
  启发式 45.8cm;而骨盆→头的 60.1cm 不变 —— 焦距只影响位移/深度,不影响姿势)。
- 新增 `Motion2MixamoRig/tools/camera_distance.py`:用 YOLO 量画面里人的像素身高 s,
  按 `f_px = s × 距离 ÷ 真人身高` 反推焦距。
- 入口 `motion2mixamo_command.py` 新增参数(委派前摘掉,不污染 m2mr CLI):
  `--distance <米>`、`--person-height <米,默认 1.70>`、`--focal-pixels <px>`。
  优先级:**焦距 > 距离 > 启发式**;两者都没有会明确告警。
- 配置键新增 `MOTION2MIXAMO_DISTANCE_METRES`、`MOTION2MIXAMO_PERSON_HEIGHT_METRES`。
- 冒烟第 7 节新增 4 项:换算数值、线性关系、非法参数报错;总数 61 → **70**。
- 文档:`Motion2MixamoRig/README.md` 增"尺度怎么给(焦距 or 距离)"一节。

实测(punch 8 秒段):像素身高 747.7px(5 帧中位数)→ 距离 3.40m / 身高 1.75m
→ 焦距 **1453 px** → 注入后 foot lock 1.4/7.3cm,跑通。

## 1.0.5.6

两件事:§10 补一条协作约定;动补落地测量**向量化**,并加一个可选的慢测入口。

- `AGENTS.md` §10 补**提交信息格式**:`type: 一句话说明，vX.Y.Z.W`(feat/fix/refactor/test/docs/chore),
  一次提交只做一件事。(git status 先看、只 add 自己文件、不用 `-A`、契约出处 `core/action_schema.py`
  这几条上一版已存在,本次未重复添加。)
- `Motion2MixamoRig/tools/ground_character_on_floor.py`:`measure_lowest_vertex_per_frame`
  改为**按帧块向量化**(默认 32 帧/块,只算插值后的 y 一行,不构造完整 (顶点,4,4) 矩阵)。
  实测 cap_punch_v2(2259 帧):**11.9s → 4.3s(2.7 倍)**,与参考实现逐帧偏差 **0.00000 mm**。
  中途踩坑:第一版用 `rows[..., :3] @ positions.T` 做成了 (V,V) 矩阵乘,已改为
  `np.einsum("fvj,vj->fv", ...)` 并加注释。
- 新增 `tests/slow.py`(手动跑,不进 smoke):在真实 GLB 上对照向量化实现与逐帧完整蒙皮,
  断言逐帧偏差 < 1 微米、无穿地帧,并打印两个实现的耗时。缺 GLB 或换了解释器则整体跳过。

验证:`python tests/slow.py` → 3 通过 / 0 失败(偏差 0.00000 mm,2.7 倍);
`tests/smoke.py`(m2mr)61 通过、`bash tests/smoke.sh`(UniMate)48 通过,均 0 失败。

## 1.0.5.5

动补产线补**自动化测试**(审核遗留 P1-7),并修掉测试暴露的一个真 bug。

- `tests/smoke.py` 新增第 7 节"动补工具",13 项断言:
  · 落地偏移:着地帧最低点归零、任何帧不穿地、`--always-ground` 每帧贴地;
  · GLB 读写往返 + Hips translation 通道定位(字节偏移/步长/分量数)+ 写回偏移量;
  · 机位融合:25° 旋转 + 1.08 缩放的合成点云能被拟合回来(残差 2.7e-15),恒等输入给单位变换;
  · 动补契约:`capture` 合法、未知来源被拒。
- 修复真 bug:`ground_character_on_floor.py` 的 `read_glb` / `write_glb` 原来只接受 Path,
  传字符串会在 `path.write_bytes` 处 AttributeError。现在两个入口都接受 `str | Path`。
- 冒烟增加**环境跳过**:动补工具需要 m2mr 的解释器(numpy + 引用库),在 UniMate 环境里
  第 7 节打印 `[skip]` 与正确跑法,不记 FAIL —— 否则 UniMate 侧冒烟会长期红。
- AGENTS §10 补两行:两套解释器怎么各跑一遍冒烟。

验证:`Motion2MixamoRig\.venv\Scripts\python.exe tests\smoke.py` → **61 项通过 / 0 失败**;
`bash tests/smoke.sh` → **48 项通过 / 0 失败**(第 7 节跳过)。

## 1.0.5.4

动补产线**去硬编码**:路径改配置驱动(审核发现 3 处写死 `H:\aiworks\motionPrj\Motion2MixamoRig`)。

- 新增 `Motion2MixamoRig/tools/motion2mixamo_config.py`:统一解析路径与可执行文件,
  顺序为 **环境变量 > Motion2MixamoRig/config.env > 从当前工作目录逐级向上找(认含 motion2mixamorig/ 的目录)
  > 明确报错**。不再回落到假路径;找不到时打印三种配法。
- 新增 `Motion2MixamoRig/config.example.env`(模板,入库)与 `config.env`(本机,不入库)。
  可配:`MOTION2MIXAMO_HOME / _PYTHON / _ASSETS_VIDEO / _DEFAULT_RIG / _OUTPUT_ROOT / _FOCAL_PIXELS`、`BLENDER_EXECUTABLE`。
  自检命令:`python tools/motion2mixamo_config.py`。
- `run_batch_captures.py`:
  · 默认交付根改为 `outputs/video_cap`(原 `outputs/motion2mixamo/batch` 与新约定不符);
  · 新增 `--device`(原来写死 cuda)与 `--python`(默认取配置,并校验存在,缺了就报错不猜);
  · 批量报告改落 `outputs/video_cap/_batch_reports/`,不再与动作目录混放;
  · 启动时打印"引用库 / 解释器 / 设备 / 交付根"四行,便于核对。
- `ground_character_on_floor.py`、`fuse_camera_views.py`:改为经 config 导入引用库。
- `motion2mixamo_command.py`:没提供焦距时**明确告警**(世界尺度按 43mm 估算),不再静默。
- 文档:`Motion2MixamoRig/README.md` 增加"配置"一节(解析顺序 + 配置项表)。

验证:`bash tests/smoke.sh` 42 项全通过;五个工具 `py_compile` 通过;
配置在三种启动目录下解析正确(工程根 / 系统临时目录 / 引用库子目录);
批量冒烟(8 秒片)按默认配置跑通并判 PASS。

## 1.0.5.3

审核后 P1 两项。

- **拆 `make_loop.py`**（原 470 行、12 个参数、混了四件事）：
  - `cycle_search.py`（236 行）：找周期。`CycleOptions` / `CycleChoice` 两个数据类，
    `choose_cycle()` 收敛"按脚 / 按旋转 / 静止保护 / 候选打分"四种决策。
  - `loop_cut.py`（126 行）：切片段。`cut_loop` / `seam_metrics` / `foot_seam` / `loop_verdict`。
  - `make_loop.py`（228 行）：只剩 CLI 与报告；旧名字（`make_loop`、`find_cycle_feet` 等）
    仍从这里导出，外部调用与测试不用改。
  验证：同一批 Dog 采样，重构前后 `loop_report.json` **逐字段一致**（唯一允许的差异见下条）。
- **`foot_seam_ratio` 语义修正**：整段收拢（head-hold）时首尾被强行拉平，原值恒为 0.0，
  读起来像"接缝完美"。现在返回 `null`，判定文案由 `loop_mode` 说明是"停一帧"。
- 冒烟测试扩到 **42 项**：新增切循环语义（周期模式 / 收拢模式 / 脚接缝为 null）、
  判定优先级（脚差太多优先报警）、拆分后的模块边界（`cycle_search` 不依赖 `loop_cut`、
  `loop_cut` 不负责找周期、`make_loop` 仍导出旧名）。
- AGENTS §10 补一条：改算法去 `cycle_search.py`，改切法去 `loop_cut.py`，
  `make_loop.py` 只做编排。

## 1.0.5.2

代码审核后补 P0 三项（审核报告见会话记录）。

- **新增冒烟测试** `tests/smoke.py` + `tests/smoke.sh`：26 项断言，约 5 秒。
  覆盖关节识别（Mixamo / 四足 / 鸟）、循环检测（合成周期 20 帧）、静止保护、
  动作契约字段、动作索引重名检测、工具可导入。测试当场抓出一个语义问题：
  两足与鸟类都被归为"后肢"，已在 `rig_joints.py` 文档里写明（行为不变）。
- **版本号统一**：`unimate-import-clip.sh` 里写死的 "1.0.1.0" 改为读 `VERSION`；
  `add_root_spin.py` 里写死的 "1.0.0.6" 改为 `pipeline_config.version()`。
- **禁止静默失败**：`unimate-pipeline.sh` 体检读不到关节数、精简后读不到输出文件时
  直接 `exit 4/5` 并说明怎么单独复查，不再回落成 -1 继续跑。
  已用假 FBX 实测：输出"体检失败：读不到关节数…"并返回 4。
- AGENTS 第 10 节与操作手册加入"改完先跑 `bash tests/smoke.sh`"。

## 1.0.5.1

视频动补的交付落位与契约对齐(用户 2026-11-07 定:动补成品放**动补自己的目录**)。

- 新增约定:视频动补交付放 `outputs/video_cap/<cap_*>/v2`,不混进 `outputs/actions/`。
  理由:actions 下是模型与库两条产线的交付,质量语义是循环接缝/四肢幅度;
  动补的语义是自穿插/脚锁/落地,混在一起索引表读不出重点。
- `core/action_meta.py`:`--source` 增加 **`capture`**(视频动补),新增 `--capture-run`,
  从 `run.json` + `diagnostics.json` 填 qa(帧数、fps、穿模帧与占比、最深、脚锁均/最大、是否已落地)。
  动补不写循环接缝字段。
- 首个交付:`outputs/video_cap/cap_punch_v2/`(punch.mp4 → X_Bot)。
  `action_index.py` 已收录,`by_source` 变为 capture=1 / library=10 / model=9。
- `core/action_index.py`:qa_of() 认识 motion_capture(显示 穿模占比/最深/脚锁),
  帧列在顶层缺失时回落到 qa.frames。索引行现在读作
  cap_punch | capture | X_Bot | 2259 | 否 | 否 | 穿模 3.4% / 最深 5.5cm / 脚锁 16.8cm。
- 文档:`Motion2MixamoRig/README.md` 补"交付落位"一节。

## 1.0.5.0

新增 **m2mr(视频动补)产线**，落点 `Motion2MixamoRig/`（AIGenAnimPrj 专属子目录）。
引用库 `H:\aiworks\motionPrj\Motion2MixamoRig` 保持只读，改动一律在本工程内以包装层实现。

- `tools/motion2mixamo_command.py`：唯一入口。运行时给 `gvhmr.recover` 套一层注入相机焦距
  （`MOTION2MIXAMO_FOCAL_PIXELS` / `MOTION2MIXAMO_FOCAL_MILLIMETRES`）。上游不透出焦距，
  按 43mm 等效估深度会高估约 65%。同时修正了一个顺序坑：必须先导出 `GVHMR_BODY_MODELS`
  再 import gvhmr，否则会去 site-packages 找体模而报 "body model not found"。
- `tools/ground_character_on_floor.py`：按 GLB 自身蒙皮逐帧算**全部顶点**最低 y，着地帧压到 0、
  非着地帧插值并夹紧不低于 0。实测 punch 片：陷地 952 帧 → 0 帧，最低点恒为 0。
- `tools/run_batch_captures.py`：批量跑素材 + 质检门禁（FAIL 穿模≥15% 或最深≥8cm 或脚锁≥30cm），
  出 markdown + csv 报告，落地修正自动串在其中。
- `tools/fuse_camera_views.py`：双机位融合。姿态（root-relative Procrustes）与根轨迹分开拟合，
  报告拆 `pose_rms_cm` / `root_rms_cm`。自测：恒等 0.00cm；模拟第二机位能还原缩放 0.9237（真值 0.9259）。
- `tools/blender/`：glb → 二进制 FBX（Unity 原生导入）；带 z=0 地板的落地对照渲染。
- 对引用库焦距补丁存档于 `Motion2MixamoRig/tmp/motion2mixamorig_focal_patch_v1.diff`
  （如需并入库内实现，先 fork 引用库）。

依据：合格素材 punch 穿模 3.4% / 脚锁 2.9cm；不合格素材（2×2 合成片裁剪）穿模 47% / 脚锁 29.6cm。

## 1.0.4.6

- **完整序列也做原地化**：`full/` 默认给原地版（`*_full.fbx`），带根位移的原版保留为
  `*_full_motion.fbx`。实测首尾水平位移 Tiger run 0.779 → 0.034、Dog run 0.262 → 0.005、
  Horse walk 0.096 → 0.014（Tiger/Horse 的 walk/run 是 160 帧长序列）。
- 新增 `docs/目录重构方案.md`：按能力分目录（core / pipelines/{unimate,library,m2mr}），
  并指出一个命名坑——内部目录别叫 `UniMate`，会和外部只读的上游仓库 `UNIMATE_HOME` 混淆。
- 用户反馈 Horse 的循环动作可接受；Tiger/Horse 的 walk 与 run 仍以完整序列 + 候选帧号为准。

## 1.0.4.5

按用户要求：**每个循环动作出两版**，供人工在完整序列里自己找循环。

- 交付包结构改成 `anim/`（循环处理版）+ `full/`（未处理的完整序列）。
- Tiger / Horse 的 walk、run 用 `motion_expand` 串 3 段做成 **160 帧**完整序列
  （60 帧常放不下一个完整周期，人工也难找"两帧相同"）；其余仍是 60 帧。
- 新增 `tools/cycle_candidates.py`：列出一条动作的候选循环区间（起点/结束帧号、
  脚差、相当于几倍步长），写进每个包的 `full/cycle_candidates.txt`，
  人工可直接按帧号切。
- 用户反馈 Tiger/Horse 的 idle 正常、walk/run 不正常，已按此重构交付，不再假装循环可用。

Tiger / Horse 的循环问题：按用户要求只走生成路线（多采 + 加长），不碰手 K。

- 多采 8 条：Tiger 只出 8 帧假周期（短窗口里脚本来就不动），Horse 17 帧但接缝 1.7。
- **加长时长**（`motion_expand` 串 3 段 = 160 帧）：Tiger 出 21 / 41 帧周期，
  接缝 0.72；Horse 出 17 / 37 帧周期，接缝 0.46 —— 两个交付包已换成加长路线的版本。
  结论：60 帧常常放不下一个完整周期，串到 160 帧周期与接缝才落得下来。
- `make_loop.py` 增加**行程约束**（`--min-foot-travel 0.55`）：一个周期内脚必须走过
  脚的行程 55% 以上，否则短窗口的"两帧相同"是白送的，会挑出 8 帧假周期。
- 记录一个度量冲突：加长路线选的周期偏短（21 / 17 帧），脚接缝很好但旋转接缝指标不同意，
  已在 docs/动物动作交付.md 写明，交给目视确认。

## 1.0.4.3

修循环检测：四足动画的周期必须按**脚**找，不能按全身姿态。

- 新增按四肢末端轨迹的周期搜索（`--basis feet`，能认出四肢时默认启用）：
  在整段里找两帧"几只脚几乎相同"，前一帧当起点、后一帧当终点；
  判定用**脚的行程比例**（`--foot-tolerance 0.12`）而非绝对距离，大小体型通用；
  达标候选里再挑"末帧到首帧最接近正常步长"的一条。
- 静止保护：脚几乎不动（待机）时不切周期，避免切成几帧的假循环。
- 报告新增 `basis` / `foot_seam_ratio` / `foot_period_error` / `feet`；
  脚接缝 >1.4 时判定直接写"接缝处脚差了几倍步长"，不再被旋转接缝掩盖。
- 抽出 `tools/rig_joints.py`（四肢识别），gait_report 与 make_loop 共用，
  并让两个工具都能直接运行（不必设 PYTHONPATH —— 之前 loop 脚本没设，
  导入失败后静默退回按旋转，正是这次问题的根因之一）。
- 实测 77 条动作：真实周期 1 → **21 条**，接缝 ≤1.1 的 1 → **12 条**；
  Dog 跑步从"整段收拢"变成接缝 0.52 的真循环，交付包已按新接缝重挑。

## 1.0.4.2

7 个 Unity Store 动物模型全部跑了一遍产线（idle/walk/run 各 3 次采样），按指标挑片并打包交付。

- 交付：`outputs/actions/<模型>_pack/`（角色 FBX + idle/walk/run + action.json），
  共 7 个包；索引现有 19 条动作（10 library + 9 model）。
- 结果：**Dog / Tiger 出成型袭步**（左右 +0.77 / +0.83）；Deer / Horse / Kitty / Pinguin
  腿在动但步态不标准（run 腿部幅度 0.04~0.25），需看视频定；
  **Chicken 生成失败**（腿部幅度仅 0.002~0.006，翅膀在动腿不动），
  已回退到它自带的 idle/walk/run（`builtin/`）。
- 修 `tools/gait_report.py` 的脚关节选择：原来把翅膀/鳍当"前脚"（鸡被判成前脚是 Wing），
  改为**腿脚类名字优先**，一条腿都找不到时才退到翅膀/手。
- 新增 `docs/动物动作交付.md`：结果总表、包结构、Unity 导入、挑选规则、已知问题。

## 1.0.4.1

- 体检用户新放的 Unity Store 动物包（Chicken/Deer/Dog/Horse/Kitty/Pinguin/Tiger）：
  20~45 关节、单 armature、蒙皮完整、骨名规范、自带动画，规则标签 **0 flag**。
  Dog 端到端跑通：run 4 条里 1 条成型袭步（左右 +0.94），待机幅度 0.0013 正确。
- 修 `tools/gait_report.py` 判定顺序 bug：幅度很小的动作（待机）会被硬套成
  "袭步/跳跃式"，现在先判幅度（<0.012 归为待机级别），再谈相位。
- AGENTS 5.5.1 补充这个动物包的实测结果与唯一注意点（前腿是机器人式 Front Thigh 命名）。

## 1.0.4.0

用户提供 3 个 GLB 模型（羊驼 / 狗 / 锦鲤），逐个体检后按能力分流。

- **羊驼**（43 关节、有蒙皮）：待机可用；跑步不合格 —— 四种 prompt × 两个权重
  （通用 + 新下载的动物专用 `unimate_truebones_f60_v2`）都是**四条腿同相 +0.93~1.00**，
  即整体弹跳而非步态。已按四足规范手工改标签（前腿→Shoulder/Upper Arm/Forearm，
  后腿→Thigh/Shin/Foot）重试，仍不成型。交付目录 `outputs/actions/alpaca_delivery/`。
- **狗 / 锦鲤**：**没有骨架**（dog 6 节点 0 skin；koi 只有 MorphBake 形变动画），
  无法生成动作，需要先绑定。
- `tools/gait_report.py` 脚关节识别改成「每侧每前后肢取链条最深的那根」，
  兼容 FrontLowerLeg / Hoof / Paw 这类命名。
- AGENTS.md 新增 5.5.1：动物骨架的实测边界（Fox 22 关节能出步态，alpaca 43 关节退化成弹跳）。
- 权重表补动物专用 `unimate_truebones_f60_v2`（5~85 关节，730 MB）。

## 1.0.3.0

动作库真正跑起来 + 目录收敛 + 操作手册。

- **动作目录收敛**：新增 `outputs/actions/<动作>/` 作为**交付物**位置
  （每个目录含 `action.json`），`outputs/samples/` 降级为采样中间产物。
  已迁移 2 个动作；`_env.sh` 导出 `ACTIONS_HOME`，两条产线默认写到这里。
- **批量接入 10 条 Mixamo 片段**（用户提供的 `Arts/mixamo/`）：翻滚 ×3、受击 ×3、
  倒地/死亡 ×2、起身 ×2，**10/10 通过质量闸门**，其中三条验证为真翻滚
  （484°/437°/446°）。索引表已更新为 11 条动作（10 library + 1 model）。
- **来源优先级写进规范**：先试模型，做不出/做不好再走库；库是候选不是默认；
  交付必须在 `action.json` 标 `source`/`origin`，索引表直接可见。
- 新增 `docs/操作手册.md`：五个场景（新角色出整套动作 / 补单条库动作 / 补一批 /
  盘点索引 / 判断该不该走库），每个都有命令 + 验收 + 失败处理，照着做即可。
- `tools/action_index.py` 增加**内容重复检测**（同角色、同帧数、同动作指标），
  靠它发现并清掉了重复导入的 `act_sprinting_forward_roll`。
- 修 `unimate-import-batch.sh` 两个 bug：`${DRY:+--dry-run}` 对 `DRY=0` 也会展开
  （导致整批只跑 dry-run）；`ok=${ok+1}` 不是算术（计数永远是 0/1）。
- 修 `unimate-import-clip.sh` 的默认输出目录与 `--action` 推导顺序。

## 1.0.2.0

动作攒起来之后的三件配套：能盘点、能批量、知道还缺什么。

- 新增 `tools/action_index.py`：扫 outputs/ 下所有 `action.json`，输出
  `actions_index.md/.json`（名字/来源/角色/帧数/循环/原地/质检/目录），
  并报重名、文件缺失、质检不通过。
- 新增 `scripts/unimate-import-batch.sh`：给一个片段目录，逐个跑产线 B，
  汇总成功/失败并列出失败清单；失败返回非零退出码。
- 新增 `docs/待补动作清单.md`：按 P0~P3 列出模型做不好的动作族与推荐的
  Mixamo 关键词，并明确"哪些不要用库"（走跑待机、舞蹈、动物运动——模型能给随机变体）。
- README / AGENTS 补入口。

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