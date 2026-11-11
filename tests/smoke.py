#!/usr/bin/env python3
"""冒烟测试：验证核心逻辑没被改坏。

为什么需要：这套产线之前只有手工回归，改一处要人肉跑十几分钟命令。
这里把"能自动判定的部分"固定下来，改动后跑一遍即可。

跑法：
    python tests/smoke.py            # 全跑，失败返回非零
    bash tests/smoke.sh             # 同上（会自动找对解释器）

测什么：
    1. 关节识别：Mixamo 骨名、四足骨名、鸟类（无腿只有腿骨）都能认出四肢
    2. 循环检测：合成一段周期 20 帧的动作，find_cycle_feet 要找到 20
    3. 静止保护：几乎不动的一段，foot_range 很小，不能报出周期
    4. 动作契约：action_meta 写出的字段齐全、版本号来自 VERSION
    5. 动作索引：能扫到刚写的 action.json，并报重名
    6. 工具可导入：各工具模块 import 不报错
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "core"))
sys.path.insert(0, os.path.join(ROOT, "pipelines", "unimate", "tools"))

import numpy as np  # noqa: E402

PASS, FAIL = [], []


def check(name: str, condition: bool, detail: str = "") -> None:
    """记一条断言结果，不抛异常，最后统一汇总。"""
    if condition:
        PASS.append(name)
        print("  [ok]   %s %s" % (name, detail))
    else:
        FAIL.append(name)
        print("  [FAIL] %s %s" % (name, detail))


def test_limbs() -> None:
    print("\n1) 关节识别")
    from rig_joints import find_limbs

    mixamo = ["mixamorig:Hips", "mixamorig:LeftUpLeg", "mixamorig:LeftLeg",
              "mixamorig:LeftFoot", "mixamorig:LeftToeBase",
              "mixamorig:RightUpLeg", "mixamorig:RightLeg", "mixamorig:RightFoot",
              "mixamorig:RightToeBase"]
    feet = find_limbs(mixamo)
    # 两足/鸟的双腿一律归"后肢"（见 rig_joints 文档），这里只要求认出两条、左右各一
    sides = {label[-1] for label in feet}
    check("Mixamo 认出左右两条腿", len(feet) == 2 and sides == {"左", "右"}, str(feet))

    dog = ["spine.004", "front_toe.L", "front_toe.R", "toe.L", "toe.R", "thigh.L", "thigh.R"]
    feet = find_limbs(dog)
    check("四足认出四只脚", len(feet) == 4, str(list(feet)))

    chicken = ["spine", "Wing.L", "Wing.R", "toe.L", "toe.R"]
    feet = find_limbs(chicken)
    check("鸟优先用腿不用翅膀",
          "后左" in feet and "后右" in feet and "Wing.L" not in str(feet), str(feet))


def test_cycle_feet() -> None:
    print("\n2) 循环检测（合成数据，周期 20 帧）")
    from make_loop import find_cycle_feet, foot_range, foot_step

    frames, joints = 80, 6
    x = np.zeros((frames, joints, 12), dtype=np.float32)
    t = np.arange(frames)
    for j in range(joints):                      # 每根骨都按 20 帧周期摆动
        x[:, j, 0] = 0.3 * np.sin(2 * np.pi * t / 20.0 + j * 0.3)
        x[:, j, 2] = 0.2 * np.cos(2 * np.pi * t / 20.0 + j * 0.3)
        x[:, j, 3] = 1.0                         # rot6 占位
    feet = {"后左": 0, "后右": 1, "前左": 2, "前右": 3}
    start, period, err, verr, cands = find_cycle_feet(
        x, feet, 8, 60, start_max=None, min_travel=0.55 * foot_range(x, feet))
    check("找到周期", period == 20, "period=%d start=%d" % (period, start))
    check("有候选表", len(cands) > 0, "%d 个" % len(cands))

    print("\n3) 静止保护（几乎不动的一段不应报周期）")
    still = np.zeros((60, joints, 12), dtype=np.float32)
    still[:, :, 0] = np.linspace(0, 0.001, 60)[:, None]
    check("脚位移极小", foot_step(still, feet) < 0.002,
          "%.5f" % foot_step(still, feet))
    check("行程极小", foot_range(still, feet) < 0.01,
          "%.5f" % foot_range(still, feet))


def test_loop_cut() -> None:
    print("\n2b) 切循环与判定（拆分后的 loop_cut）")
    from cycle_search import CycleOptions, choose_cycle
    from loop_cut import cut_loop, foot_seam, loop_verdict

    frames, joints = 80, 6
    x = np.zeros((frames, joints, 12), dtype=np.float32)
    t_axis = np.arange(frames)
    for j in range(joints):
        x[:, j, 0] = 0.3 * np.sin(2 * np.pi * t_axis / 20.0 + j * 0.3)
        x[:, j, 3] = 1.0
    feet = {"后左": 0, "后右": 1, "前左": 2, "前右": 3}

    choice = choose_cycle(x, feet, CycleOptions(basis="feet"))
    check("choose_cycle 找到周期", choice.period == 20 and choice.cyclic,
          "period=%d cyclic=%s" % (choice.period, choice.cyclic))

    # 真实调用是"先用整段搜到周期，再把整段交给 cut_loop"，period < T 才是周期模式
    looped, info = cut_loop(x, choice.period, 4, True)
    check("切出的帧数=周期", looped.shape[0] == 20, str(looped.shape))
    check("模式是 periodic", info["mode"] == "periodic", info["mode"])

    # 待机（整段收拢）时脚接缝必须是 None，不能是 0.0（0.0 会被读成"完美"）
    still = np.zeros((60, joints, 12), dtype=np.float32)
    hold, hinfo = cut_loop(still, 60, 8, True)
    check("整段收拢模式", hinfo["mode"] == "head-hold", hinfo["mode"])
    check("收拢时脚接缝为 None", foot_seam(hold, feet, hinfo["mode"]) is None,
          str(foot_seam(hold, feet, hinfo["mode"])))

    check("好循环判定", loop_verdict(1.0, 0.01, "periodic", 1.0) == "好循环")
    check("脚差太多优先报警",
          "脚差了" in loop_verdict(0.5, 0.01, "periodic", 2.0),
          loop_verdict(0.5, 0.01, "periodic", 2.0))


def test_module_split() -> None:
    print("\n2c) 拆分后的模块边界")
    import cycle_search
    import loop_cut
    import make_loop

    check("cycle_search 不 import loop_cut",
          "loop_cut" not in open(cycle_search.__file__, encoding="utf-8").read())
    check("loop_cut 只依赖 cycle_search 的基础函数",
          "find_cycle_feet" not in open(loop_cut.__file__, encoding="utf-8").read())
    for legacy in ("find_cycle_feet", "foot_range", "foot_step", "make_loop", "seam_metrics"):
        check("make_loop 仍导出 %s" % legacy, hasattr(make_loop, legacy))


def test_action_meta() -> None:
    print("\n4) 动作契约 action_meta")
    tmp = tempfile.mkdtemp(prefix="smoke_meta_")
    try:
        open(os.path.join(tmp, "a.fbx"), "w").close()
        cmd = [sys.executable, os.path.join(ROOT, "core", "action_meta.py"),
               "--dir", tmp, "--name", "test_action", "--source", "model",
               "--rig", "R", "--origin", "p", "--loopable"]
        out = subprocess.run(cmd, capture_output=True, text=True)
        check("命令成功", out.returncode == 0, out.stderr.strip()[:60])
        meta = json.load(open(os.path.join(tmp, "action.json"), encoding="utf-8"))
        for key in ("kind", "version", "name", "source", "rig", "loopable",
                    "in_place", "files", "qa", "created"):
            check("字段 %s" % key, key in meta)
        version_file = open(os.path.join(ROOT, "VERSION"), encoding="utf-8").read().strip()
        check("版本来自 VERSION", meta["version"] == version_file,
              "%s vs %s" % (meta["version"], version_file))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_schema() -> None:
    print("\n4b) 动作契约定义（core/action_schema.py）")
    from action_schema import KIND, LOOP_MODES, SOURCES, validate

    ok = {"kind": KIND, "version": "1.0.0.0", "name": "gen_x", "source": "model",
          "in_place": True, "files": []}
    check("合格样本无问题", validate(ok) == [], str(validate(ok)))

    for bad_case, expect in (
        ({"kind": KIND, "name": "x", "source": "model", "in_place": True, "files": []},
         "缺 version"),
        (dict(ok, source="teleport"), "source 不在允许值"),
        (dict(ok, in_place="yes"), "in_place 类型"),
    ):
        problems = validate(bad_case)
        check("能报出：%s" % expect, bool(problems), str(problems)[:70])

    check("capture 是合法来源", "capture" in SOURCES, str(sorted(SOURCES)))
    check("loop_mode 定义齐全", set(LOOP_MODES) == {"periodic", "head-hold"}, str(LOOP_MODES))


def test_action_index() -> None:
    print("\n5) 动作索引")
    tmp = tempfile.mkdtemp(prefix="smoke_index_")
    try:
        for name in ("alpha", "beta"):
            d = os.path.join(tmp, "actions", name)
            os.makedirs(d)
            open(os.path.join(d, "x.fbx"), "w").close()
            cmd = [sys.executable, os.path.join(ROOT, "core", "action_meta.py"),
                   "--dir", d, "--name", name, "--source", "library", "--rig", "R"]
            subprocess.run(cmd, capture_output=True, text=True)
        # 再放一个同名动作，索引应报"重名"
        dup = os.path.join(tmp, "actions", "alpha_copy")
        shutil.copytree(os.path.join(tmp, "actions", "alpha"), dup)
        out = subprocess.run([sys.executable, os.path.join(ROOT, "core", "action_index.py"),
                              "--root", tmp, "--out", tmp],
                             capture_output=True, text=True)
        check("索引命令成功", out.returncode == 0, out.stderr.strip()[:60])
        index = json.load(open(os.path.join(tmp, "actions_index.json"), encoding="utf-8"))
        check("扫到 3 条", index["count"] == 3, str(index["count"]))
        check("报了重名", any("重名" in p for p in index["problems"]),
              str(index["problems"])[:80])
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_imports() -> None:
    print("\n6) 工具可导入")
    for mod in ("make_loop", "cycle_search", "loop_cut", "rig_joints",
                "gait_report", "cycle_candidates"):
        try:
            __import__(mod)
            check("import %s" % mod, True)
        except Exception as exc:            # 导入失败要看到具体异常
            check("import %s" % mod, False, repr(exc)[:80])


def main() -> int:
    print("冒烟测试（工程根 %s）" % ROOT)
    for fn in (test_limbs, test_cycle_feet, test_loop_cut, test_module_split,
               test_action_meta, test_schema, test_action_index, test_imports):
        try:
            fn()
        except Exception as exc:            # 单个用例炸了不拦其它用例
            FAIL.append(fn.__name__)
            print("  [FAIL] %s 抛异常: %r" % (fn.__name__, exc))
    print("\n结果：通过 %d，失败 %d" % (len(PASS), len(FAIL)))
    if FAIL:
        print("失败项：" + ", ".join(FAIL))
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())