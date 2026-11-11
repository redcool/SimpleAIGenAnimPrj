"""把"人到相机的距离"换算成相机焦距(像素)。

为什么要这个:GVHMR 的绝对深度由 **焦距** 决定(pinhole 近似下 深度 ∝ 焦距),
没给焦距时它按 ~43mm 等效估,手机主摄(约 26mm)的深度会高估约 65%。
但用户手里通常没有焦距,只有"人站多远"这种可测的量。

针孔关系:
    像素身高 = 焦距(px) × 真人身高(m) / 距离(m)
所以:
    焦距(px) = 像素身高 × 距离(m) / 真人身高(m)

也就是说"给距离"和"给焦距"是同一件事的两种输入,本模块负责前者:
先用目标检测量出画面里人的像素身高,再换算成焦距交给上游。

注意:身高要用真实身高(默认 1.70m),不要用模型估的体型 —— 那正是要消歧的量。
"""
from __future__ import annotations

import logging
import statistics
from pathlib import Path

LOGGER = logging.getLogger("motion2mixamo.camera_distance")

DEFAULT_PERSON_HEIGHT_METRES = 1.70
DEFAULT_SAMPLE_FRAMES = 5


def focal_pixels_from_distance(pixel_height: float, distance_metres: float,
                               person_height_metres: float) -> float:
    """焦距(像素) = 像素身高 × 距离 / 真人身高。三个参数都必须是正数。"""
    if pixel_height <= 0 or distance_metres <= 0 or person_height_metres <= 0:
        raise ValueError("像素身高、距离、真人身高都必须为正数")
    return pixel_height * distance_metres / person_height_metres


def _load_detector(weights: Path | None):
    """用上游仓库里的 YOLO 权重;没有就退回 ultralytics 的 yolov8n。"""
    from ultralytics import YOLO

    if weights is not None and Path(weights).is_file():
        return YOLO(str(weights))
    LOGGER.warning("没找到 %s,退回 yolov8n(精度略低)", weights)
    return YOLO("yolov8n.pt")


def person_pixel_height(video: Path, weights: Path | None = None,
                        sample_frames: int = DEFAULT_SAMPLE_FRAMES) -> float | None:
    """在若干等距帧上量"人的包围盒高度",取中位数(像素);一帧都没检测到就返回 None。"""
    import cv2

    capture = cv2.VideoCapture(str(video))
    if not capture.isOpened():
        LOGGER.warning("打不开视频:%s", video)
        return None
    frame_count = int(capture.get(cv2.CAP_PROP_FRAME_COUNT)) or 0
    if frame_count <= 0:
        capture.release()
        LOGGER.warning("读不到帧数:%s", video)
        return None

    detector = _load_detector(weights)
    heights: list[float] = []
    for index in range(sample_frames):
        position = int(round(index * (frame_count - 1) / max(sample_frames - 1, 1)))
        capture.set(cv2.CAP_PROP_POS_FRAMES, position)
        ok, frame = capture.read()
        if not ok:
            continue
        result = detector.predict(frame, conf=0.5, classes=[0], verbose=False)[0]
        if result.boxes is None or len(result.boxes) == 0:
            continue
        # 取面积最大的人(单人素材里就是主体)
        tops = [float(box.xyxy[0][1]) for box in result.boxes]
        bottoms = [float(box.xyxy[0][3]) for box in result.boxes]
        heights.append(max(bottoms) - min(tops))
    capture.release()

    if not heights:
        LOGGER.warning("在抽样的 %d 帧里没有检测到人:%s", sample_frames, video.name)
        return None
    measured = float(statistics.median(heights))
    LOGGER.info("像素身高 %.1f px(取 %d 帧中位数)", measured, len(heights))
    return measured


def focal_pixels_from_distance_for_video(video: Path, distance_metres: float,
                                         person_height_metres: float = DEFAULT_PERSON_HEIGHT_METRES,
                                         weights: Path | None = None) -> float | None:
    """从视频 + 距离推出焦距;量不到人就返回 None,让调用方决定怎么办。"""
    measured = person_pixel_height(video, weights=weights)
    if measured is None:
        return None
    focal = focal_pixels_from_distance(measured, distance_metres, person_height_metres)
    LOGGER.info("按 距离 %.2fm / 身高 %.2fm 推算焦距 %.0f px", distance_metres,
                person_height_metres, focal)
    return focal
