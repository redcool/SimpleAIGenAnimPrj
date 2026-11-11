# Motion2MixamoRig 专属目录

本目录是 **AIGenAnimPrj 里 m2mr 产线的全部落点**。上层引用库
`H:\aiworks\motionPrj\Motion2MixamoRig` 保持**只读**,任何改进都在这里做。

> 命令与参数的完整清单见 [`docs/动补操作手册.md`](../docs/动补操作手册.md)(配置项、命令配方、参数总表、排错)。

## 目录

```
Motion2MixamoRig/
├── tools/                     Python 实现(调用引用库,不改它)
│   ├── motion2mixamo_command.py      唯一入口:注入焦距后调用 m2mr 命令行
│   ├── ground_character_on_floor.py  按真实最低顶点把角色压到 y=0
│   ├── run_batch_captures.py         批量跑素材 + 质检判定(PASS/WARN/FAIL)
│   ├── fuse_camera_views.py          双机位轨迹融合 + 分歧报告
│   ├── camera_distance.py            距离 ↔ 焦距换算(量像素身高)
│   ├── plot_trajectory_compare.py    两次 run 的位移/高度对比图
│   ├── make_comparison_video.py      两次 run 的角色预览并排成对比 mp4
│   └── blender/
│       ├── export_character_fbx.py        glb -> 二进制 FBX(Unity 原生)
│       └── render_floor_contact_stills.py 加 z=0 地板渲染若干帧,看脚是否贴地
├── outputs/                   模块内中间产物(正式交付不放这里)
└── tmp/                       临时文件、日志、以及对引用库的补丁存档
```

## 为什么要包一层入口

上游 m2mr 没有把相机焦距透出来,而焦距是**最主要的系统性误差源**:不传时
GVHMR 按 43mm 等效镜头估算,手机主摄(约 26mm)的深度会被高估约 65%,表现为
"角色位移比实际大"。

本目录不改引用库,而是在运行时给 `gvhmr.recover` 套一层,读出环境变量后补上
`f_px` / `f_mm`。补丁内容存档在 `tmp/motion2mixamorig_focal_patch_v1.diff`
(如需改为库内实现,先 fork 引用库再合并该补丁)。

## 交付落位(2026-11-07 定)

视频动补的成品**统一放 `AIGenAnimPrj/outputs/video_cap/<cap_*>/v2` 这类目录**,
不混进 `outputs/actions/`(那里是模型产线与动作库产线的交付,契约字段不同)。

每个交付目录要有:

| 文件 | 说明 |
|---|---|
| `action.json` | 由 `core/action_meta.py` 写,`source: capture`;不要自己另写一份 |
| `mixamo_character_grounded.glb` / `.fbx` | 落地修正后的角色(Unity 用 fbx) |
| `videos/compare.mp4` | 四宫格对比 |
| `diagnostics.json` / `REPORT.md` | 质量报告 |

命名:`cap_<动作>_v<版本>`,例如 `outputs/video_cap/cap_punch_v2/`。

## 配置(先读这一节)

代码里**没有写死机器路径**。所有路径按下面顺序解析,先命中先用:

1. **环境变量**(临时覆盖,适合一次性的不同机器)
2. **`Motion2MixamoRig/config.env`**(本机配置,不入库;模板是 `config.example.env`)
3. **从当前工作目录逐级向上找**,认「含 `motion2mixamorig/` 的目录」为引用库根
4. 都找不到就**明确报错并打印配置方法**,不回落假路径

