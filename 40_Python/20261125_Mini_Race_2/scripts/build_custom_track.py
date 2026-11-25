# -*- coding: utf-8 -*-
"""从卫星图/示意图生成自定义赛道的中心线/边界 JSON。

适用于和宝山图类似的图：灰/深灰赛道、黑/浅色背景、白色边线。
不是全自动“理解任意图片”：需要你给出圈长；宽度可自动估计也可以手动给；
起点可以给图片像素坐标，脚本会把中心线平移成“起点为原点”。

典型流程::

    python scripts/build_custom_track.py ^
        --image images/my_track.png ^
        --lap-m 1200 --width-m 12 ^
        --start-pixel 300,400 --direction right ^
        --out cfg/tracks/track_mytrack.json ^
        --name "我的赛道" --display-name "MY TRACK"

    python scripts/annotate_track.py ^
        --image images/my_track.png ^
        --track cfg/tracks/track_mytrack.json

然后手动把地图加入 cfg/sim.json 的 maps.list。
"""
import argparse
import json
import math
import os
import sys

import cv2
import numpy as np
from PIL import Image, ImageDraw
from scipy import ndimage
from scipy.spatial import cKDTree

PROJECT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(PROJECT, "scripts"))

import build_track as bt  # noqa: E402


def extract_mask(image_path, low=30, high=200):
    rgb = np.asarray(Image.open(image_path).convert("RGB"))
    gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)
    mask = ((gray > low) & (gray < high)).astype(np.uint8)
    _count, labels, stats, _centroids = cv2.connectedComponentsWithStats(mask, 8)
    label = int(np.argmax(stats[1:, 4])) + 1
    return (labels == label).astype(np.uint8)


def estimate_width(mask, scale):
    contours, hierarchy = cv2.findContours(
        mask, cv2.RETR_CCOMP, cv2.CHAIN_APPROX_NONE)
    outer = max((c for i, c in enumerate(contours)
                 if hierarchy[0][i][3] == -1), key=cv2.contourArea)
    inner = max((c for i, c in enumerate(contours)
                 if hierarchy[0][i][3] != -1), key=cv2.contourArea)
    outer_pts = outer.reshape(-1, 2).astype(np.float64)
    inner_pts = inner.reshape(-1, 2).astype(np.float64)
    distances, _ = cKDTree(inner_pts).query(outer_pts)
    width_px = float(np.mean(distances))
    return width_px, width_px * scale


def build(image_path, lap_m, width_m=None, start_pixel=None,
          direction="right", low=30, high=200, smooth_window=31,
          name="自定义赛道", display_name="CUSTOM TRACK"):
    mask = extract_mask(image_path, low, high)
    midpoints = bt._centerline_from_contours(mask)
    path = bt._resample(midpoints, 2.0)
    path = bt._circular_smooth(path, max(1, int(smooth_window)))
    path = bt._resample(path, 2.0)

    closed = np.vstack([path, path[0]])
    perimeter_px = float(np.hypot(*np.diff(closed, axis=0).T).sum())
    scale = float(lap_m) / perimeter_px

    if start_pixel is None:
        start_index = int(np.argmax(path[:, 1]))
    else:
        target = np.asarray(start_pixel, dtype=np.float64)
        start_index = int(np.argmin(((path - target) ** 2).sum(axis=1)))
    tangent = path[(start_index + 2) % len(path)] - path[start_index]
    want_right = direction != "left"
    if (tangent[0] < 0.0) == want_right:
        path = path[::-1]
        start_index = (len(path) - 1 - start_index) % len(path)
        tangent = path[(start_index + 2) % len(path)] - path[start_index]
        if tangent[0] < 0.0:
            path = path[::-1]
            start_index = (len(path) - 1 - start_index) % len(path)

    origin_px = path[start_index].copy()
    world = np.empty_like(path)
    world[:, 0] = (path[:, 0] - origin_px[0]) * scale
    world[:, 1] = -(path[:, 1] - origin_px[1]) * scale
    world = np.roll(world, -start_index, axis=0)
    centerline, lap_length = bt._cyclic_resample(world, 4.0)
    centerline[0] = (0.0, 0.0)
    heading = math.atan2(centerline[5][1] - centerline[-1][1],
                         centerline[5][0] - centerline[-1][0])

    width_px, width_estimated = estimate_width(mask, scale)
    if width_m is None:
        width_m = max(4.0, round(width_estimated * 2.0) / 2.0)
    width_m = float(width_m)

    tangents = np.roll(centerline, -1, axis=0) - centerline
    lengths = np.hypot(tangents[:, 0], tangents[:, 1])
    tangents /= np.maximum(lengths, 1e-9)[:, None]
    normals = np.stack([-tangents[:, 1], tangents[:, 0]], axis=1)
    half = width_m * 0.5
    left = centerline + normals * half
    right = centerline - normals * half

    return {
        "kind": "circuit",
        "name": name,
        "display_name": display_name,
        "source_image": os.path.relpath(image_path, PROJECT).replace("\\", "/"),
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
            "requested_lap_m": float(lap_m),
            "scale_m_per_px": round(scale, 8),
            "start_pixel": [round(float(v), 3) for v in origin_px],
            "centerline_perimeter_px": round(perimeter_px, 3),
            "estimated_width_px": round(width_px, 3),
            "estimated_width_m": round(width_estimated, 3),
            "width_m": round(width_m, 3),
            "start_from": ("given start pixel" if start_pixel is not None
                           else "lowest image point"),
            "direction": direction,
            "corner_post_count": 1,
        },
    }


