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
    7. 动补工具：落地偏移算法、GLB 字节写回、机位融合拟合、动补契约
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


def test_period_ceiling() -> None:
    print("\n2d) 周期上限按片段长度放宽")
    from cycle_search import CycleOptions, choose_cycle, period_ceiling

    short = np.zeros((60, 4, 12), dtype=np.float32)
    long_clip = np.zeros((160, 4, 12), dtype=np.float32)
    check("60 帧素材仍是 58（历史行为不变）",
          period_ceiling(short, CycleOptions()) == 58, str(period_ceiling(short, CycleOptions())))
    check("160 帧长片段放宽到 144",
          period_ceiling(long_clip, CycleOptions()) == 144,
          str(period_ceiling(long_clip, CycleOptions())))
    check("显式 --max-period 优先",
          period_ceiling(long_clip, CycleOptions(max_period=40)) == 40)

    # 造一段周期 90 的长动作：老上限 58 找不到，新逻辑应该找到
    frames = 160
    t_axis = np.arange(frames)
    x = np.zeros((frames, 4, 12), dtype=np.float32)
    for j in range(4):
        x[:, j, 0] = 0.4 * np.sin(2 * np.pi * t_axis / 90.0 + j * 0.5)
        x[:, j, 3] = 1.0
    feet = {"后左": 0, "后右": 1, "前左": 2, "前右": 3}
    choice = choose_cycle(x, feet, CycleOptions(basis="feet"))
    check("90 帧周期能被找到", choice.period == 90, "period=%d" % choice.period)
    old = choose_cycle(x, feet, CycleOptions(basis="feet", max_period=58))
    check("旧上限 58 确实找不到它", old.period != 90, "period=%d" % old.period)


def test_basis_rule() -> None:
    print("\n2e) 依据规则：四足按脚、两足按姿态")
    from cycle_search import CycleOptions, choose_cycle

    frames = 80
    t_axis = np.arange(frames)
    x = np.zeros((frames, 8, 12), dtype=np.float32)
    for j in range(8):
        x[:, j, 0] = 0.3 * np.sin(2 * np.pi * t_axis / 20.0 + j * 0.3)
        x[:, j, 3] = 1.0

    four = {"后左": 0, "后右": 1, "前左": 2, "前右": 3}
    two = {"后左": 0, "后右": 1}
    check("四足走 feet", choose_cycle(x, four, CycleOptions()).basis == "feet",
          choose_cycle(x, four, CycleOptions()).basis)
    check("两足走 rot", choose_cycle(x, two, CycleOptions()).basis == "rot",
          choose_cycle(x, two, CycleOptions()).basis)
    check("显式 basis 优先", choose_cycle(x, two, CycleOptions(basis="feet")).basis == "feet")


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


def test_deliver_pack() -> None:
    print("\n4c) 两版交付的挑片逻辑（deliver_pack）")
    import deliver_pack as dp

    tmp = tempfile.mkdtemp(prefix="smoke_pack_")
    try:
        # 造一份 gait 报告：run 一条成型、一条不典型
        gait_txt = """
=== a_runs_forward.npy ===
    后右 toe.R                    竖直摆幅 0.04
  判定: 前后各自同相 → 袭步/跳跃式（左右 +0.9），跑动正常
=== b_runs_forward.npy ===
    后右 toe.R                    竖直摆幅 0.01
  判定: 相位不典型，需看视频确认
"""
        gait_path = os.path.join(tmp, "gait_report.txt")
        open(gait_path, "w", encoding="utf-8").write(gait_txt)
        gait = dp.parse_gait(gait_path)
        check("gait 解析出两条", len(gait) == 2, str(list(gait)))

        # 造 loop_report + 假的 animated_inplace 文件
        anim = os.path.join(tmp, "animated_inplace")
        os.makedirs(anim)
        for name in ("a_runs_forward", "b_runs_forward"):
            open(os.path.join(anim, name + ".fbx"), "w").close()
        report = {"items": {
            "a_runs_forward.npy": {"period_detected": 22, "frames_in": 60,
                                   "foot_seam_ratio": 0.9},
            "b_runs_forward.npy": {"period_detected": 60, "frames_in": 60,
                                   "foot_seam_ratio": None},
        }}
        json.dump(report, open(os.path.join(tmp, "loop_report.json"), "w", encoding="utf-8"))
        chosen = dp.pick_looped(tmp, "runs_forward", gait)
        check("挑到真周期那条", chosen and chosen[2] == "a_runs_forward.npy",
              str(chosen[2]) if chosen else "None")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


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
                "gait_report", "cycle_candidates", "deliver_pack"):
        try:
            __import__(mod)
            check("import %s" % mod, True)
        except Exception as exc:            # 导入失败要看到具体异常
            check("import %s" % mod, False, repr(exc)[:80])


