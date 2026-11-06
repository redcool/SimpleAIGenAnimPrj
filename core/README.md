# core —— 跨来源共用的底座

这里放**不依赖任何一条产线**的东西。任何一条产线（UniMate 抽卡、动作库接入、动补重定向）
都可以用，也都必须用同一份，避免各写一套。

| 文件 | 职责 |
|---|---|
| `env.sh` | 读 `config.env`、导出绝对路径与目录变量、提供 `from_project` / `abs_path` |
| `pipeline_config.py` | Python 侧的同一套配置与版本号（唯一来源 `VERSION`） |
| `action_meta.py` | 写动作契约 `action.json`（source / origin / loopable / in_place / qa / files） |
| `action_index.py` | 扫 `outputs/` 生成动作索引，并报重名、文件缺失、质检不通过、内容重复 |

## 目录变量（`env.sh` 导出）

| 变量 | 指向 | 说明 |
|---|---|---|
| `PIPELINE_HOME` | 仓库根 | 所有相对路径按它解析 |
| `CORE_HOME` | `core/` | 本目录 |
| `UM_PIPELINE` | `pipelines/unimate/` | 抽卡产线 |
| `UM_SCRIPTS` | `pipelines/unimate/scripts/` | 脚本入口 |
| `UM_TOOLS` | `pipelines/unimate/tools/` | 工具实现 |
| `UNIMATE_HOME` | **外部上游仓库** | 只读依赖，不是本工程的子目录 |
| `ACTIONS_HOME` | `outputs/actions` | 交付物 |
| `SAMPLES_HOME` / `RIGS_HOME` | `outputs/samples` / `outputs/rig` | 中间产物 |

`TOOLS` 是旧名字，仍指向 `UM_TOOLS`，只为兼容老脚本。

## 规矩

1. 这里**不许 import 任何产线的代码**（不能反向依赖 `pipelines/`）。
2. 动作契约只有一份，改字段要同步 `docs/动作产线规范.md`。
3. 新增产线时，先看这里有没有能复用的东西，别另起一份配置解析。
