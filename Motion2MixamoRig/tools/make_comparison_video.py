"""把两次动补(不同焦距)的角色预览并排合成一个对比视频,并烧上标签。

为什么不用 ffmpeg 的 drawtext:Windows 上字体路径里的冒号要转义,容易出错;
这里用 PIL 先画两张透明标签 PNG,再让 ffmpeg 只做 overlay + hstack。
"""
from __future__ import annotations

import argparse
import subprocess
import sys
import tempfile
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

WIDTH, HEIGHT = 1280, 720
BAND_HEIGHT = 76


def _font(size: int) -> ImageFont.FreeTypeFont:
    """优先用 matplotlib 自带的 DejaVu Sans(一定存在),否则退回 PIL 默认字体。"""
    try:
        import matplotlib

        candidate = Path(matplotlib.get_data_path()) / "fonts" / "ttf" / "DejaVuSans-Bold.ttf"
        if candidate.is_file():
            return ImageFont.truetype(str(candidate), size)
    except Exception:
        pass
    return ImageFont.load_default()


def make_label(text: str, output: Path, colour: tuple[int, int, int]) -> Path:
    """画一条半透明黑底白字的标签,宽度与视频一致。"""
    image = Image.new("RGBA", (WIDTH, BAND_HEIGHT), (0, 0, 0, 150))
    draw = ImageDraw.Draw(image)
    draw.text((20, 16), text, font=_font(34), fill=colour + (255,))
    output.parent.mkdir(parents=True, exist_ok=True)
    image.save(output)
    return output


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--left", required=True, help="左边视频")
    parser.add_argument("--right", required=True, help="右边视频")
    parser.add_argument("--left-label", required=True)
    parser.add_argument("--right-label", required=True)
    parser.add_argument("--out", required=True)
    arguments = parser.parse_args()

    left, right = Path(arguments.left), Path(arguments.right)
    for path in (left, right):
        if not path.is_file():
            print("缺文件:", path)
            return 2

    with tempfile.TemporaryDirectory(prefix="compare_labels_") as temporary:
        temporary_path = Path(temporary)
        left_label = make_label(arguments.left_label, temporary_path / "left.png", (255, 190, 190))
        right_label = make_label(arguments.right_label, temporary_path / "right.png", (190, 220, 255))
        filter_graph = (
            "[0:v][2:v]overlay=0:0:format=auto[a];"
            "[1:v][3:v]overlay=0:0:format=auto[b];"
            "[a][b]hstack=inputs=2[out]"
        )
        command = [
            "ffmpeg", "-y", "-loglevel", "error",
            "-i", str(left), "-i", str(right),
            "-i", str(left_label), "-i", str(right_label),
            "-filter_complex", filter_graph,
            "-map", "[out]", "-c:v", "libx264", "-crf", "20", "-preset", "veryfast",
            "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(arguments.out),
        ]
        completed = subprocess.run(command, capture_output=True, text=True)
        if completed.returncode != 0:
            print("ffmpeg 失败:", (completed.stderr or "")[-400:])
            return 1

    output = Path(arguments.out)
    print("写出 %s (%.1f MB)" % (output, output.stat().st_size / 1048576))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
