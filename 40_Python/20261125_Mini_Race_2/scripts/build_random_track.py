# -*- coding: utf-8 -*-
"""按边界条件随机生成闭环赛道。

设计：
- 中心线由「直道 + 平滑曲率弯」组成；
- 每个弯的曲率使用 ``sin²(π t)`` 车削：两端曲率为 0、导数为 0，
  弯内曲率只有一个极值（弯心），因此整条中心线的 κ 和 dκ/ds 连续；
- 直道曲率为 0；
- 弯与弯之间保留最小直道；
- 用闭合多边形（随机转角 + 线性规划边 length）保证闭环；
- 生成后检查总长、宽度、弯数、最长直道、发卡弯、边界曲率上界、
  边界自交。

生成结果写入 JSON，并在 ``reference.generator`` 里记录种子和全部边界参数，
可用同一参数和种子复现。
"""
import argparse
import json
import math
import os
import sys

import numpy as np
from PIL import Image, ImageDraw
from scipy.optimize import linprog
from scipy.spatial import cKDTree
from shapely.geometry import LineString

PROJECT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(PROJECT, "scripts"))

import build_track as bt  # noqa: E402
import track_manager as tm  # noqa: E402

# 生成器独立版本号：只保证同一版本内 seed 可复现。
# 规则约定：以后任何会改变生成结果/输出结构的修改，都必须提升该版本号。
GENERATOR_VERSION = "1.0.0"

DEFAULTS = {
    "lap_length_m": [1200.0, 1800.0],
    "width_m": [15.0, 25.0],
    "corner_count": [8, 12],
    "min_straight_m": 12.0,
    "min_longest_straight_m": 0.0,  # 只限制最长直道；0=不限制
    "max_straight_m": 300.0,  # 0=不限制
    "straight_kappa_threshold": 0.0025,  # 1/m，R > 400 m 视为直道
    "hairpin_boundary_curvature": 0.12,  # 1/m，内侧边界 R < 8.33 m 视为发卡
    "min_hairpin_count": 1,  # 至少几个发卡弯；0=不限制
    "max_left_right_diff": None,  # |左弯-右弯|上限；None=不限制，0=必须相等
    "boundary_max_curvature": 0.30,  # 1/m，边界 R > 3.33 m
    "postprocess_straight_kappa": 0.0015,  # 后处理：严格直道阈值
    "postprocess_blend_points": 3,
    "corner_samples": 120,
    "max_attempts": 400,
}

# 弯道曲率最大值的默认范围（特殊发卡弯单独取高值）
NORMAL_KMAX_RANGE = (0.022, 0.065)
RADIAL_RANGE = (0.25, 1.0)
ANGLE_JITTER = 0.45


def _turn_directions(turns):
    angles = [0.0]
    for turn in turns[:-1]:
        angles.append(angles[-1] + turn)
    return angles


