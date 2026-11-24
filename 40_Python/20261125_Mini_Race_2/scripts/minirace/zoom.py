# -*- coding: utf-8 -*-
"""显示倍率档位（纯数学，可单测）。

7 档：-3 .. +3，共 7 档；+3 时显示比例为默认的 2 倍，-3 时为 0.5 倍。
档位不写配置，每次进入/切换地图重建 Renderer 时回到 0（默认）。
"""

MAX_LEVEL = 3


def clamp_level(level):
    return max(-MAX_LEVEL, min(MAX_LEVEL, int(level)))


def zoom_factor(level):
    """档位 -> 显示倍率（几何分档，+3 = 2.0，-3 = 0.5）。"""
    return 2.0 ** (clamp_level(level) / float(MAX_LEVEL))


def zoom_label(level):
    """HUD 标签：0 档为空串，其余形如 (+1) / (-2)。"""
    level = clamp_level(level)
    if level == 0:
        return ""
    return "(%+d)" % level


def adjust_level(level, delta):
    return clamp_level(level + int(delta))
