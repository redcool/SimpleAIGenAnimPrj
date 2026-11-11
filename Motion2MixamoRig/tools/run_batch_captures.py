"""批量跑素材并给出质检判断。

对目录里的每个视频依次:跑 m2mr(不出预览)→ 落地修正 → 读指标 → 判 PASS/WARN/FAIL,
最后写一份 markdown + csv 报告。判定阈值来自实测:合格片(punch)穿模 3.4%、陷地可修;
不合格片(demo 裁剪)穿模 47%、脚锁修正 29.6cm。

用法:
    python run_batch_captures.py --videos assets/video [--focal-pixels 1387] [--limit 3]
"""
from __future__ import annotations

import argparse
import csv
import json
import logging
import os
import subprocess
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

LOGGER = logging.getLogger("motion2mixamo.batch")

TOOLS_ROOT = Path(__file__).resolve().parent
if str(TOOLS_ROOT) not in sys.path:
    sys.path.insert(0, str(TOOLS_ROOT))

import motion2mixamo_config as config  # noqa: E402

VIDEO_SUFFIXES = (".mp4", ".mov", ".avi", ".mkv", ".webm")

FAIL_FRAME_SHARE = 0.15
WARN_FRAME_SHARE = 0.05
FAIL_MAX_DEPTH_CENTIMETRES = 8.0
WARN_MAX_DEPTH_CENTIMETRES = 5.0
FAIL_FOOT_LOCK_CENTIMETRES = 30.0
WARN_FOOT_LOCK_CENTIMETRES = 15.0


@dataclass
class CaptureRecord:
    """一条素材的处理结果。"""

    clip: str
    verdict: str = "UNKNOWN"
    note: str = ""
    duration_seconds: float | None = None
    frame_count: int | None = None
    frames_per_second: float | None = None
    elapsed_seconds: float | None = None
    foot_lock_mean_centimetres: float | None = None
    foot_lock_max_centimetres: float | None = None
    self_intersection_share: float | None = None
    self_intersection_frames: int | None = None
    self_intersection_max_centimetres: float | None = None
    grounded: bool = False
    extra: dict = field(default_factory=dict)


def build_environment() -> dict[str, str]:
    """所有缓存都落在本模块 tmp 下,避免写到用户目录或引用库。"""
    temporary_root = config.module_tmp()
    environment = os.environ.copy()
    environment.update({
        "TMP": str(temporary_root),
        "TEMP": str(temporary_root),
        "YOLO_CONFIG_DIR": str(temporary_root / "ultralytics"),
        "HF_HOME": str(temporary_root / "huggingface"),
        "HF_XET_CACHE": str(temporary_root / "huggingface" / "xet"),
        "HUGGINGFACE_HUB_CACHE": str(temporary_root / "huggingface" / "hub"),
        "TORCH_HOME": str(temporary_root / "torch"),
        "XDG_CACHE_HOME": str(temporary_root / "xdg"),
        "PYTHONIOENCODING": "utf-8",
    })
    return environment


def probe_duration_seconds(clip: Path) -> float | None:
    """用 ffprobe 读时长;失败返回 None。"""
    try:
        completed = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "default=nw=1:nk=1", str(clip)],
            capture_output=True, text=True, timeout=30, check=False,
        )
        return float(completed.stdout.strip())
    except (ValueError, OSError) as error:
        LOGGER.warning("读取时长失败 %s: %s", clip.name, error)
        return None