def draw_preview(data, path, scale_px_per_m=1.0):
    centerline = np.array(data["centerline"])
    left = np.array(data["left_edge"])
    right = np.array(data["right_edge"])
    points = np.vstack([centerline, left, right])
    margin = 40
    min_xy, max_xy = points.min(axis=0), points.max(axis=0)
    width = int((max_xy[0] - min_xy[0]) * scale_px_per_m) + margin * 2
    height = int((max_xy[1] - min_xy[1]) * scale_px_per_m) + margin * 2
    image = Image.new("RGB", (max(1, width), max(1, height)), (76, 128, 62))
    draw = ImageDraw.Draw(image)

    def to_px(point):
        return (margin + (point[0] - min_xy[0]) * scale_px_per_m,
                margin + (max_xy[1] - point[1]) * scale_px_per_m)

    track = [to_px(point) for point in centerline] + [to_px(centerline[0])]
    track_width = max(2, int(round(data["width_m"] * scale_px_per_m)))
    draw.line(track, fill=(235, 235, 235), width=track_width + 3, joint="curve")
    draw.line(track, fill=(58, 58, 60), width=track_width, joint="curve")
    start = to_px((0.0, 0.0))
    heading = data["start"]["heading_rad"]
    draw.line([start, to_px((math.cos(heading) * 60.0,
                             math.sin(heading) * 60.0))],
              fill=(235, 80, 60), width=3)
    draw.ellipse([start[0] - 4, start[1] - 4, start[0] + 4, start[1] + 4],
                 fill=(235, 80, 60))
    image.save(path, "PNG")


def main():
    parser = argparse.ArgumentParser(description="从图片生成自定义赛道 JSON")
    parser.add_argument("--image", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--lap-m", type=float, required=True,
                        help="目标中心线长度（米）")
    parser.add_argument("--width-m", type=float, default=None,
                        help="赛道宽度；不给则按图片外/内轮廓估计")
    parser.add_argument("--start-pixel", default=None,
                        help="起点图片像素 x,y；不给则取图像最下方中心线点")
    parser.add_argument("--direction", choices=("right", "left"), default="right",
                        help="起点处的行驶方向（图像 x 增大/减小）")
    parser.add_argument("--name", default="自定义赛道")
    parser.add_argument("--display-name", default="CUSTOM TRACK")
    parser.add_argument("--mask-low", type=float, default=30.0)
    parser.add_argument("--mask-high", type=float, default=200.0)
    parser.add_argument("--smooth", type=int, default=31)
    parser.add_argument("--preview", default=None)
    args = parser.parse_args()
    start = None
    if args.start_pixel:
        x, y = args.start_pixel.split(",")
        start = (float(x), float(y))
    data = build(args.image, args.lap_m, args.width_m, start,
                 args.direction, args.mask_low, args.mask_high,
                 args.smooth, args.name, args.display_name)
    with open(args.out, "w", encoding="utf-8") as handle:
        json.dump(data, handle, ensure_ascii=False, indent=1)
        handle.write("\n")
    print("wrote: %s（中心线 %.1f m，宽度 %.1f m，中心线 %d 点）" % (
        args.out, data["reference"]["lap_length_m"], data["width_m"],
        len(data["centerline"])))
    if args.preview:
        draw_preview(data, args.preview)
        print("preview:", args.preview)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
