#!/usr/bin/env python3
"""Generate the Retina Finder background used by the MineM installer."""

from __future__ import annotations

import argparse
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


CANVAS_WIDTH = 640
CANVAS_HEIGHT = 423
FONT_CANDIDATES = (
    Path("/System/Library/Fonts/SFNSRounded.ttf"),
    Path("/System/Library/Fonts/SFNS.ttf"),
    Path("/System/Library/Fonts/Helvetica.ttc"),
)


def load_font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    for path in FONT_CANDIDATES:
        if not path.is_file():
            continue
        try:
            return ImageFont.truetype(str(path), size)
        except OSError:
            continue
    return ImageFont.load_default()


def centered_text(
    draw: ImageDraw.ImageDraw,
    *,
    y: int,
    text: str,
    font: ImageFont.FreeTypeFont | ImageFont.ImageFont,
    fill: str,
    width: int,
) -> None:
    bounds = draw.textbbox((0, 0), text, font=font)
    text_width = bounds[2] - bounds[0]
    draw.text(((width - text_width) / 2, y), text, font=font, fill=fill)


def render_background(scale: int, destination: Path) -> None:
    width = CANVAS_WIDTH * scale
    height = CANVAS_HEIGHT * scale
    image = Image.new("RGB", (width, height), "#f4f8fc")
    draw = ImageDraw.Draw(image)

    for y in range(height):
        ratio = y / max(1, height - 1)
        red = round(247 - 13 * ratio)
        green = round(251 - 17 * ratio)
        blue = round(255 - 11 * ratio)
        draw.line((0, y, width, y), fill=(red, green, blue))

    draw.ellipse(
        (-120 * scale, -250 * scale, 360 * scale, 230 * scale),
        fill="#dceefe",
    )
    draw.ellipse(
        (410 * scale, 245 * scale, 810 * scale, 645 * scale),
        fill="#e5f2ff",
    )
    draw.rounded_rectangle(
        (24 * scale, 24 * scale, 616 * scale, 399 * scale),
        radius=24 * scale,
        fill="#f9fcff",
        outline="#d5e4f2",
        width=1 * scale,
    )

    centered_text(
        draw,
        y=50 * scale,
        text="Install MineM",
        font=load_font(30 * scale),
        fill="#0b3f75",
        width=width,
    )
    centered_text(
        draw,
        y=94 * scale,
        text="Drag MineM to Applications",
        font=load_font(16 * scale),
        fill="#5d7186",
        width=width,
    )

    arrow_y = 220 * scale
    arrow_start_x = 270 * scale
    arrow_end_x = 370 * scale
    arrow_color = "#1c78c0"
    draw.line(
        (arrow_start_x, arrow_y, arrow_end_x, arrow_y),
        fill=arrow_color,
        width=7 * scale,
    )
    draw.polygon(
        (
            (arrow_end_x, arrow_y),
            ((arrow_end_x - 22 * scale), (arrow_y - 17 * scale)),
            ((arrow_end_x - 22 * scale), (arrow_y + 17 * scale)),
        ),
        fill=arrow_color,
    )

    draw.rounded_rectangle(
        (101 * scale, 154 * scale, 243 * scale, 296 * scale),
        radius=26 * scale,
        fill="#eef7ff",
        outline="#c8deef",
        width=2 * scale,
    )
    draw.rounded_rectangle(
        (397 * scale, 154 * scale, 539 * scale, 296 * scale),
        radius=26 * scale,
        fill="#f2f8fd",
        outline="#c8deef",
        width=2 * scale,
    )

    centered_text(
        draw,
        y=350 * scale,
        text="Your local materials and data remain on this Mac.",
        font=load_font(13 * scale),
        fill="#718396",
        width=width,
    )

    destination.parent.mkdir(parents=True, exist_ok=True)
    image.save(destination, format="TIFF", compression="tiff_lzw", dpi=(72 * scale, 72 * scale))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output_dir", type=Path)
    args = parser.parse_args()

    output_dir = args.output_dir.resolve()
    render_background(1, output_dir / "bg_1x.tiff")
    render_background(2, output_dir / "bg_2x.tiff")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
