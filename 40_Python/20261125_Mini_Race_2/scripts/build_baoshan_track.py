# -*- coding: utf-8 -*-
"""从 images/track_baoshan_kartin.bmp 提取宝山卡丁车赛道。

这是构建期脚本，不参与游戏运行：
1. 取灰色沥青带（排除黑色背景/白色边线）的最大连通域；
2. 用赛道带内/外轮廓中点得到中心线，平滑、重采样；
3. 中心线目标长度 1264 m（公开资料：赛道总长 1264 m）标定比例尺；
4. 起点取底部主直道的发车格/黑白线附近（图像像素约 x=277），
   行驶方向沿底部直道向右（T16 -> T1）。
"""
import json
import math
import os
import sys

import cv2
import numpy as np
from PIL import Image, ImageDraw
from scipy import ndimage

PROJECT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(PROJECT, "scripts"))

import build_track as bt  # noqa: E402

IMAGE = os.path.join(PROJECT, "images", "track_baoshan_kartin.bmp")
OUT = os.path.join(PROJECT, "cfg", "tracks", "track_baoshan.json")
PREVIEW = os.path.join(PROJECT, "data", "track_baoshan_layout.png")
LAP_M = 1264.0
# 由图像外/内轮廓间距估计：平均约 27.6 px，比例尺约 0.649 m/px。
WIDTH_M = 18.0
START_PIXEL = (276.9, 264.38)  # 底部发车格/黑白线中央


def track_mask(image_path):
    rgb = np.asarray(Image.open(image_path).convert("RGB"))
    gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)
    mask = ((gray > 30) & (gray < 200)).astype(np.uint8)
    _count, labels, stats, _centroids = cv2.connectedComponentsWithStats(mask, 8)
    label = int(np.argmax(stats[1:, 4])) + 1
    return (labels == label).astype(np.uint8)


def build():
    mask = track_mask(IMAGE)
    print("track pixels:", int(mask.sum()))
    midpoints = bt._centerline_from_contours(mask)
    path = bt._resample(midpoints, 2.0)
    path = bt._circular_smooth(path, 31)
    path = bt._resample(path, 2.0)

    closed = np.vstack([path, path[0]])
    perimeter_px = float(np.hypot(*np.diff(closed, axis=0).T).sum())
    scale = LAP_M / perimeter_px
    print("centerline %.1f px -> %.2f m/px" % (perimeter_px, scale))

    # 起点：取离用户确认的发车格中央最近的像素点
    target = np.asarray(START_PIXEL, dtype=np.float64)
    start_index = int(np.argmin(((path - target) ** 2).sum(axis=1)))
    # 保证沿底部直道向右（图像 x 增加）
    tangent = path[(start_index + 2) % len(path)] - path[start_index]
    if tangent[0] < 0.0:
        path = path[::-1]
        start_index = (len(path) - 1 - start_index) % len(path)
        tangent = path[(start_index + 2) % len(path)] - path[start_index]

    origin_px = path[start_index].copy()
    world = np.empty_like(path)
    world[:, 0] = (path[:, 0] - origin_px[0]) * scale
    world[:, 1] = -(path[:, 1] - origin_px[1]) * scale
    world = np.roll(world, -start_index, axis=0)
    centerline, lap_length = bt._cyclic_resample(world, 4.0)
    centerline[0] = (0.0, 0.0)
    heading = math.atan2(centerline[5][1] - centerline[-1][1],
                         centerline[5][0] - centerline[-1][0])

    # 用同样像素比例估计宽度（外/内轮廓最近点平均距离）
    contours, hierarchy = cv2.findContours(mask, cv2.RETR_CCOMP,
                                           cv2.CHAIN_APPROX_NONE)
    outer = max((c for i, c in enumerate(contours) if hierarchy[0][i][3] == -1),
                key=cv2.contourArea)
    inner = max((c for i, c in enumerate(contours) if hierarchy[0][i][3] != -1),
                key=cv2.contourArea)
    from scipy.spatial import cKDTree
    outer_pts = outer.reshape(-1, 2).astype(np.float64)
    inner_pts = inner.reshape(-1, 2).astype(np.float64)
    distances, _ = cKDTree(inner_pts).query(outer_pts)
    width_px = float(np.mean(distances))
    width_m = WIDTH_M
    print("estimated width %.1f px -> %.1f m (use %.1f m)" % (
        width_px, width_px * scale, width_m))

    tangents = np.roll(centerline, -1, axis=0) - centerline
    lengths = np.hypot(tangents[:, 0], tangents[:, 1])
    tangents /= np.maximum(lengths, 1e-9)[:, None]
    normals = np.stack([-tangents[:, 1], tangents[:, 0]], axis=1)
    half = width_m * 0.5
    left = centerline + normals * half
    right = centerline - normals * half

    data = {
        "kind": "circuit",
        "name": "宝山卡丁车场",
        "display_name": "BAOSHAN KARTING",
        "source_image": "images/track_baoshan_kartin.bmp",
        "width_m": width_m,
        "center": [0.0, 0.0],
        "centerline": [[round(float(x), 3), round(float(y), 3)]
                       for x, y in centerline],
        "left_edge": [[round(float(x), 3), round(float(y), 3)]
                      for x, y in left],
        "right_edge": [[round(float(x), 3), round(float(y), 3)]
                       for x, y in right],
        "corners": [],
        "elements": [],
        "start": {"x": 0.0, "y": 0.0, "heading_rad": heading},
        "reference": {
            "lap_length_m": round(lap_length, 1),
            "requested_lap_m": LAP_M,
            "lap_length_note": "public track length 1264 m",
            "scale_m_per_px": round(scale, 6),
            "centerline_perimeter_px": round(perimeter_px, 2),
            "estimated_width_px": round(width_px, 2),
            "estimated_width_m": round(width_px * scale, 2),
            "width_m": width_m,
            "start_pixel": [round(float(v), 2) for v in origin_px],
            "start_from": "bottom start grid / checkered line",
            "direction": "bottom straight left -> right (T16 -> T1)",
            "corner_count_from_labels": 15,
            "corner_post_count": 1,
        },
    }
    return data


