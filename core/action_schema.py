#!/usr/bin/env python3
"""动作契约的唯一出处：action.json 允许有哪些字段、source 有哪几种。

为什么需要：source 的取值原本散在三处（action_meta 的 choices、docs 的表格、
action_index 的统计），加一个 capture 就要改三个地方，漏一处就出现
"写进去能过、索引认不出"的怪现象。

这里只放**定义**和**校验**，不碰文件读写：
    SOURCES / LOOP_MODES / REQUIRED_FIELDS / OPTIONAL_FIELDS / validate()
"""

from __future__ import annotations

KIND = "action"

# 动作来源。新增来源时只改这里，action_meta / action_index / 文档跟着走。
SOURCES = {
    "model": "UniMate 模型生成（抽卡）",
    "library": "动作库片段接入（Mixamo 等）",
    "hybrid": "模型生成 + 程序处理（例如补根骨旋转）",
    "capture": "动补/视频重定向（Motion2MixamoRig）",
}

# 循环模式：periodic = 真的切出了一轮；head-hold = 没找到周期，整段收拢（接缝处停一帧）
LOOP_MODES = ("periodic", "head-hold")

# 命名前缀只作提示，不强制（历史资产已经存在，改名成本高于收益）
NAME_PREFIX_HINTS = {
    "gen_": "模型生成",
    "lib_": "库片段直接接入",
    "act_": "关键动作（业务语义，多为库）",
    "loc_": "位移循环（走/跑/爬行）",
    "cap_": "动补",
}

REQUIRED_FIELDS = ("kind", "version", "name", "source", "in_place", "files")


def validate(meta: dict) -> list:
    """检查一份 action.json，返回问题描述列表（空列表 = 合格）。

    只报能确定的问题：缺字段、source 不认识、类型不对。
    不断言"必须有 origin"这类业务偏好，免得把历史资产判死。
    """
    problems = []

    for field in REQUIRED_FIELDS:
        if field not in meta:
            problems.append("缺字段 %s" % field)

    if meta.get("kind") not in (None, KIND):
        problems.append("kind 应为 %r，实际 %r" % (KIND, meta.get("kind")))

    source = meta.get("source")
    if source is not None and source not in SOURCES:
        problems.append("source=%r 不在允许值 %s" % (source, sorted(SOURCES)))

    if "in_place" in meta and not isinstance(meta["in_place"], bool):
        problems.append("in_place 应为布尔值，实际 %r" % (meta["in_place"],))

    files = meta.get("files")
    if files is not None and not isinstance(files, list):
        problems.append("files 应为列表，实际 %r" % (type(files).__name__,))

    loop_mode = meta.get("loop_mode")
    if loop_mode is not None and loop_mode not in LOOP_MODES:
        problems.append("loop_mode=%r 不在 %s" % (loop_mode, list(LOOP_MODES)))

    return problems


def describe() -> str:
    """给人看的一行摘要，供 --help 或文档生成用。"""
    return "source ∈ {%s}" % " | ".join(SOURCES)
