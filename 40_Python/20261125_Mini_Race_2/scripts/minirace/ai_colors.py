# -*- coding: utf-8 -*-
"""AI 车辆静态配色表（2D/3D 共用）。

顺序固定：红、黄、绿、蓝、品红、橙、青、深蓝、浅灰、白。
绿色特意选高亮、偏青的鲜绿，和草地 (74, 124, 64) 拉开。
"""

AI_COLOR_NAMES = (
    "red",
    "yellow",
    "green",
    "blue",
    "magenta",
    "orange",
    "cyan",
    "dark_blue",
    "light_gray",
    "white",
)

AI_COLORS = (
    (232, 48, 48),      # 红
    (248, 208, 32),     # 黄
    (48, 225, 105),     # 鲜绿（和草地明显区分）
    (48, 120, 255),     # 蓝
    (235, 70, 220),     # 品红
    (255, 145, 30),     # 橙
    (40, 220, 230),     # 青
    (30, 70, 165),      # 深蓝
    (190, 198, 210),    # 浅灰
    (245, 248, 252),    # 白
)

AI_OUTLINE = (20, 24, 30)


def ai_rgb(index):
    """返回 0~255 的 RGB；超过 10 个循环使用。"""
    return AI_COLORS[int(index) % len(AI_COLORS)]


def ai_float(index):
    """返回 0~1 的 RGB，供 Panda3D 材质使用。"""
    return tuple(value / 255.0 for value in ai_rgb(index))