def draw_preview(data, path):
    centerline = np.array(data["centerline"], dtype=np.float64)
    left = np.array(data["left_edge"], dtype=np.float64)
    right = np.array(data["right_edge"], dtype=np.float64)
    all_points = np.vstack([centerline, left, right])
    margin = 40
    scale_px = 2.0
    min_xy = all_points.min(axis=0)
    max_xy = all_points.max(axis=0)
    width = int((max_xy[0] - min_xy[0]) * scale_px) + margin * 2
    height = int((max_xy[1] - min_xy[1]) * scale_px) + margin * 2
    image = Image.new("RGB", (width, height), (76, 128, 62))
    draw = ImageDraw.Draw(image)

    def to_px(point):
        return (margin + (point[0] - min_xy[0]) * scale_px,
                margin + (max_xy[1] - point[1]) * scale_px)

    track = [to_px(point) for point in centerline]
    track.append(track[0])
    track_width = max(2, int(round(data["width_m"] * scale_px)))
    draw.line(track, fill=(235, 235, 235), width=track_width + 3, joint="curve")
    draw.line(track, fill=(58, 58, 60), width=track_width, joint="curve")
    start = to_px((0.0, 0.0))
    heading = data["start"]["heading_rad"]
    nose = to_px((math.cos(heading) * 80.0, math.sin(heading) * 80.0))
    draw.line([start, nose], fill=(235, 80, 60), width=3)
    draw.ellipse([start[0] - 4, start[1] - 4, start[0] + 4, start[1] + 4],
                 fill=(235, 80, 60))
    image.save(path, "PNG")
    print("preview:", path, image.size)


if __name__ == "__main__":
    data = build()
    with open(OUT, "w", encoding="utf-8") as handle:
        json.dump(data, handle, ensure_ascii=False, indent=1)
    print("wrote:", OUT)
    draw_preview(data, PREVIEW)