def _corner_shape(turn, kmax, samples):
    """返回 (local points, length, trim_in, trim_out, apex point)。

    曲率 κ(t) = kmax * sin²(pi t)，t in [0,1]；
    起点切线 +x，终点方向旋转 turn。
    """
    if abs(turn) < 1e-6 or kmax <= 1e-9:
        return np.zeros((2, 2)), 0.0, 0.0, 0.0, np.zeros(2)
    length = 2.0 * abs(turn) / kmax
    t = np.linspace(0.0, 1.0, samples)
    # normalized heading: theta(t) = turn * (t - sin(2πt)/(2π))
    theta = turn * (t - np.sin(2.0 * np.pi * t) / (2.0 * np.pi))
    ds = length / float(max(1, samples - 1))
    points = np.zeros((samples, 2))
    for i in range(1, samples):
        a = theta[i - 1]
        b = theta[i]
        points[i, 0] = points[i - 1, 0] + ds * 0.5 * (math.cos(a) + math.cos(b))
        points[i, 1] = points[i - 1, 1] + ds * 0.5 * (math.sin(a) + math.sin(b))
    end = points[-1]
    u_out = np.array([math.cos(turn), math.sin(turn)])
    u_in = np.array([1.0, 0.0])
    # 入口切线 y=0 与出口切线的交点；出口切线点在交点前方
    # end = t_in*u_in + t_out*u_out
    a11, a12 = u_in[0], u_out[0]
    a21, a22 = u_in[1], u_out[1]
    det = a11 * a22 - a12 * a21
    if abs(det) < 1e-12:
        return points, length, 0.0, 0.0, points[samples // 2]
    t_in = (end[0] * a22 - a12 * end[1]) / det
    t_out = (a11 * end[1] - end[0] * a21) / det
    apex = points[samples // 2]
    return points, length, max(0.0, float(t_in)), max(0.0, float(t_out)), apex


def _polygon_edges(turns, rng):
    directions = _turn_directions(turns)
    return directions


def _solve_edges(turns, trims_in, trims_out, corner_lengths, target_lap,
                 width, rng, max_straight, min_straight):
    count = len(turns)
    angles = _turn_directions(turns)
    directions = [(math.cos(a), math.sin(a)) for a in angles]
    lower = np.zeros(count)
    upper = np.zeros(count)
    for i in range(count):
        nxt = (i + 1) % count
        lower[i] = trims_out[i] + trims_in[nxt] + min_straight
        upper[i] = trims_out[i] + trims_in[nxt] + max_straight
    trim_total = float(sum(trims_in) + sum(trims_out))
    corner_total = float(sum(corner_lengths))
    desired_sum = target_lap - corner_total + trim_total
    if desired_sum < float(np.sum(lower)) - 1e-6:
        return None
    if desired_sum > float(np.sum(upper)) + 1e-6:
        return None
    a_eq = np.array([
        [direction[0] for direction in directions],
        [direction[1] for direction in directions],
        np.ones(count),
    ])
    b_eq = np.array([0.0, 0.0, desired_sum])
    cost = rng.uniform(-1.0, 1.0, count)
    try:
        result = linprog(cost, A_eq=a_eq, b_eq=b_eq, bounds=list(zip(lower, upper)),
                         method="highs")
    except ValueError:
        return None
    if not result.success:
        return None
    lengths = np.asarray(result.x, dtype=np.float64)
    # Verify closure and edge length limits
    if np.any(lengths < lower - 1e-4) or np.any(lengths > upper + 1e-4):
        return None
    if np.hypot(np.sum(lengths * np.cos(np.array(angles))),
                np.sum(lengths * np.sin(np.array(angles)))) > 0.1:
        return None
    return lengths


def _postprocess_straights(centerline, width, expected_corners,
                           straight_kappa=0.0015, blend_points=3):
    """把严格直道段拉成直线，并用弯道段包住过渡曲率。

    返回 (centerline, corners, elements, straight_lengths) 或 None。
    直线段用弦线投影；两端各 blend_points 点做余弦混合，避免接点折角。
    """
    points = np.asarray(centerline, dtype=np.float64)
    count = len(points)
    curvature = _curvature(points)
    mask = np.abs(curvature) < float(straight_kappa)
    if np.all(mask) or np.all(~mask):
        return None
    runs = []
    i = int(np.argmax(~mask))
    visited = 0
    while visited < count:
        if mask[i]:
            start = i
            ids = []
            while mask[i] and len(ids) < count:
                ids.append(i)
                i = (i + 1) % count
            visited += len(ids)
            if len(ids) >= 4:
                runs.append(ids)
        else:
            i = (i + 1) % count
            visited += 1
    if len(runs) != int(expected_corners):
        return None

    start_index = None
    for run in runs:
        if 0 in run:
            start_index = run[0]
            break
    if start_index is None:
        start_index = max(runs, key=len)[0]
    points = np.roll(points, -start_index, axis=0)
    curvature = np.roll(curvature, -start_index, axis=0)
    runs = [[(index - start_index) % count for index in run] for run in runs]
    runs.sort(key=lambda run: run[0])

    straightened = points.copy()
    for ids in runs:
        pp = points[ids]
        p0, p1 = pp[0], pp[-1]
        chord = p1 - p0
        chord_len = float(np.linalg.norm(chord))
        if chord_len < 1e-9:
            continue
        distances = np.concatenate(
            [[0.0], np.cumsum(np.linalg.norm(np.diff(pp, axis=0), axis=1))])
        fractions = distances / max(float(distances[-1]), 1e-9)
        targets = p0[None, :] + chord[None, :] * fractions[:, None]
        last = len(ids) - 1
        for k, index in enumerate(ids):
            weight = 1.0
            if k < blend_points:
                weight = min(weight, 0.5 - 0.5 * math.cos(
                    math.pi * k / float(blend_points)))
            if last - k < blend_points:
                weight = min(weight, 0.5 - 0.5 * math.cos(
                    math.pi * (last - k) / float(blend_points)))
            straightened[index] = ((1.0 - weight) * points[index]
                                  + weight * targets[k])
    straightened -= straightened[0]
    new_curvature = _curvature(straightened)

    corners = []
    elements = []
    straight_lengths = []
    for run_index, ids in enumerate(runs):
        straight_lengths.append(float(np.linalg.norm(
            straightened[ids[-1]] - straightened[ids[0]])))
        elements.append({"type": "straight", "label": "-",
                         "start": int(ids[0]), "end": int(ids[-1])})
        nxt = runs[(run_index + 1) % len(runs)]
        gap = []
        i = (ids[-1] + 1) % count
        while i != nxt[0]:
            gap.append(i)
            i = (i + 1) % count
        if not gap:
            return None
        apex = max(gap, key=lambda index: abs(new_curvature[index]))
        direction = 1 if new_curvature[apex] >= 0 else -1
        label = run_index + 1
        corners.append({"label": label, "apex": int(apex),
                        "start": int(gap[0]), "end": int(gap[-1]),
                        "direction": int(direction)})
        elements.append({"type": "corner", "label": "T%d" % label,
                         "start": int(gap[0]), "end": int(gap[-1])})
    return straightened, corners, elements, straight_lengths


def _strict_straight_runs(points, straight_kappa):
    curvature = _curvature(points)
    mask = np.abs(curvature) < float(straight_kappa)
    count = len(points)
    runs = []
    i = int(np.argmax(~mask))
    visited = 0
    while visited < count:
        if mask[i]:
            ids = []
            while mask[i] and len(ids) < count:
                ids.append(i)
                i = (i + 1) % count
            visited += len(ids)
            if len(ids) >= 4:
                runs.append(ids)
        else:
            i = (i + 1) % count
            visited += 1
    return mask, runs


def _start_on_longest_straight(centerline, rng, expected_corners,
                               straight_kappa):
    """把起点放到最长直道中点；方向随机但由 rng 决定。"""
    points = np.asarray(centerline, dtype=np.float64)
    reverse = bool(rng.randint(0, 2))
    if reverse:
        points = points[::-1].copy()
    mask, runs = _strict_straight_runs(points, straight_kappa)
    if len(runs) != int(expected_corners):
        return None
    if not runs:
        return None
    longest = max(
        runs, key=lambda ids: float(np.linalg.norm(
            points[ids[-1]] - points[ids[0]])))
    pp = points[longest]
    distances = np.concatenate(
        [[0.0], np.cumsum(np.linalg.norm(np.diff(pp, axis=0), axis=1))])
    half = float(distances[-1]) * 0.5
    middle = int(np.argmin(np.abs(distances - half)))
    start_index = int(longest[middle])
    points = np.roll(points, -start_index, axis=0)
    points -= points[0]
    count = len(points)
    curvature = _curvature(points)
    mask = np.abs(curvature) < float(straight_kappa)

    elements = []
    corners = []
    straight_lengths = []
    i = 0
    if i < count and mask[i]:
        start = i
        while i < count and mask[i]:
            i += 1
        elements.append({"type": "straight", "label": "-",
                         "start": start, "end": i - 1})
        straight_lengths.append(float(np.linalg.norm(
            points[i - 1] - points[start])))
    while i < count:
        if not mask[i]:
            gap_start = i
            while i < count and not mask[i]:
                i += 1
            gap_end = i - 1
            apex = max(range(gap_start, gap_end + 1),
                       key=lambda index: abs(curvature[index]))
            label = len(corners) + 1
            direction = 1 if curvature[apex] >= 0 else -1
            corners.append({"label": label, "apex": int(apex),
                            "start": int(gap_start), "end": int(gap_end),
                            "direction": int(direction)})
            elements.append({"type": "corner", "label": "T%d" % label,
                             "start": int(gap_start),
                             "end": int(gap_end)})
        if i < count and mask[i]:
            start = i
            while i < count and mask[i]:
                i += 1
            elements.append({"type": "straight", "label": "-",
                             "start": start, "end": i - 1})
            straight_lengths.append(float(np.linalg.norm(
                points[i - 1] - points[start])))
    if len(corners) != int(expected_corners):
        return None
    # 起点在直道中间时，首尾两段其实属于同一条直道，合并显示
    if (len(elements) >= 2
            and elements[0]["type"] == "straight"
            and elements[-1]["type"] == "straight"):
        merged = {"type": "straight", "label": "-",
                  "start": int(elements[-1]["start"]),
                  "end": int(elements[0]["end"])}
        elements = [merged] + elements[1:-1]
    _mask2, runs2 = _strict_straight_runs(points, straight_kappa)
    longest_length = max(
        float(np.linalg.norm(points[ids[-1]] - points[ids[0]]))
        for ids in runs2)
    return {
        "centerline": points,
        "corners": corners,
        "elements": elements,
        "straight_lengths": straight_lengths,
        "start_straight_length_m": longest_length,
        "start_direction": "reverse" if reverse else "forward",
        "start_fraction": 0.5,
    }


def _curvature(points):
    count = len(points)
    result = np.zeros(count)
    for i in range(count):
        a = points[(i - 1) % count]
        b = points[i]
        c = points[(i + 1) % count]
        h1 = math.atan2(b[1] - a[1], b[0] - a[0])
        h2 = math.atan2(c[1] - b[1], c[0] - b[0])
        dh = (h2 - h1 + math.pi) % (2.0 * math.pi) - math.pi
        ds = 0.5 * (math.hypot(b[0] - a[0], b[1] - a[1])
                    + math.hypot(c[0] - b[0], c[1] - b[1]))
        result[i] = dh / max(ds, 1e-9)
    return result


def _boundary_curvature(points):
    return np.abs(_curvature(points))


def _count_hairpins(left, right, corners, threshold):
    """按每个弯的内侧边界曲率统计发卡弯数量。"""
    left_curvature = _boundary_curvature(left)
    right_curvature = _boundary_curvature(right)
    count = len(left)
    total = 0
    for corner in corners:
        start = int(corner["start"]) % count
        end = int(corner["end"]) % count
        indices = []
        index = start
        while True:
            indices.append(index)
            if index == end:
                break
            index = (index + 1) % count
        inside = (left_curvature if int(corner.get("direction", 1)) >= 0
                  else right_curvature)
        if float(np.max(inside[indices])) >= float(threshold):
            total += 1
    return total


def _direction_counts(corners):
    left = sum(1 for corner in corners
               if int(corner.get("direction", 1)) >= 0)
    right = len(corners) - left
    return left, right


def _edges(points, width):
    tangents = np.roll(points, -1, axis=0) - points
    lengths = np.hypot(tangents[:, 0], tangents[:, 1])
    tangents /= np.maximum(lengths, 1e-9)[:, None]
    normals = np.stack([-tangents[:, 1], tangents[:, 0]], axis=1)
    half = width * 0.5
    return points + normals * half, points - normals * half


def _try_seed(seed, params):
    rng = np.random.RandomState(int(seed))
    min_lap, max_lap = params["lap_length_m"]
    min_width, max_width = params["width_m"]
    min_corners, max_corners = params["corner_count"]
    width = float(rng.uniform(min_width, max_width))
    count = int(rng.randint(min_corners, max_corners + 1))
    target_lap = float(rng.uniform(min_lap, max_lap))

    # 随机星形凸多边形：角度 + 半径扰动；顶点按极角排序，天然闭合
    gap = 2.0 * math.pi / float(count)
    gaps = gap * (1.0 + rng.uniform(-ANGLE_JITTER, ANGLE_JITTER, count))
    gaps /= np.sum(gaps)
    angles = np.cumsum(gaps) * (2.0 * math.pi)
    angles = np.concatenate([[0.0], angles[:-1]])
    radii = rng.uniform(RADIAL_RANGE[0], RADIAL_RANGE[1], count)
    vertices0 = np.stack([radii * np.cos(angles),
                          radii * np.sin(angles)], axis=1)
    edge_vec = np.roll(vertices0, -1, axis=0) - vertices0
    edge_base = np.hypot(edge_vec[:, 0], edge_vec[:, 1])
    if np.any(edge_base < 1e-4):
        return None
    directions = edge_vec / edge_base[:, None]
    turns = np.zeros(count)
    for index in range(count):
        prev = directions[index - 1]
        nxt = directions[index]
        cross = prev[0] * nxt[1] - prev[1] * nxt[0]
        dot = prev[0] * nxt[0] + prev[1] * nxt[1]
        turns[index] = math.atan2(cross, dot)
    # 允许 S 弯/凹弯；只排除过小的弯和接近发卡的单个转角
    if np.any(np.abs(turns) <= 0.02) or np.any(np.abs(turns) >= math.pi - 0.02):
        return None
    if abs(float(np.sum(turns)) - 2.0 * math.pi) > 1e-5:
        return None

    required_hairpins = int(params.get("min_hairpin_count", 1))
    if required_hairpins < 0 or required_hairpins > count:
        return None
    max_center_k = 1.0 / (width * 0.5 + 1.0 / params["boundary_max_curvature"])
    ranked = list(np.argsort(-np.abs(turns)))
    hairpin_indices = ranked[:required_hairpins]
    kmax = np.zeros(count)
    for index in range(count):
        kmax[index] = rng.uniform(NORMAL_KMAX_RANGE[0],
                                  max_center_k * 0.62)
    for index in hairpin_indices:
        kmax[index] = max_center_k * 0.93
    shapes = []
    trims_in = np.zeros(count)
    trims_out = np.zeros(count)
    corner_lengths = np.zeros(count)
    for index, turn in enumerate(turns):
        points, length, trim_in, trim_out, _apex = _corner_shape(
            turn, kmax[index], int(params["corner_samples"]))
        if length <= 0 or trim_in <= 0 or trim_out <= 0:
            return None
        shapes.append(points)
        trims_in[index] = trim_in
        trims_out[index] = trim_out
        corner_lengths[index] = length

    trim_total = float(np.sum(trims_in) + np.sum(trims_out))
    corner_total = float(np.sum(corner_lengths))
    edge_base_sum = float(np.sum(edge_base))
    scale = (target_lap - corner_total + trim_total) / edge_base_sum
    if scale <= 0.1:
        return None
    vertices = vertices0 * scale
    lengths = edge_base * scale
    min_straight = max(float(params["min_straight_m"]), width * 2.0)
    straight_lengths = []
    for index in range(count):
        nxt = (index + 1) % count
        straight = lengths[index] - trims_out[index] - trims_in[nxt]
        if straight < min_straight - 1e-6:
            return None
        if (float(params["max_straight_m"]) > 0.0
                and straight > params["max_straight_m"] + 1e-6):
            return None
        straight_lengths.append(float(straight))

    # 用弯曲线 + 直道拼出高密度中心线
    dense = []
    apex_points = []
    straight_lengths = []
    for index in range(count):
        turn = turns[index]
        local = shapes[index]
        trim_in = trims_in[index]
        trim_out = trims_out[index]
        angle = math.atan2(directions[index - 1][1],
                           directions[index - 1][0])
        ca, sa = math.cos(angle), math.sin(angle)
        rot = np.array([[ca, -sa], [sa, ca]])
        entry = vertices[index] - trim_in * directions[index - 1]
        world = local.dot(rot.T) + entry
        # 加入弯曲线（去掉与上一段重复的起点）
        start = 0 if not dense else 1
        dense.extend(world[start:].tolist())
        apex_points.append((world[len(world) // 2][0],
                            world[len(world) // 2][1]))
        # 直道从弯出口到下一个弯入口
        nxt = (index + 1) % count
        straight_start = vertices[index] + trim_out * directions[index]
        straight_end = vertices[nxt] - trims_in[nxt] * directions[index]
        straight_len = float(np.linalg.norm(straight_end - straight_start))
        if straight_len <= 0.0:
            return None
        straight_lengths.append(straight_len)
        if len(dense) > 1:
            dense.pop()  # 与直道起点重复
        dense.append(straight_start.tolist())
        # 高密度直道
        if straight_len > 3.0:
            for k in range(1, max(2, int(straight_len / 1.0))):
                frac = k / float(max(1, int(straight_len / 1.0)))
                dense.append((straight_start + (straight_end - straight_start) * frac).tolist())
        dense.append(straight_end.tolist())

    dense = np.asarray(dense, dtype=np.float64)
    # 去掉连续重复点
    keep = [0]
    for i in range(1, len(dense)):
        if np.linalg.norm(dense[i] - dense[keep[-1]]) > 1e-6:
            keep.append(i)
    dense = dense[keep]
    if len(dense) < 100:
        return None

    # 选一条足够长的直道，取中点附近作为起点；旋转闭环
    best_edge = max(range(count), key=lambda i: straight_lengths[i])
    i = best_edge
    start_a = vertices[i] + trims_out[i] * directions[i]
    start_b = vertices[(i + 1) % count] - trims_in[(i + 1) % count] * directions[i]
    fraction = float(rng.uniform(0.25, 0.75))
    start_point = start_a + (start_b - start_a) * fraction
    start_idx = int(np.argmin(np.sum((dense - start_point) ** 2, axis=1)))
    dense = np.roll(dense, -start_idx, axis=0)
    origin = dense[0].copy()
    dense = dense - origin
    # 目标点重采样到 4 m
    centerline, lap_length = bt._cyclic_resample(dense, 4.0)
    centerline[0] = (0.0, 0.0)
    heading = math.atan2(centerline[1][1] - centerline[0][1],
                         centerline[1][0] - centerline[0][0])
    left, right = _edges(centerline, width)

    # 发卡弯的内侧边界曲率；这里直接检查整体边界最大曲率
    max_boundary = max(float(np.max(_boundary_curvature(left))),
                       float(np.max(_boundary_curvature(right))))
    if max_boundary > params["boundary_max_curvature"] + 1e-6:
        return None
    # 边界自交
    try:
        if not LineString(np.vstack([left, left[0]])).is_simple:
            return None
        if not LineString(np.vstack([right, right[0]])).is_simple:
            return None
    except Exception:
        return None

    # 后处理：严格直道段拉直，过渡区留给弯道，并自动重建 T1..Tn
    post = _postprocess_straights(
        centerline, width, count,
        straight_kappa=float(params.get("postprocess_straight_kappa", 0.0015)),
        blend_points=int(params.get("postprocess_blend_points", 3)))
    if post is None:
        return None
    centerline, corners, elements, straight_lengths = post
    if len(corners) != count:
        return None
    # 起点：最长直道中点；方向由 seed 驱动，保证可复现
    start_info = _start_on_longest_straight(
        centerline, rng, count,
        float(params.get("postprocess_straight_kappa", 0.0015)))
    if start_info is None:
        return None
    centerline = start_info["centerline"]
    corners = start_info["corners"]
    elements = start_info["elements"]
    straight_lengths = start_info["straight_lengths"]
    if len(corners) != count:
        return None
    lap_length = float(np.sum(np.linalg.norm(
        np.diff(np.vstack([centerline, centerline[0]]), axis=0), axis=1)))
    heading = math.atan2(centerline[1][1] - centerline[0][1],
                         centerline[1][0] - centerline[0][0])
    # 绝对方向：整体旋转，使起点出发方向朝正右方（+x）
    rotation_rad = -heading
    cos_r = math.cos(rotation_rad)
    sin_r = math.sin(rotation_rad)
    rot = np.array([[cos_r, -sin_r], [sin_r, cos_r]])
    centerline = centerline.dot(rot.T)
    heading = 0.0
    left, right = _edges(centerline, width)
    max_boundary = max(float(np.max(_boundary_curvature(left))),
                       float(np.max(_boundary_curvature(right))))
    if max_boundary > params["boundary_max_curvature"] + 1e-6:
        return None
    actual_hairpin_count = _count_hairpins(
        left, right, corners, params["hairpin_boundary_curvature"])
    if actual_hairpin_count < required_hairpins:
        return None
    left_corners, right_corners = _direction_counts(corners)
    direction_diff = abs(left_corners - right_corners)
    diff_limit = params.get("max_left_right_diff")
    if diff_limit is not None and direction_diff > int(diff_limit):
        return None
    try:
        if not LineString(np.vstack([left, left[0]])).is_simple:
            return None
        if not LineString(np.vstack([right, right[0]])).is_simple:
            return None
    except Exception:
        return None
    straight_limit = max(max(straight_lengths),
                         float(start_info["start_straight_length_m"]))
    if (float(params["max_straight_m"]) > 0.0
            and straight_limit > params["max_straight_m"] + 1e-6):
        return None
    min_longest = float(params.get("min_longest_straight_m", 0.0))
    if (min_longest > 0.0
            and float(start_info["start_straight_length_m"])
            < min_longest - 1e-6):
        return None
    if lap_length < min_lap - 1e-3 or lap_length > max_lap + 1e-3:
        return None

    data = {
        "kind": "circuit",
        "name": "自动赛道 %02d" % (int(seed) % 100),
        "display_name": "AUTO TRACK %02d" % (int(seed) % 100),
        "width_m": round(width, 3),
        "center": [0.0, 0.0],
        "centerline": [[round(float(x), 3), round(float(y), 3)]
                       for x, y in centerline],
        "left_edge": [[round(float(x), 3), round(float(y), 3)]
                      for x, y in left],
        "right_edge": [[round(float(x), 3), round(float(y), 3)]
                       for x, y in right],
        "corners": corners,
        "elements": elements,
        "start": {"x": 0.0, "y": 0.0, "heading_rad": heading},
        "reference": {
            "lap_length_m": round(lap_length, 1),
            "width_m": round(width, 3),
            "corner_post_count": 1,
            "straight_kappa_threshold": params["straight_kappa_threshold"],
            "hairpin_boundary_curvature": params["hairpin_boundary_curvature"],
            "min_hairpin_count": required_hairpins,
            "actual_hairpin_count": actual_hairpin_count,
            "left_corner_count": int(left_corners),
            "right_corner_count": int(right_corners),
            "left_right_diff": int(direction_diff),
            "max_left_right_diff": diff_limit,
            "boundary_max_curvature": params["boundary_max_curvature"],
            "max_straight_m": round(max(
                max(straight_lengths),
                float(start_info["start_straight_length_m"])), 2),
            "min_straight_m": round(min(straight_lengths), 2),
            "min_straight_effective_m": round(min_straight, 2),
            "min_longest_straight_m": float(params.get(
                "min_longest_straight_m", 0.0)),
            "max_straight_limit_m": float(params["max_straight_m"]),
            "corner_count": count,
            "start_on_longest_straight": True,
            "start_fraction": round(float(start_info["start_fraction"]), 3),
            "start_straight_length_m": round(
                float(start_info["start_straight_length_m"]), 2),
            "start_direction": start_info["start_direction"],
            "start_heading_rad": 0.0,
            "rotation_rad": round(float(rotation_rad), 6),
            "target_lap_m": round(target_lap, 1),
            "max_boundary_curvature": round(max_boundary, 4),
            "boundary_simple": True,
            "curvature_derivative_continuous": True,
            "postprocess": {
                "straight_kappa": round(float(params.get(
                    "postprocess_straight_kappa", 0.0015)), 6),
                "blend_points": int(params.get(
                    "postprocess_blend_points", 3)),
                "straightened": True,
            },
            "generator": {
                "version": GENERATOR_VERSION,
                "seed": int(seed),
                "params": params,
                "corner_turns_rad": [round(float(v), 6) for v in turns],
                "corner_kmax": [round(float(v), 6) for v in kmax],
                "straight_lengths_m": [round(float(v), 2)
                                       for v in straight_lengths],
                "hairpin_indices": [int(v) for v in hairpin_indices],
                "hairpin_count": int(actual_hairpin_count),
                "left_corner_count": int(left_corners),
                "right_corner_count": int(right_corners),
                "left_right_diff": int(direction_diff),
                "hairpin_boundary_curvature": round(max_boundary, 4),
                "start_direction": start_info["start_direction"],
                "start_fraction": round(float(start_info["start_fraction"]), 3),
            },
        },
    }
    return data


def generate(seed_start, count, params, out_dir):
    required_hairpins = int(params.get("min_hairpin_count", 1))
    if required_hairpins > int(params["corner_count"][1]):
        raise ValueError(
            "min_hairpin_count=%d 大于最大弯数 %d，无法生成"
            % (required_hairpins, int(params["corner_count"][1])))
    os.makedirs(out_dir, exist_ok=True)
    results = []
    seed = int(seed_start)
    for _ in range(count):
        found = None
        seed_start_attempt = seed
        attempts = int(params["max_attempts"])
        for _attempt in range(attempts):
            data = _try_seed(seed, params)
            if data is not None:
                found = data
                break
            seed += 1
        if found is None:
            seed_end_attempt = seed_start_attempt + attempts - 1
            raise RuntimeError(
                "已尝试 %d 次仍未找到合规赛道\n种子范围 %d - %d"
                % (attempts, seed_start_attempt, seed_end_attempt))
        track_index = len(results) + 1
        found["name"] = "自动赛道 %02d" % track_index
        found["display_name"] = "AUTO TRACK %02d" % track_index
        filename = "track_auto_%02d.json" % track_index
        path = os.path.join(out_dir, filename)
        rel_track = os.path.relpath(path, PROJECT).replace("\\", "/")
        track_id = "auto_%d" % track_index
        seed_file = tm.create_seed_file(
            PROJECT, GENERATOR_VERSION,
            found["reference"]["generator"]["seed"],
            found["reference"]["generator"]["params"],
            track_id, rel_track)
        found["reference"]["generator"]["seed_file"] = seed_file
        with open(path, "w", encoding="utf-8") as handle:
            json.dump(found, handle, ensure_ascii=False, indent=1)
            handle.write("\n")
        print("生成 %s：seed=%d，%.1f m，%.1f m 宽，%d 弯，最长直 %.1f m"
              % (os.path.basename(path), found["reference"]["generator"]["seed"],
                 found["reference"]["lap_length_m"],
                 found["width_m"], found["reference"]["corner_count"],
                 found["reference"]["max_straight_m"]))
        results.append((path, found))
        seed += 1
    manifest = {
        "generator": "scripts/build_random_track.py",
        "generator_version": GENERATOR_VERSION,
        "seed_compatibility": "only same generator_version",
        "params": params,
        "tracks": [
            {
                "file": os.path.basename(path),
                "seed": data["reference"]["generator"]["seed"],
                "name": data["name"],
                "lap_length_m": data["reference"]["lap_length_m"],
                "width_m": data["width_m"],
                "corner_count": data["reference"]["corner_count"],
                "max_straight_m": data["reference"]["max_straight_m"],
                "seed_file": data["reference"]["generator"].get(
                    "seed_file", ""),
                "hairpin_boundary_curvature":
                    data["reference"]["generator"]["hairpin_boundary_curvature"],
            }
            for path, data in results
        ],
    }
    manifest_path = os.path.join(out_dir, "auto_tracks_manifest.json")
    with open(manifest_path, "w", encoding="utf-8") as handle:
        json.dump(manifest, handle, ensure_ascii=False, indent=1)
        handle.write("\n")
    print("manifest:", manifest_path)
    return results


def preview(data, path, scale=1.0):
    pts = np.asarray(data["centerline"])
    min_xy, max_xy = pts.min(axis=0), pts.max(axis=0)
    margin = 30
    w = int((max_xy[0] - min_xy[0]) * scale) + margin * 2
    h = int((max_xy[1] - min_xy[1]) * scale) + margin * 2
    im = Image.new("RGB", (max(1, w), max(1, h)), (76, 128, 62))
    dr = ImageDraw.Draw(im)

    def px(p):
        return (margin + (p[0] - min_xy[0]) * scale,
                margin + (max_xy[1] - p[1]) * scale)

    line = [px(p) for p in pts] + [px(pts[0])]
    tw = max(2, int(data["width_m"] * scale))
    dr.line(line, fill=(235, 235, 235), width=tw + 3, joint="curve")
    dr.line(line, fill=(58, 58, 60), width=tw, joint="curve")
    sx, sy = px((0, 0))
    dr.ellipse([sx - 4, sy - 4, sx + 4, sy + 4], fill=(235, 80, 60))
    im.save(path, "PNG")


def main():
    parser = argparse.ArgumentParser(description="随机生成闭环赛道")
    parser.add_argument("--seed", type=int, default=20261126)
    parser.add_argument("--count", type=int, default=3)
    parser.add_argument("--out-dir", default=os.path.join(PROJECT, "cfg", "tracks"))
    parser.add_argument("--preview-dir", default=os.path.join(PROJECT, "data"))
    parser.add_argument("--lap-min", type=float, default=DEFAULTS["lap_length_m"][0])
    parser.add_argument("--lap-max", type=float, default=DEFAULTS["lap_length_m"][1])
    parser.add_argument("--width-min", type=float, default=DEFAULTS["width_m"][0])
    parser.add_argument("--width-max", type=float, default=DEFAULTS["width_m"][1])
    parser.add_argument("--corner-min", type=int, default=DEFAULTS["corner_count"][0])
    parser.add_argument("--corner-max", type=int, default=DEFAULTS["corner_count"][1])
    parser.add_argument("--max-straight", type=float,
                        default=DEFAULTS["max_straight_m"],
                        help="所有直道上限；0=不限制")
    parser.add_argument("--min-straight", type=float,
                        default=DEFAULTS["min_straight_m"],
                        help="所有直道最短长度")
    parser.add_argument("--min-longest-straight", type=float,
                        default=DEFAULTS["min_longest_straight_m"],
                        help="只限制最长直道不得短于该值；0=不限制")
    parser.add_argument("--straight-threshold", type=float,
                        default=DEFAULTS["straight_kappa_threshold"])
    parser.add_argument("--hairpin-curvature", type=float,
                        default=DEFAULTS["hairpin_boundary_curvature"])
    parser.add_argument("--hairpin-min-count", type=int,
                        default=DEFAULTS["min_hairpin_count"],
                        help="至少几个发卡弯；0=不限制，>1 需要更多高曲率弯")
    parser.add_argument("--max-left-right-diff", default="none",
                        help="|左弯-右弯|上限；0=严格相等，none=不限制")
    parser.add_argument("--boundary-curvature-max", type=float,
                        default=DEFAULTS["boundary_max_curvature"])
    parser.add_argument("--postprocess-threshold", type=float,
                        default=DEFAULTS["postprocess_straight_kappa"])
    parser.add_argument("--postprocess-blend", type=int,
                        default=DEFAULTS["postprocess_blend_points"])
    parser.add_argument("--attempts", type=int, default=DEFAULTS["max_attempts"])
    args = parser.parse_args()
    params = {
        "lap_length_m": [float(args.lap_min), float(args.lap_max)],
        "width_m": [float(args.width_min), float(args.width_max)],
        "corner_count": [int(args.corner_min), int(args.corner_max)],
        "min_straight_m": float(args.min_straight),
        "min_longest_straight_m": float(args.min_longest_straight),
        "max_straight_m": float(args.max_straight),
        "straight_kappa_threshold": float(args.straight_threshold),
        "hairpin_boundary_curvature": float(args.hairpin_curvature),
        "min_hairpin_count": int(args.hairpin_min_count),
        "max_left_right_diff": (None if str(args.max_left_right_diff).strip().lower()
                                in ("none", "") else int(args.max_left_right_diff)),
        "boundary_max_curvature": float(args.boundary_curvature_max),
        "corner_samples": DEFAULTS["corner_samples"],
        "radial_radius_range": list(RADIAL_RANGE),
        "angle_jitter": ANGLE_JITTER,
        "postprocess_straight_kappa": float(args.postprocess_threshold),
        "postprocess_blend_points": int(args.postprocess_blend),
        "max_attempts": int(args.attempts),
    }
    results = generate(args.seed, args.count, params, args.out_dir)
    for index, (path, data) in enumerate(results, start=1):
        preview_path = os.path.join(args.preview_dir,
                                    "auto_track_%02d_layout.png" % index)
        preview(data, preview_path)
        print("preview:", preview_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
