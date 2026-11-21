"""用 Pillow 画对比柱状图（不引入 matplotlib，保持零额外依赖）。"""

from __future__ import annotations

import math
from pathlib import Path
from typing import Mapping, Sequence

from PIL import Image, ImageDraw, ImageFont

FONT_CANDIDATES = [
    r"C:\Windows\Fonts\msyh.ttc",
    r"C:\Windows\Fonts\msyhbd.ttc",
    r"C:\Windows\Fonts\simhei.ttf",
    r"C:\Windows\Fonts\simsun.ttc",
    r"C:\Windows\Fonts\arial.ttf",
    "/System/Library/Fonts/PingFang.ttc",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc",
]

#: 蓝→深蓝，对应 1/2/4 部电梯
DEFAULT_PALETTE = ["#9ecae1", "#4292c6", "#08519c", "#f16913"]

INK = "#222222"
MUTED = "#6b7280"
GRID = "#e5e7eb"


def _font(size: int) -> ImageFont.FreeTypeFont:
    for candidate in FONT_CANDIDATES:
        try:
            if Path(candidate).exists():
                return ImageFont.truetype(candidate, size)
        except OSError:
            continue
    return ImageFont.load_default()


def _nice_ceiling(value: float) -> float:
    if value <= 0:
        return 1.0
    exponent = math.floor(math.log10(value))
    base = 10 ** exponent
    for mult in (1, 1.2, 1.5, 2, 2.5, 3, 4, 5, 6, 8, 10):
        if value <= base * mult:
            return base * mult
    return base * 10


def grouped_bar_chart(
    path: str | Path,
    group_labels: Sequence[str],
    series: Mapping[str, Sequence[float]],
    *,
    title: str,
    ylabel: str,
    width: int = 1500,
    height: int = 760,
    palette: Sequence[str] = DEFAULT_PALETTE,
    value_format: str = "{:.0f}",
    bar_value_suffix: str = "",
    skip_zero: bool = False,
) -> Path:
    """画分组柱状图：x 轴是 ``group_labels``，每组里每个系列一根柱子。"""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)

    labels = list(series.keys())
    values = [list(series[label]) for label in labels]
    ymax = _nice_ceiling(max(max(v) for v in values) * 1.08)

    image = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(image)

    title_font = _font(30)
    axis_font = _font(17)
    tick_font = _font(16)
    value_font = _font(14)
    legend_font = _font(17)

    left, right, top, bottom = 110, 50, 110, 150
    plot_w = width - left - right
    plot_h = height - top - bottom

    def y_of(value: float) -> float:
        return top + plot_h - plot_h * (value / ymax)

    # 标题
    title_w = draw.textlength(title, font=title_font)
    draw.text(((width - title_w) / 2, 34), title, font=title_font, fill=INK)
    draw.text((left, top - 34), ylabel, font=axis_font, fill=MUTED)

    # 网格与 y 轴刻度
    steps = 5
    for i in range(steps + 1):
        value = ymax * i / steps
        y = y_of(value)
        draw.line([(left, y), (left + plot_w, y)], fill=GRID, width=1)
        text = value_format.format(value)
        tw = draw.textlength(text, font=tick_font)
        draw.text((left - 14 - tw, y - 10), text, font=tick_font, fill=MUTED)

    # 柱子和 x 轴标签
    group_w = plot_w / len(group_labels)
    bar_w = group_w * 0.78 / len(labels)
    for gi, group in enumerate(group_labels):
        group_x = left + gi * group_w
        for si, label in enumerate(labels):
            value = values[si][gi]
            if skip_zero and value <= 0:
                continue
            x0 = group_x + group_w * 0.11 + si * bar_w
            x1 = x0 + bar_w * 0.9
            y0 = y_of(value)
            color = palette[si % len(palette)]
            draw.rectangle([x0, y0, x1, top + plot_h], fill=color)

            text = value_format.format(value) + bar_value_suffix
            tw = draw.textlength(text, font=value_font)
            draw.text((x0 + (x1 - x0 - tw) / 2, y0 - 22), text, font=value_font, fill=INK)

        label_w = draw.textlength(group, font=tick_font)
        draw.text(
            (group_x + (group_w - label_w) / 2, top + plot_h + 14),
            group,
            font=tick_font,
            fill=INK,
        )

    # 轴线
    draw.line([(left, top), (left, top + plot_h)], fill="#9ca3af", width=2)
    draw.line([(left, top + plot_h), (left + plot_w, top + plot_h)], fill="#9ca3af", width=2)

    # 图例
    legend_y = height - 62
    swatch = 22
    gap = 14
    widths = [swatch + 8 + draw.textlength(label, font=legend_font) for label in labels]
    total_w = sum(widths) + gap * (len(labels) - 1)
    x = (width - total_w) / 2
    for si, label in enumerate(labels):
        draw.rectangle([x, legend_y, x + swatch, legend_y + swatch], fill=palette[si % len(palette)])
        draw.text((x + swatch + 8, legend_y + 1), label, font=legend_font, fill=INK)
        x += widths[si] + gap

    image.save(path)
    return path