def test_motion2mixamo() -> None:
    """动补工具的三处核心算法：落地偏移、GLB 写回、机位融合。"""
    print("\n7) 动补工具（Motion2MixamoRig）")
    tools_dir = os.path.join(ROOT, "Motion2MixamoRig", "tools")
    if not os.path.isdir(tools_dir):
        check("动补模块存在", False, tools_dir)
        return
    sys.path.insert(0, tools_dir)

    # 动补工具要在 m2mr 的 venv 里跑(要 numpy + 引用库)。换了解释器就跳过,
    # 不把"环境不对"记成 FAIL —— 那会让 UniMate 侧的冒烟永远红。
    try:
        import ground_character_on_floor  # noqa: F401
    except (Exception, SystemExit) as exc:
        print("  [skip] 当前解释器拿不到动补依赖（%s），本节跳过；"
              "要用 m2mr 的 python 跑：Motion2MixamoRig\\.venv\\Scripts\\python.exe tests/smoke.py"
              % repr(exc)[:60])
        return

    # --- 7.1 落地偏移：着地帧压到 0，且任何帧都不穿地 ---
    try:
        import ground_character_on_floor as ground
    except Exception as exc:                # 导入失败要看到具体异常
        check("import ground_character_on_floor", False, repr(exc)[:80])
    else:
        check("import ground_character_on_floor", True)
        lowest = np.array([0.05, -0.06, 0.02, 0.31, 0.0, -0.02])
        contact = np.array([[1.0, 1.0, 1.0, 1.0]] * 3 + [[0.0, 0.0, 0.0, 0.0]] * 3)
        offsets = ground.compute_vertical_offsets(lowest, contact, False)
        after = lowest + offsets
        check("着地帧最低点归零",
              abs(after[0]) < 1e-9 and abs(after[1]) < 1e-9 and abs(after[2]) < 1e-9,
              "after=%s" % np.round(after, 4).tolist())
        check("任何帧都不穿地", float(after.min()) > -1e-9, "min=%.4f" % float(after.min()))

        always = ground.compute_vertical_offsets(lowest, contact, True)
        check("--always-ground 每帧贴地",
              float(np.abs(lowest + always).max()) < 1e-9,
              "max=%.4f" % float(np.abs(lowest + always).max()))

    # --- 7.2 GLB 读写往返 + Hips 通道定位（字节级数学）---
    try:
        import ground_character_on_floor as ground
        frame_count = 4
        times = np.arange(frame_count, dtype=np.float32) * 0.0333
        hips = np.array([[0.0, 1.0, 0.0]] * frame_count, dtype=np.float32)
        binary = times.tobytes() + hips.tobytes()
        gltf = {
            "asset": {"version": "2.0"},
            "nodes": [{"name": "mixamorig:Hips"}],
            "scenes": [{"nodes": [0]}],
            "scene": 0,
            "accessors": [
                {"bufferView": 0, "componentType": 5126, "count": frame_count, "type": "SCALAR"},
                {"bufferView": 1, "componentType": 5126, "count": frame_count, "type": "VEC3"},
            ],
            "bufferViews": [
                {"buffer": 0, "byteOffset": 0, "byteLength": frame_count * 4},
                {"buffer": 0, "byteOffset": frame_count * 4, "byteLength": frame_count * 12},
            ],
            "buffers": [{"byteLength": len(binary)}],
            "animations": [{
                "channels": [{"sampler": 0, "target": {"node": 0, "path": "translation"}}],
                "samplers": [{"input": 0, "output": 1}],
            }],
        }
        import tempfile
        with tempfile.TemporaryDirectory(prefix="smoke_glb_") as tmp:
            glb_path = os.path.join(tmp, "clip.glb")
            ground.write_glb(glb_path, gltf, binary)
            parsed_json, parsed_bin = ground.read_glb(glb_path)
            check("GLB 读回 JSON 一致", parsed_json["nodes"][0]["name"] == "mixamorig:Hips")
            check("GLB 读回 BIN 长度一致", len(parsed_bin) == len(binary),
                  "%d vs %d" % (len(parsed_bin), len(binary)))
            hips_index = ground.find_hips_node_index(parsed_json)
            accessor = ground.find_hips_translation_accessor(parsed_json, hips_index)
            start, count, components, stride = ground.resolve_accessor_layout(parsed_json, accessor)
            check("Hips 通道定位正确",
                  (start, count, components, stride) == (frame_count * 4, frame_count, 3, 12),
                  "start=%d count=%d comps=%d stride=%d" % (start, count, components, stride))

            # 模拟工具里"原地加偏移再写回"的动作
            raw = np.frombuffer(bytes(parsed_bin[start:start + stride * count]),
                                dtype=np.float32).reshape(count, 3).copy()
            raw[:, 1] += 0.25
            parsed_bin[start:start + stride * count] = raw.astype(np.float32).tobytes()
            ground.write_glb(glb_path, parsed_json, bytes(parsed_bin))
            _, rewritten = ground.read_glb(glb_path)
            values = np.frombuffer(bytes(rewritten[start:start + stride * count]),
                                   dtype=np.float32).reshape(count, 3)
            check("写回偏移量正确", bool(np.allclose(values[:, 1], 1.25, atol=1e-6)),
                  str(np.round(values[:, 1], 3).tolist()))
    except Exception as exc:
        check("GLB 写回测试", False, repr(exc)[:100])

    # --- 7.3 机位融合：旋转与缩放能被拟合回来 ---
    try:
        import fuse_camera_views as fuse
    except Exception as exc:
        check("import fuse_camera_views", False, repr(exc)[:80])
    else:
        check("import fuse_camera_views", True)
        rng = np.random.default_rng(7)
        source = rng.normal(size=(30, 24, 3))
        angle = np.deg2rad(25.0)
        rotation = np.array([[np.cos(angle), 0, np.sin(angle)],
                             [0, 1, 0],
                             [-np.sin(angle), 0, np.cos(angle)]])
        target = 1.08 * (source @ rotation.T)
        fitted_rotation, fitted_scale = fuse.fit_rotation_and_scale(source, target, allow_scale=True)
        residual = np.abs(source @ fitted_rotation.T * fitted_scale - target).max()
        check("融合复原旋转+缩放", residual < 1e-6 and abs(fitted_scale - 1.08) < 1e-6,
              "scale=%.4f（真值 1.08）residual=%.2e" % (fitted_scale, residual))
        same_rotation, same_scale = fuse.fit_rotation_and_scale(target, target, allow_scale=False)
        check("恒等输入给出单位变换",
              bool(np.allclose(same_rotation, np.eye(3), atol=1e-9)) and abs(same_scale - 1.0) < 1e-12)

    # --- 7.4 距离 → 焦距换算（纯数学，不需要视频）---
    try:
        import camera_distance
    except Exception as exc:
        check("import camera_distance", False, repr(exc)[:80])
    else:
        check("import camera_distance", True)
        focal = camera_distance.focal_pixels_from_distance(747.7, 3.4, 1.75)
        check("距离换算焦距", abs(focal - 1452.6) < 1.0, "%.1f px" % focal)
        doubled = camera_distance.focal_pixels_from_distance(747.7, 6.8, 1.75)
        check("距离翻倍焦距翻倍", abs(doubled - 2 * focal) < 1e-9)
        try:
            camera_distance.focal_pixels_from_distance(0.0, 3.4, 1.75)
            check("非法参数被拒", False, "没有抛 ValueError")
        except ValueError:
            check("非法参数被拒", True)

    # --- 7.5 外部工具：ffmpeg/ffprobe 走配置，坏路径要明确报错 ---
    try:
        import motion2mixamo_config as config
    except Exception as exc:
        check("import motion2mixamo_config", False, repr(exc)[:80])
    else:
        # 不要再 import os:函数里出现 import 会让 os 变成局部名,前面用过的 os 会 UnboundLocalError
        for name, resolver in (("ffprobe", config.ffprobe_executable),
                               ("ffmpeg", config.ffmpeg_executable)):
            try:
                path = resolver()
                check("解析 %s" % name, os.path.isfile(path), path)
            except SystemExit as exc:
                print("  [skip] 本机没有 %s（%s）" % (name, str(exc).splitlines()[0][:60]))
        saved = os.environ.get("MOTION2MIXAMO_FFPROBE")
        os.environ["MOTION2MIXAMO_FFPROBE"] = os.path.join(ROOT, "no_such_ffprobe.exe")
        try:
            config.ffprobe_executable()
            check("坏路径被拒", False, "没有抛 SystemExit")
        except SystemExit:
            check("坏路径被拒", True)
        finally:
            if saved is None:
                os.environ.pop("MOTION2MIXAMO_FFPROBE", None)
            else:
                os.environ["MOTION2MIXAMO_FFPROBE"] = saved

    # --- 7.6 动补契约：capture 能过校验，乱填的 source 会被拒 ---
    try:
        from action_schema import SOURCES, validate
    except Exception as exc:
        check("import action_schema", False, repr(exc)[:80])
    else:
        good = {"kind": "action", "version": "test", "name": "cap_x",
                "source": "capture", "in_place": False, "files": ["a.glb"]}
        check("capture 是合法来源", "capture" in SOURCES and not validate(good), str(validate(good)))
        bad = dict(good, source="teleport")
        check("未知来源被拒", bool(validate(bad)), str(validate(bad))[:60])


def main() -> int:
    print("冒烟测试（工程根 %s）" % ROOT)
    for fn in (test_limbs, test_cycle_feet, test_loop_cut, test_period_ceiling,
               test_basis_rule, test_module_split, test_action_meta, test_schema, test_action_index,
               test_deliver_pack, test_imports, test_motion2mixamo):
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