def run_single_capture(clip: Path, rig: Path, output_directory: Path, focal_pixels: float | None,
                       reference_python: str, device: str, environment: dict[str, str]) -> CaptureRecord:
    """跑一条素材并归档指标。解释器与设备都由调用方给定,不在这里猜。"""
    record = CaptureRecord(clip=clip.name)
    started_at = time.time()
    command = [
        reference_python, str(TOOLS_ROOT / "motion2mixamo_command.py"), "run",
        "--video", str(clip), "--rig", str(rig), "--device", device,
        "--output-dir", str(output_directory), "--no-preview",
    ]
    if focal_pixels:
        environment = dict(environment)
        environment["MOTION2MIXAMO_FOCAL_PIXELS"] = str(focal_pixels)
    completed = subprocess.run(command, cwd=str(config.motion2mixamo_home()), env=environment,
                               capture_output=True, text=True, encoding="utf-8", errors="replace", check=False)
    record.elapsed_seconds = round(time.time() - started_at, 1)
    if completed.returncode != 0:
        record.verdict = "FAIL"
        record.note = (completed.stderr or completed.stdout or "")[-300:].replace("\n", " ")
        return record

    run_report_path = output_directory / "run.json"
    diagnostics_path = output_directory / "diagnostics.json"
    if not run_report_path.exists():
        record.verdict = "FAIL"
        record.note = "缺少 run.json"
        return record
    run_report = json.loads(run_report_path.read_text(encoding="utf-8"))
    diagnostics = json.loads(diagnostics_path.read_text(encoding="utf-8")) if diagnostics_path.exists() else {}

    intersection = (diagnostics.get("summary") or {}).get("self_intersection", {})
    foot_lock = run_report.get("foot_lock") or {}
    record.frame_count = run_report.get("n_frames")
    record.frames_per_second = round(float(run_report.get("fps") or 0.0), 2)
    record.foot_lock_mean_centimetres = foot_lock.get("mean_correction_cm")
    record.foot_lock_max_centimetres = foot_lock.get("max_correction_cm")
    record.self_intersection_frames = intersection.get("frame_count")
    record.self_intersection_max_centimetres = intersection.get("max_depth_cm")
    if record.frame_count:
        record.self_intersection_share = round(float(record.self_intersection_frames or 0) / record.frame_count, 4)

    grounding = subprocess.run(
        [reference_python, str(TOOLS_ROOT / "ground_character_on_floor.py"), str(output_directory)],
        cwd=str(config.motion2mixamo_home()), env=environment, capture_output=True, text=True,
        encoding="utf-8", errors="replace", check=False, timeout=3600,
    )
    record.grounded = (output_directory / "mixamo_character_grounded.glb").exists()
    if grounding.returncode != 0:
        LOGGER.warning("落地修正失败 %s: %s", clip.name, (grounding.stderr or "")[-200:])

    record.verdict, record.note = decide_verdict(record)
    return record


def decide_verdict(record: CaptureRecord) -> tuple[str, str]:
    """按阈值给出判定。"""
    share = record.self_intersection_share or 0.0
    depth = record.self_intersection_max_centimetres or 0.0
    foot_lock = record.foot_lock_max_centimetres or 0.0
    reasons: list[str] = []
    if share >= FAIL_FRAME_SHARE or depth >= FAIL_MAX_DEPTH_CENTIMETRES or foot_lock >= FAIL_FOOT_LOCK_CENTIMETRES:
        if share >= FAIL_FRAME_SHARE:
            reasons.append(f"穿模帧 {share * 100:.1f}%")
        if depth >= FAIL_MAX_DEPTH_CENTIMETRES:
            reasons.append(f"最深 {depth:.1f}cm")
        if foot_lock >= FAIL_FOOT_LOCK_CENTIMETRES:
            reasons.append(f"脚锁 {foot_lock:.1f}cm")
        return "FAIL", "; ".join(reasons)
    if share >= WARN_FRAME_SHARE or depth >= WARN_MAX_DEPTH_CENTIMETRES or foot_lock >= WARN_FOOT_LOCK_CENTIMETRES:
        if share >= WARN_FRAME_SHARE:
            reasons.append(f"穿模帧 {share * 100:.1f}%")
        if depth >= WARN_MAX_DEPTH_CENTIMETRES:
            reasons.append(f"最深 {depth:.1f}cm")
        if foot_lock >= WARN_FOOT_LOCK_CENTIMETRES:
            reasons.append(f"脚锁 {foot_lock:.1f}cm")
        return "WARN", "; ".join(reasons)
    return "PASS", ""


