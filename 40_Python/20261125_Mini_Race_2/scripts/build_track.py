# -*- coding: utf-8 -*-
"""从示意图生成赛道的**中心线/边界/起点**数据（构建期工具，运行期不需要）。

输入：``images/track.jpg``（上海国际赛车场示意图，黑线=赛道，灰底，带 T1..T16 标签）
输出：``cfg/tracks/track.json``（world 坐标，米）+ ``docs/images/track_layout.png`` 预览图

做法：
1. 取黑色像素中最大的连通域（赛道），丢掉 T1..T16 文字；
2. 用赛道带的外轮廓/内轮廓取中点得到中心线（比骨架更稳，不会有歧义分支）；
3. 平滑中心线，找长直道：最长直道 = T13-T14（示意图比例记录 1135 m 题目约束），
   第二长直道 = T16-T1 主直道（方向从 T16 指向 T1，即比赛方向）；
   整体比例尺按"圈长 = 真实约 5451 m"标定（示意图各段比例与真实赛道有偏差）；
4. 起点 = 主直道从 **T1 端往回 1/3** 处；赛道宽度 15 m；
5. 输出世界坐标（起点为原点、y 轴向上）中心线点列、起点朝向、宽度等。

跑法::

    "D:\\Programming\\Python_dir_38\\python.exe" scripts\\build_track.py
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
DEFAULT_IMAGE = os.path.join(PROJECT, "images", "track.jpg")
DEFAULT_OUT = os.path.join(PROJECT, "cfg", "tracks", "track.json")
DEFAULT_PREVIEW = os.path.join(PROJECT, "docs", "images", "track_layout.png")

STRAIGHT_LENGTH_M = 1135.0
TARGET_LAP_M = 5451.0
TRACK_WIDTH_M = 15.0
# 示意图中 T6 发夹弯附近（像素坐标）：只在该区域做额外局部平滑
T6_SMOOTH_PIXEL = (1288.0, 242.0)
# 上海赛道 T1..T16 标签的近似像素位置（用于把弯道编号映射到中心线）
CORNER_LABEL_PIXELS = {
    1: (740.0, 40.0), 2: (930.0, 125.0), 3: (815.0, 105.0),
    4: (805.0, 250.0), 5: (1090.0, 155.0), 6: (1325.0, 280.0),
    7: (890.0, 365.0), 8: (1010.0, 615.0), 9: (785.0, 615.0),
    10: (805.0, 725.0), 11: (1170.0, 700.0), 12: (1245.0, 625.0),
    13: (1315.0, 705.0), 14: (200.0, 885.0), 15: (245.0, 780.0),
    16: (465.0, 760.0),
}
CIRCLE_OUT = os.path.join(PROJECT, "cfg", "tracks", "track_circle.json")
OVAL_OUT = os.path.join(PROJECT, "cfg", "tracks", "track_oval.json")


def build_oval_map(out_path, straight_m=1000.0, outer_radius_m=400.0,
                   width_m=25.0, spacing_m=4.0):
    """简单椭圆赛道：两段 1 km 直道 + 两端直径 800 m 半圆（外边界），宽 25 m。

    方向：顶直道向右行驶 → T1（右半圆）→ 底直道向左 → T2（左半圆）→ 回顶直道。
    起点：T1 前直道从 T1 往回 1/3 处。
    """
    radius = outer_radius_m - width_m * 0.5
    straight_end_x = straight_m * 0.5
    start_x = straight_end_x - straight_m / 3.0
    dense = []

    def add_straight(x0, x1, y, step=2.0):
        length = abs(x1 - x0)
        count = max(2, int(round(length / step)))
        for index in range(count):
            t = index / float(count)
            dense.append((x0 + (x1 - x0) * t, y))

    def add_arc(center_x, start_angle, end_angle, step=2.0):
        length = abs(end_angle - start_angle) * radius
        count = max(8, int(round(length / step)))
        for index in range(count):
            t = index / float(count)
            angle = start_angle + (end_angle - start_angle) * t
            dense.append((center_x + radius * math.cos(angle),
                          radius * math.sin(angle)))

    # 起点在顶直道，向右到 T1；右半圆；底直道向左；左半圆；回起点
    add_straight(start_x, straight_end_x, radius)
    add_arc(straight_end_x, math.pi * 0.5, -math.pi * 0.5)
    add_straight(straight_end_x, -straight_end_x, -radius)
    add_arc(-straight_end_x, -math.pi * 0.5, -math.pi * 1.5)
    add_straight(-straight_end_x, start_x, radius)
    points = np.array(dense, dtype=np.float64)
    centerline, lap_length = _cyclic_resample(points, spacing_m)
    centerline[0] = (round(start_x, 6), round(radius, 6))
    # 平移到"起点为原点、车头朝 +x"
    origin = centerline[0].copy()
    centerline = centerline - origin
    tangents = np.roll(centerline, -1, axis=0) - centerline
    lengths = np.hypot(tangents[:, 0], tangents[:, 1])
    tangents /= np.maximum(lengths, 1e-9)[:, None]
    normals = np.stack([-tangents[:, 1], tangents[:, 0]], axis=1)
    left = centerline + normals * (width_m * 0.5)
    right = centerline - normals * (width_m * 0.5)

    # T1/T2 的范围：右/左半圆的点（x 超过 ±straight_end_x 即半圆）
    t1_indices = [index for index, point in enumerate(centerline)
                  if point[0] >= straight_end_x - 1e-6]
    t2_indices = [index for index, point in enumerate(centerline)
                  if point[0] <= -straight_end_x + 1e-6]
    t1_start, t1_end = min(t1_indices), max(t1_indices)
    t2_start, t2_end = min(t2_indices), max(t2_indices)
    count = len(centerline)
    corners = [
        {"label": 1, "apex": (t1_start + t1_end) // 2,
         "start": t1_start, "end": t1_end, "direction": -1},
        {"label": 2, "apex": (t2_start + t2_end) // 2,
         "start": t2_start, "end": t2_end, "direction": -1},
    ]
    elements = [
        {"type": "corner", "label": "T1", "start": t1_start, "end": t1_end},
        {"type": "straight", "label": "-",
         "start": (t1_end + 1) % count, "end": (t2_start - 1) % count},
        {"type": "corner", "label": "T2", "start": t2_start, "end": t2_end},
        {"type": "straight", "label": "-",
         "start": (t2_end + 1) % count, "end": (t1_start - 1) % count},
    ]
    data = {
        "kind": "circuit",
        "name": "椭圆赛道",
        "display_name": "OVAL TEST TRACK",
        "width_m": width_m,
        "center": [0.0, 0.0],
        "centerline": [[round(float(x), 3), round(float(y), 3)]
                       for x, y in centerline],
        "left_edge": [[round(float(x), 3), round(float(y), 3)] for x, y in left],
        "right_edge": [[round(float(x), 3), round(float(y), 3)] for x, y in right],
        "corners": corners,
        "elements": elements,
        "start": {"x": 0.0, "y": 0.0, "heading_rad": 0.0},
        "reference": {
            "lap_length_m": round(lap_length, 1),
            "straight_length_m": straight_m,
            "outer_radius_m": outer_radius_m,
            "outer_diameter_m": round(outer_radius_m * 2.0, 1),
            "width_m": width_m,
            "start_fraction_before_t1": 1.0 / 3.0,
        },
    }
    with open(out_path, "w", encoding="utf-8") as handle:
        json.dump(data, handle, ensure_ascii=False, indent=1)
    print("已写出：%s（圈长 %.1f m，直道 %.0f m，外径 %.0f m，宽 %.0f m）" % (
        out_path, lap_length, straight_m, outer_radius_m * 2.0, width_m))
    return data


def build_circle_map(out_path, outer_radius_m=200.0, guide_radius_m=180.0,
                     point_count=720):
    """圆形试车场：直径 400 m 空地，内部直径 360 m 白色虚线（不是墙）。"""
    count = max(64, int(point_count))
    points = []
    for index in range(count):
        angle = math.pi * 0.5 + 2.0 * math.pi * index / count
        points.append([round(math.cos(angle) * guide_radius_m, 3),
                       round(math.sin(angle) * guide_radius_m, 3)])
    lap = 2.0 * math.pi * guide_radius_m
    data = {
        "kind": "circle",
        "name": "圆形试车场",
        "display_name": "CIRCLE TEST TRACK",
        "width_m": round(outer_radius_m * 2.0, 1),
        "center": [0.0, 0.0],
        "outer_radius_m": outer_radius_m,
        "guide_radius_m": guide_radius_m,
        "centerline": points,
        "start": {"x": 0.0, "y": round(guide_radius_m, 3),
                  "heading_rad": math.pi},
        "reference": {
            "lap_length_m": round(lap, 1),
            "reset_to_start": True,
            "outer_diameter_m": round(outer_radius_m * 2.0, 1),
            "guide_diameter_m": round(guide_radius_m * 2.0, 1),
        },
    }
    with open(out_path, "w", encoding="utf-8") as handle:
        json.dump(data, handle, ensure_ascii=False, indent=1)
    print("已写出：%s（Ø%.0f m 空地，Ø%.0f m 虚线，起点在顶部向左，圈长 %.0f m）" % (
        out_path, outer_radius_m * 2.0, guide_radius_m * 2.0, lap))
    return data


# ------------------------------------------------------------------ 中心线
def _track_mask(image_path):
    """取最大的黑色连通域（赛道），返回 (mask, 原图尺寸)。"""
    gray = np.asarray(Image.open(image_path).convert("L"), dtype=np.uint8)
    mask = (gray < 100).astype(np.uint8)
    labels, count = ndimage.label(mask)
    if count < 1:
        raise RuntimeError("图像里没有找到黑色赛道")
    sizes = ndimage.sum(mask, labels, range(1, count + 1))
    label = int(np.argmax(sizes)) + 1
    return (labels == label).astype(np.uint8), gray.shape


def _centerline_from_contours(mask):
    """赛道带外轮廓/内轮廓取中点 -> 有序中心线（像素坐标）。"""
    contours, hierarchy = cv2.findContours(mask, cv2.RETR_CCOMP,
                                           cv2.CHAIN_APPROX_NONE)
    if hierarchy is None:
        raise RuntimeError("没有找到赛道轮廓")
    outer = None
    inner = None
    for index, contour in enumerate(contours):
        if hierarchy[0][index][3] == -1:
            if outer is None or cv2.contourArea(contour) > cv2.contourArea(outer):
                outer = contour
        else:
            if inner is None or cv2.contourArea(contour) > cv2.contourArea(inner):
                inner = contour
    if outer is None or inner is None:
        raise RuntimeError("赛道不是闭合带状（缺少内/外轮廓）")
    outer_points = outer.reshape(-1, 2).astype(np.float64)
    inner_points = inner.reshape(-1, 2).astype(np.float64)
    tree = cKDTree(inner_points)
    distances, indices = tree.query(outer_points)
    midpoints = (outer_points + inner_points[indices]) * 0.5
    print("轮廓：外 %d 点 / 内 %d 点，中点间距平均 %.2f px（最大 %.1f）" % (
        len(outer_points), len(inner_points),
        float(np.mean(distances)), float(np.max(distances))))
    return midpoints


def _resample(points, step):
    """按弧长等间距重采样（不闭合）。"""
    deltas = np.hypot(*np.diff(points, axis=0).T)
    distances = np.concatenate(([0.0], np.cumsum(deltas)))
    total = distances[-1]
    count = max(2, int(round(total / step)) + 1)
    targets = np.linspace(0.0, total, count)
    result = np.empty((count, 2), dtype=np.float64)
    result[:, 0] = np.interp(targets, distances, points[:, 0])
    result[:, 1] = np.interp(targets, distances, points[:, 1])
    return result


def _circular_smooth(points, window):
    """周期滑动平均（窗口为奇数）。"""
    if window <= 1:
        return points
    half = window // 2
    padded = np.vstack([points[-half:], points, points[:half]])
    kernel = np.ones(window) / float(window)
    smoothed = np.empty_like(points)
    for axis in (0, 1):
        smoothed[:, axis] = np.convolve(padded[:, axis], kernel, mode="valid")
    return smoothed


def _cyclic_resample(points, step):
    """闭合路径按弧长等间距重采样，返回 (点列, 总长)。"""
    closed = np.vstack([points, points[0]])
    deltas = np.hypot(*np.diff(closed, axis=0).T)
    distances = np.concatenate(([0.0], np.cumsum(deltas)))
    total = distances[-1]
    count = max(8, int(round(total / step)))
    targets = np.linspace(0.0, total, count, endpoint=False)
    result = np.empty((count, 2), dtype=np.float64)
    result[:, 0] = np.interp(targets, distances, closed[:, 0])
    result[:, 1] = np.interp(targets, distances, closed[:, 1])
    return result, total


def _headings(points):
    """闭合中心线各点切线角（rad，指向下一点）。"""
    nxt = np.roll(points, -1, axis=0)
    return np.arctan2(nxt[:, 1] - points[:, 1], nxt[:, 0] - points[:, 0])


def _find_straights(points, spacing):
    """按曲率找长直道，返回 [(长度, 起点索引, 终点索引, 起点, 终点)]。"""
    count = len(points)
    headings = _headings(points)
    curvature = np.abs(np.diff(np.unwrap(headings), append=headings[0])) / spacing
    threshold = 0.0025  # 1/m，约 R > 400 m
    is_straight = curvature < threshold
    spans = []
    index = 0
    while index < count:
        if is_straight[index]:
            start = index
            while index < count and is_straight[index]:
                index += 1
            spans.append((start, index - 1))
        else:
            index += 1
    if spans and is_straight[0] and is_straight[-1] and len(spans) > 1:
        first_start, _ = spans[0]
        _, last_end = spans[-1]
        spans = spans[1:-1] + [(last_end, first_start)]
    merged = []
    for start, end in spans:
        if merged and ((start - merged[-1][1]) % count) * spacing < 25.0:
            merged[-1] = (merged[-1][0], end)
        else:
            merged.append((start, end))
    results = []
    for start, end in merged:
        steps = (end - start) % count + 1
        length = steps * spacing
        results.append((length, start, end, points[start].copy(), points[end].copy()))
    results.sort(key=lambda item: -item[0])
    return results[:8]


def _local_smooth(points, center_pixel, radius_px=90.0, window=21, passes=3,
                  spacing=2.0):
    """在指定像素点附近做局部平滑（用于消除 T6 这类急弯边界的锯齿）。

    只替换距离目标点 ``radius_px`` 以内的点，并用余弦权重渐变到原曲线，
    避免在平滑区域边缘产生新的折角。
    """
    count = len(points)
    center_index = int(np.argmin(
        (points[:, 0] - center_pixel[0]) ** 2
        + (points[:, 1] - center_pixel[1]) ** 2))
    half = max(2, int(round(radius_px / spacing)))
    kernel = np.ones(window) / float(window)
    half_window = window // 2
    smoothed = points.copy()
    for _ in range(max(1, passes)):
        padded = np.vstack([smoothed[-half_window:], smoothed,
                            smoothed[:half_window]])
        averaged = np.empty_like(smoothed)
        for axis in (0, 1):
            averaged[:, axis] = np.convolve(padded[:, axis], kernel, mode="valid")
        for offset in range(-half, half + 1):
            weight = 0.5 * (1.0 + math.cos(math.pi * offset / float(half)))
            index = (center_index + offset) % count
            smoothed[index] = (smoothed[index] * (1.0 - weight)
                               + averaged[index] * weight)
    return smoothed


def _curvature(points, span=4):
    """中心线各点曲率（1/m，逆时针为正）。"""
    count = len(points)
    result = np.zeros(count, dtype=np.float64)
    for index in range(count):
        a = points[(index - span) % count]
        b = points[index]
        c = points[(index + span) % count]
        angle0 = math.atan2(b[1] - a[1], b[0] - a[0])
        angle1 = math.atan2(c[1] - b[1], c[0] - b[0])
        delta = (angle1 - angle0 + math.pi) % (2.0 * math.pi) - math.pi
        distance = math.hypot(c[0] - a[0], c[1] - a[1])
        result[index] = delta / distance if distance > 1e-9 else 0.0
    return result


def _range_contains(start, end, index, count):
    if start <= end:
        return start <= index <= end
    return index >= start or index <= end


def _build_corner_elements(points, anchor_indices, min_corner_pts=12,
                           min_straight_pts=8):
    """根据曲率 + Tn 锚点，生成"弯 / 直道"交替的元素序列。

    - 弯道范围：从锚点向两侧扩展到曲率低于阈值处；低曲率弯有最小长度兜底；
    - 相邻弯之间以"曲率绝对值最小点"为界，并强制留出 min_straight_pts 的直道；
    - 同向组合弯/反向 S 弯都按这个边界切分，保证 5 要素窗口交替。
    """
    count = len(points)
    curvature = _curvature(points)
    labels = sorted(anchor_indices)
    anchors = [anchor_indices[label] for label in labels]
    # 每两个相邻弯之间曲率最小的点 = 直道中心/弯边界
    boundaries = []
    for index in range(len(labels)):
        start = anchors[index]
        end = anchors[(index + 1) % len(labels)]
        if end <= start:
            end += count
        best = start
        best_value = 1e9
        for extended in range(start, end + 1):
            value = abs(curvature[extended % count])
            if value < best_value:
                best_value = value
                best = extended
        boundaries.append(best % count)

    half = min_straight_pts // 2
    spans = []
    for index, label in enumerate(labels):
        apex = anchors[index]
        previous_boundary = boundaries[index - 1]
        next_boundary = boundaries[index]
        previous_ext = previous_boundary
        if previous_ext > apex:
            previous_ext -= count
        next_ext = next_boundary
        if next_ext < apex:
            next_ext += count
        threshold = max(0.0015, 0.30 * abs(curvature[apex]))
        start = apex
        while (start - 1 > previous_ext
               and abs(curvature[(start - 1) % count]) > threshold
               and apex - (start - 1) < 140):
            start -= 1
        end = apex
        while (end + 1 < next_ext
               and abs(curvature[(end + 1) % count]) > threshold
               and (end + 1) - apex < 140):
            end += 1
        # 低曲率弯（示意图标注但曲率很小）至少给一段最小长度
        while apex - start < min_corner_pts // 2:
            start -= 1
        while end - apex < min_corner_pts // 2:
            end += 1
        # 边界附近强制留直道
        start = max(start, previous_ext + half)
        end = min(end, next_ext - half)
        if end - start < min_corner_pts:
            middle = (start + end) // 2
            start = middle - min_corner_pts // 2
            end = middle + min_corner_pts // 2
        spans.append({
            "label": label,
            "apex": apex % count,
            "start": start % count,
            "end": end % count,
            "direction": 1 if curvature[apex] >= 0.0 else -1,
        })
    # 按标签顺序生成交替元素（最后一个直道跨过起点线）
    corners = []
    elements = []
    for index, span in enumerate(spans):
        corners.append(span)
        elements.append({"type": "corner", "label": "T%d" % span["label"],
                         "start": span["start"], "end": span["end"]})
        next_span = spans[(index + 1) % len(spans)]
        straight_start = (span["end"] + 1) % count
        straight_end = (next_span["start"] - 1) % count
        elements.append({"type": "straight", "label": "-",
                         "start": straight_start, "end": straight_end})
    return corners, elements


# ------------------------------------------------------------------ 主流程
def build(image_path, straight_m, width_m, target_lap_m):
    mask, shape = _track_mask(image_path)
    print("图像 %dx%d，赛道面积 %d px" % (shape[1], shape[0], int(mask.sum())))
    midpoints = _centerline_from_contours(mask)
    path = _resample(midpoints, 2.0)
    path = _circular_smooth(path, 25)
    # T6 在示意图上是一个很尖的发夹弯，轮廓中点法会留下小锯齿：局部再平滑一次
    path = _local_smooth(path, T6_SMOOTH_PIXEL, radius_px=180.0,
                         window=45, passes=5)
    path = _resample(path, 2.0)
    spacing = 2.0

    straights_px = _find_straights(path, spacing)
    print("候选直道：")
    for length, start, end, p0, p1 in straights_px:
        print("  %7.1f px  (%6.1f,%6.1f) -> (%6.1f,%6.1f)" % (
            length, p0[0], p0[1], p1[0], p1[1]))
    if len(straights_px) < 2:
        raise RuntimeError("没有找到两条长直道，无法定标")
    t13_length_px = straights_px[0][0]
    # 以"圈长 = 目标圈长"定整体比例尺（示意图各段比例与真实赛道有偏差，
    # 单靠某一段直道定标会让总圈长偏短；这里优先保证整圈长度）。
    closed = np.vstack([path, path[0]])
    perimeter_px = float(np.hypot(*np.diff(closed, axis=0).T).sum())
    scale = target_lap_m / perimeter_px
    print("比例尺：%.5f m/px（中心线 %.1f px -> 圈长 %.0f m）" % (
        scale, perimeter_px, target_lap_m))
    print("  T13-T14 直道（示意图）%.1f px -> 约 %.0f m（题目给定 %.0f m）" % (
        t13_length_px, t13_length_px * scale, straight_m))

    main_length_px, main_start, main_end, main_p0, main_p1 = straights_px[1]
    if main_p0[1] < main_p1[1]:
        t16_point, t1_point = main_p1, main_p0
    else:
        t16_point, t1_point = main_p0, main_p1
    # 路径方向必须是 T16 -> T1（比赛方向）
    n = len(path)
    forward = (main_end - main_start) % n
    path_goes_to_t1 = (main_p1[1] < main_p0[1])
    if not path_goes_to_t1:
        path = path[::-1]
        main_start, main_end = (n - 1 - main_end) % n, (n - 1 - main_start) % n
        forward = (main_end - main_start) % n
    print("主直道：%.1f px（%.0f m），T16 端 (%0.1f,%0.1f)，T1 端 (%0.1f,%0.1f)" % (
        main_length_px, main_length_px * scale,
        t16_point[0], t16_point[1], t1_point[0], t1_point[1]))

    # 起点：从 T1 端往回 1/3（即 T16→T1 直道的 2/3 处），车头仍朝 T1（比赛方向）
    start_point = t1_point + (t16_point - t1_point) * 0.33
    print("起点（像素）：(%0.1f,%0.1f)（从 T1 端往回 1/3）" % (
        start_point[0], start_point[1]))

    origin = start_point.copy()

    def make_world(scale_value):
        world = np.empty_like(path)
        world[:, 0] = (path[:, 0] - origin[0]) * scale_value
        world[:, 1] = -(path[:, 1] - origin[1]) * scale_value
        distances = np.hypot(world[:, 0], world[:, 1])
        start_index = int(np.argmin(distances))
        world = np.roll(world, -start_index, axis=0)
        centerline, lap = _cyclic_resample(world, 4.0)
        centerline[0] = (0.0, 0.0)
        heading = math.atan2(centerline[5][1] - centerline[-1][1],
                             centerline[5][0] - centerline[-1][0])
        return centerline, lap, heading

    centerline, lap_length, heading = make_world(scale)
    if abs(lap_length - target_lap_m) > 0.5:
        scale *= target_lap_m / lap_length
        centerline, lap_length, heading = make_world(scale)
    print("世界坐标：中心线 %d 点，圈长 %.1f m，起点朝向 %.1f°" % (
        len(centerline), lap_length, math.degrees(heading)))

    # 把 T1..T16 标签像素映射到最终中心线索引，用来给弯道编号
    anchor_indices = {}
    for label, (px, py) in CORNER_LABEL_PIXELS.items():
        wx = (px - origin[0]) * scale
        wy = -(py - origin[1]) * scale
        index = int(np.argmin((centerline[:, 0] - wx) ** 2
                              + (centerline[:, 1] - wy) ** 2))
        anchor_indices[label] = index
    print("弯道标签索引：%s" % ", ".join(
        "T%d:%d" % (label, index)
        for label, index in sorted(anchor_indices.items(),
                                   key=lambda item: item[1])))
    corners, elements = _build_corner_elements(centerline, anchor_indices)
    print("弯道：%s" % ", ".join(
        "T%d[%d..%d]" % (item["label"], item["start"], item["end"])
        for item in corners))

    tangents = np.roll(centerline, -1, axis=0) - centerline
    length = np.hypot(tangents[:, 0], tangents[:, 1])
    tangents /= np.maximum(length, 1e-9)[:, None]
    normals = np.stack([-tangents[:, 1], tangents[:, 0]], axis=1)
    half = width_m * 0.5
    left = centerline + normals * half
    right = centerline - normals * half
    straight_info = [(round(item[0] * scale, 1),
                      [round(float(value), 2) for value in item[3]],
                      [round(float(value), 2) for value in item[4]])
                     for item in straights_px]
    return {
        "name": "Shanghai International Circuit (from images/track.jpg)",
        "source_image": os.path.relpath(image_path, PROJECT).replace("\\", "/"),
        "reference": {
            "t13_t14_straight_px": round(t13_length_px, 2),
            "t13_t14_straight_m": round(t13_length_px * scale, 1),
            "requested_t13_t14_m": straight_m,
            "target_lap_length_m": target_lap_m,
            "scale_m_per_px": scale,
            "main_straight_px": round(main_length_px, 2),
            "main_straight_m": round(main_length_px * scale, 1),
            "lap_length_m": round(lap_length, 1),
            "start_fraction_from_t1": 0.33,
        },
        "width_m": width_m,
        "centerline": [[round(float(x), 3), round(float(y), 3)]
                       for x, y in centerline],
        "corners": corners,
        "elements": elements,
        "left_edge": [[round(float(x), 3), round(float(y), 3)] for x, y in left],
        "right_edge": [[round(float(x), 3), round(float(y), 3)] for x, y in right],
        "start": {
            "x": 0.0,
            "y": 0.0,
            "heading_rad": heading,
        },
        "straights": straight_info,
    }


def draw_preview(data, out_path, scale_px_per_m=0.5):
    """把中心线/边界/起点画成预览图（文档用）。"""
    centerline = np.array(data["centerline"], dtype=np.float64)
    left = np.array(data["left_edge"], dtype=np.float64)
    right = np.array(data["right_edge"], dtype=np.float64)
    all_points = np.vstack([centerline, left, right])
    margin = 40
    min_xy = all_points.min(axis=0)
    max_xy = all_points.max(axis=0)
    width = int((max_xy[0] - min_xy[0]) * scale_px_per_m) + margin * 2
    height = int((max_xy[1] - min_xy[1]) * scale_px_per_m) + margin * 2
    canvas = Image.new("RGB", (width, height), (76, 128, 62))
    draw = ImageDraw.Draw(canvas)

    def to_px(point):
        return (margin + (point[0] - min_xy[0]) * scale_px_per_m,
                margin + (max_xy[1] - point[1]) * scale_px_per_m)

    track_px = [to_px(point) for point in centerline]
    track_px.append(track_px[0])
    track_width = max(2, int(round(data["width_m"] * scale_px_per_m)))
    draw.line(track_px, fill=(235, 235, 235), width=track_width + 3, joint="curve")
    draw.line(track_px, fill=(58, 58, 60), width=track_width, joint="curve")
    start = to_px((0.0, 0.0))
    heading = data["start"]["heading_rad"]
    nose = to_px((math.cos(heading) * 120.0, math.sin(heading) * 120.0))
    draw.line([start, nose], fill=(235, 80, 60), width=3)
    draw.ellipse([start[0] - 4, start[1] - 4, start[0] + 4, start[1] + 4],
                 fill=(235, 80, 60))
    canvas.save(out_path, "PNG")
    print("预览图：%s（%dx%d）" % (out_path, width, height))


def main():
    parser = argparse.ArgumentParser(description="从 images/track.jpg 生成 cfg/tracks/track.json")
    parser.add_argument("--image", default=DEFAULT_IMAGE)
    parser.add_argument("--out", default=DEFAULT_OUT)
    parser.add_argument("--preview", default=DEFAULT_PREVIEW)
    parser.add_argument("--straight-m", type=float, default=STRAIGHT_LENGTH_M,
                        help="示意图中 T13-T14 直道的题目给定长度，仅记录/参考")
    parser.add_argument("--lap-m", type=float, default=TARGET_LAP_M,
                        help="整体比例尺的目标圈长（默认 5451 m）")
    parser.add_argument("--width-m", type=float, default=TRACK_WIDTH_M)
    parser.add_argument("--circle", action="store_true",
                        help="不读底图，只生成圆形试车场 cfg/tracks/track_circle.json")
    parser.add_argument("--oval", action="store_true",
                        help="不读底图，只生成椭圆赛道 cfg/tracks/track_oval.json")
    parser.add_argument("--circle-out", default=CIRCLE_OUT)
    parser.add_argument("--oval-out", default=OVAL_OUT)
    args = parser.parse_args()
    if args.circle:
        build_circle_map(args.circle_out)
        return 0
    if args.oval:
        build_oval_map(args.oval_out)
        return 0
    data = build(args.image, args.straight_m, args.width_m, args.lap_m)
    with open(args.out, "w", encoding="utf-8") as handle:
        json.dump(data, handle, ensure_ascii=False, indent=1)
    print("已写出：%s" % args.out)
    if args.preview:
        draw_preview(data, args.preview)
    return 0


if __name__ == "__main__":
    sys.exit(main())
