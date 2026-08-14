"""Generate the canonical 有迹 Windows icon used by release packaging."""
from __future__ import annotations

import os
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ICON_SIZES = (16, 20, 24, 32, 40, 48, 64, 128, 256)
CANVAS_SIZE = 256
GLYPH = "迹"


def _font_candidates() -> list[Path]:
    windows = Path(os.environ.get("WINDIR", r"C:\Windows")) / "Fonts"
    return [
        windows / "msyhbd.ttc",  # Microsoft YaHei Bold
        windows / "msyh.ttc",  # Microsoft YaHei
        windows / "simhei.ttf",  # SimHei
        Path("/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc"),
        Path("/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"),
    ]


def _load_font(size: int) -> ImageFont.FreeTypeFont:
    for candidate in _font_candidates():
        if candidate.is_file():
            return ImageFont.truetype(str(candidate), size=size, index=0)
    raise RuntimeError("No CJK font is available to generate the 有迹 icon")


def _gradient_background(size: int) -> Image.Image:
    image = Image.new("RGBA", (size, size))
    pixels = image.load()
    start = (49, 87, 213)
    end = (23, 55, 143)
    denominator = max(1, 2 * (size - 1))
    for y in range(size):
        for x in range(size):
            t = (x + y) / denominator
            pixels[x, y] = tuple(
                round(start[channel] * (1 - t) + end[channel] * t)
                for channel in range(3)
            ) + (255,)
    return image


def render_icon(size: int = CANVAS_SIZE) -> Image.Image:
    background = _gradient_background(size)
    mask = Image.new("L", (size, size), 0)
    mask_draw = ImageDraw.Draw(mask)
    radius = round(size * 0.20)
    mask_draw.rounded_rectangle((0, 0, size - 1, size - 1), radius=radius, fill=255)

    canvas = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    canvas.paste(background, (0, 0), mask)

    draw = ImageDraw.Draw(canvas)
    font = _load_font(round(size * 0.56))
    bbox = draw.textbbox((0, 0), GLYPH, font=font, stroke_width=1)
    width = bbox[2] - bbox[0]
    height = bbox[3] - bbox[1]
    x = (size - width) / 2 - bbox[0]
    # Optical centering: Chinese glyph metrics otherwise sit slightly low.
    y = (size - height) / 2 - bbox[1] - size * 0.012
    draw.text(
        (x, y),
        GLYPH,
        font=font,
        fill=(255, 255, 255, 255),
        stroke_width=1,
        stroke_fill=(255, 255, 255, 255),
    )
    return canvas


def generate_icon(output_path: str | Path) -> Path:
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    image = render_icon()
    image.save(output, format="ICO", sizes=[(size, size) for size in ICON_SIZES])
    return output


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument(
        "output",
        nargs="?",
        default="build/brand/trace.ico",
        help="ICO output path",
    )
    args = parser.parse_args()
    print(generate_icon(args.output))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