| 配置项 | 含义 | 缺省 |
|---|---|---|
| `MOTION2MIXAMO_HOME` | 引用库根目录(只读) | 由 1/3 步解析 |
| `MOTION2MIXAMO_PYTHON` | 跑引用库的解释器 | `<HOME>/.venv/Scripts/python.exe` |
| `MOTION2MIXAMO_ASSETS_VIDEO` | 素材目录 | `assets/video`(相对 HOME) |
| `MOTION2MIXAMO_DEFAULT_RIG` | 默认角色 FBX | `assets/mixamo/X_Bot.fbx` |
| `MOTION2MIXAMO_OUTPUT_ROOT` | 交付根 | 主工程 `outputs/video_cap` |
| `MOTION2MIXAMO_FOCAL_PIXELS` | 相机焦距(像素) | 空 = 上游按 43mm 启发式 |
| `MOTION2MIXAMO_DISTANCE_METRES` | 人到相机的距离(米) | 空;给了就反推焦距 |
| `MOTION2MIXAMO_PERSON_HEIGHT_METRES` | 画面里人的真实身高(米) | `1.70` |
| `BLENDER_EXECUTABLE` | Blender | `blender`(走 PATH) |

自检:`python tools/motion2mixamo_config.py` 会打印当前解析结果。

## 尺度怎么给(焦距 or 距离)

GVHMR 的**绝对深度由焦距决定**;不给焦距时它按 ~43mm 等效镜头估,
手机主摄(约 26mm)的深度会被高估约 65% —— 表现为"角色位移比实际大"。
朝向、姿势形状不受影响,所以我们量的 60.1cm 骨盆→头距离始终一致。

三种给法,优先级从高到低:

| 给什么 | 怎么做 | 说明 |
|---|---|---|
| **焦距** | `--focal-pixels 1387` | 最直接;手机主摄 26mm @1920 宽 ≈ 1387 |
| **距离** | `--distance 3.4 --person-height 1.75` | 本入口用 YOLO 量像素身高,按 `焦距 = 像素身高 × 距离 ÷ 真人身高` 反推 |
| 都不给 | — | 上游启发式,只适合"只要动作、不管位移"的场合 |

`--distance` 只是入口层的便利参数,底层仍然注入 `f_px`(引用库一行没改)。

## 环境变量

| 变量 | 作用 |
|---|---|
| `MOTION2MIXAMO_FOCAL_PIXELS` | 相机焦距(像素),优先 |
| `MOTION2MIXAMO_FOCAL_MILLIMETRES` | 等效焦距(mm),由上游换算 |

像素换算:`f_px = 等效焦距mm × 画面宽px ÷ 36`(iPhone 主摄 26mm @1920 → 1387)。

## 常用命令

全部用引用库的 venv 解释器:
`H:\aiworks\motionPrj\Motion2MixamoRig\.venv\Scripts\python.exe`

```powershell
# 1) 单条:注入焦距 + 出预览
$env:MOTION2MIXAMO_FOCAL_PIXELS = 1387
python tools\motion2mixamo_command.py run --video <片>.mp4 --device cuda --output-dir outputs\<名>\v2

# 2) 落地修正(必跑;批量里已自动执行)
python tools\ground_character_on_floor.py outputs\<名>\v2

# 3) 批量 + 质检
python tools\run_batch_captures.py --videos <目录> --focal-pixels 1387

# 4) 双机位融合
python tools\fuse_camera_views.py fused.npz cam1.npz cam2.npz --scale

# 5) 出 FBX(Unity)
& 'H:\Program Files\blender-5.2.0-windows-x64\blender.exe' -b --factory-startup ^
  --python tools\blender\export_character_fbx.py -- ^
  outputs\<名>\v2\mixamo_character_grounded.glb outputs\<名>\v2\mixamo_character.fbx 30
```

## 判定阈值(批量里的质检门禁)

| 判定 | 条件 |
|---|---|
| FAIL | 穿模帧 ≥15%,或最深 ≥8cm,或脚锁修正 ≥30cm |
| WARN | ≥5% / ≥5cm / ≥15cm |
| PASS | 其余 |

依据:合格素材(punch)穿模 3.4%、脚锁 2.9cm;不合格素材(裁剪片)穿模 47%、脚锁 29.6cm。

## 边界

- 引用库 `Motion2MixamoRig` 不接收本条线任何修改;升级它不影响本目录。
- 本目录的产物不入库(outputs/ 与 tmp/ 已在 .gitignore 内)。