def write_reports(records: list[CaptureRecord], report_directory: Path) -> tuple[Path, Path]:
    """写 markdown 与 csv 两份报告。"""
    report_directory.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    csv_path = report_directory / f"batch_report_{stamp}.csv"
    markdown_path = report_directory / f"batch_report_{stamp}.md"

    columns = ["clip", "verdict", "duration_seconds", "frame_count", "frames_per_second",
               "elapsed_seconds", "foot_lock_mean_centimetres", "foot_lock_max_centimetres",
               "self_intersection_share", "self_intersection_frames",
               "self_intersection_max_centimetres", "grounded", "note"]
    with open(csv_path, "w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.writer(handle)
        writer.writerow(columns)
        for record in records:
            writer.writerow([getattr(record, column) for column in columns])

    lines = [f"# 批量动补报告 {stamp}", "",
             f"判定规则:FAIL = 穿模帧≥{FAIL_FRAME_SHARE:.0%} 或 最深≥{FAIL_MAX_DEPTH_CENTIMETRES:.0f}cm "
             f"或 脚锁≥{FAIL_FOOT_LOCK_CENTIMETRES:.0f}cm;WARN = 超过 "
             f"{WARN_FRAME_SHARE:.0%}/{WARN_MAX_DEPTH_CENTIMETRES:.0f}cm/{WARN_FOOT_LOCK_CENTIMETRES:.0f}cm;"
             f"其余 PASS", "",
             "| 片名 | 判定 | 时长s | 帧数 | 耗时s | 脚锁均/最大cm | 穿模帧 | 最深cm | 说明 |",
             "|---|---|---|---|---|---|---|---|---|"]
    for record in records:
        share_text = f"{(record.self_intersection_share or 0) * 100:.1f}%"
        lines.append(
            f"| {record.clip} | {record.verdict} | {record.duration_seconds or ''} | "
            f"{record.frame_count or ''} | {record.elapsed_seconds or ''} | "
            f"{record.foot_lock_mean_centimetres}/{record.foot_lock_max_centimetres} | "
            f"{share_text} | {record.self_intersection_max_centimetres} | {record.note} |"
        )
    counts: dict[str, int] = {}
    for record in records:
        counts[record.verdict] = counts.get(record.verdict, 0) + 1
    lines += ["", "汇总:" + ", ".join(f"{key}={value}" for key, value in sorted(counts.items()))]
    markdown_path.write_text("\n".join(lines), encoding="utf-8")
    return markdown_path, csv_path


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="[%(asctime)s] %(message)s", stream=sys.stdout)
    parser = argparse.ArgumentParser()
    parser.add_argument("--videos", default=str(config.assets_video()))
    parser.add_argument("--rig", default=str(config.default_rig()))
    parser.add_argument("--out", default=str(config.video_cap_output_root()),
                        help="交付根目录,默认 outputs/video_cap")
    parser.add_argument("--report", default=None, help="报告目录,默认与 --out 相同")
    parser.add_argument("--device", default="cuda", choices=["cpu", "cuda", "mps"],
                        help="推理设备,默认 cuda")
    parser.add_argument("--python", default=None,
                        help="跑引用库的解释器,默认取配置(MOTION2MIXAMO_PYTHON 或 <HOME>/.venv)")
    parser.add_argument("--focal-pixels", type=float,
                        default=config.default_focal_pixels(),
                        help="相机焦距(像素);默认取配置里的 MOTION2MIXAMO_FOCAL_PIXELS")
    parser.add_argument("--skip-existing", action="store_true")
    parser.add_argument("--min-seconds", type=float, default=2.0)
    parser.add_argument("--limit", type=int, default=None)
    arguments = parser.parse_args()

    reference_python = arguments.python or config.resolve_reference_python()
    LOGGER.info("引用库 %s", config.motion2mixamo_home())
    LOGGER.info("解释器 %s", reference_python)
    LOGGER.info("设备 %s | 交付根 %s", arguments.device, arguments.out)

    video_directory = Path(arguments.videos)
    if not video_directory.is_dir():
        LOGGER.error("素材目录不存在: %s", video_directory)
        return 1
    clips = sorted(path for path in video_directory.iterdir() if path.suffix.lower() in VIDEO_SUFFIXES)
    if arguments.limit:
        clips = clips[: arguments.limit]
    if not clips:
        LOGGER.error("目录里没有视频: %s", video_directory)
        return 1

    rig_path = Path(arguments.rig)
    environment = build_environment()
    output_root = Path(arguments.out)
    records: list[CaptureRecord] = []
    for index, clip in enumerate(clips, start=1):
        duration = probe_duration_seconds(clip)
        if duration is not None and duration < arguments.min_seconds:
            records.append(CaptureRecord(clip=clip.name, verdict="SKIP", note=f"太短 {duration:.1f}s"))
            continue
        clip_output = output_root / clip.stem
        if arguments.skip_existing and (clip_output / "run.json").exists():
            LOGGER.info("[%d/%d] %s 已处理,跳过", index, len(clips), clip.name)
            continue
        LOGGER.info("[%d/%d] %s (%.1fs)", index, len(clips), clip.name, duration or 0.0)
        record = run_single_capture(clip, rig_path, clip_output, arguments.focal_pixels,
                                   reference_python, arguments.device, environment)
        record.duration_seconds = round(duration, 2) if duration else None
        records.append(record)
        LOGGER.info("    %s %s", record.verdict, record.note)

    # 报告单独放 _batch_reports,避免和逐个动作的交付目录混在一起
    report_directory = Path(arguments.report) if arguments.report else (output_root / "_batch_reports")
    markdown_path, csv_path = write_reports(records, report_directory)
    LOGGER.info("报告 %s", markdown_path)
    LOGGER.info("CSV  %s", csv_path)
    return 0 if all(record.verdict != "FAIL" for record in records) else 2


if __name__ == "__main__":
    raise SystemExit(main())
