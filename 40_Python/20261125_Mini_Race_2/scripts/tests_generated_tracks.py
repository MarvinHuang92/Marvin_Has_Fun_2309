# -*- coding: utf-8 -*-
"""校验 cfg/sim.json 中当前随机赛道是否满足生成边界条件。"""
import json
import math
import os
import sys

import numpy as np
from shapely.geometry import LineString

PROJECT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(PROJECT, "scripts"))

import build_random_track as generator  # noqa: E402

_passed = 0
_failed = []


def check(name, condition, detail=""):
    global _passed
    if condition:
        _passed += 1
        print("[PASS] %s" % name)
    else:
        _failed.append(name)
        print("[FAIL] %s  %s" % (name, detail))


def main():
    config_path = os.path.join(PROJECT, "cfg", "sim.json")
    with open(config_path, "r", encoding="utf-8") as handle:
        config = json.load(handle)
    files = []
    for item in config["maps"]["list"]:
        if not item.get("random"):
            continue
        path = os.path.join(PROJECT, item.get("file", ""))
        if os.path.isfile(path):
            files.append(path)
    check("随机赛道至少生成 3 条", len(files) >= 3, "files=%d" % len(files))
    for path in files:
        name = os.path.basename(path)
        with open(path, "r", encoding="utf-8") as handle:
            data = json.load(handle)
        ref = data["reference"]
        params = ref["generator"]["params"]
        centerline = np.asarray(data["centerline"], dtype=np.float64)
        left = np.asarray(data["left_edge"], dtype=np.float64)
        right = np.asarray(data["right_edge"], dtype=np.float64)
        check("%s：总长 %.1f m 在 %.0f-%.0f" % (
            name, ref["lap_length_m"], params["lap_length_m"][0],
            params["lap_length_m"][1]),
            params["lap_length_m"][0] - 1e-6
            <= ref["lap_length_m"] <= params["lap_length_m"][1] + 1e-6)
        check("%s：宽度 %.2f m 在 %.0f-%.0f" % (
            name, data["width_m"], params["width_m"][0],
            params["width_m"][1]),
            params["width_m"][0] - 1e-6
            <= data["width_m"] <= params["width_m"][1] + 1e-6)
        check("%s：弯道数 %d 在 %d-%d" % (
            name, ref["corner_count"], params["corner_count"][0],
            params["corner_count"][1]),
            params["corner_count"][0] <= ref["corner_count"]
            <= params["corner_count"][1]
            and len(data["corners"]) == ref["corner_count"])
        max_limit = float(params.get("max_straight_m", 0.0))
        check("%s：最长直道 %.1f m ≤ 上限 %.1f（0=不限）" % (
            name, ref["max_straight_m"], max_limit),
            max_limit <= 0.0
            or ref["max_straight_m"] <= max_limit + 1e-6)
        min_longest = float(params.get("min_longest_straight_m", 0.0))
        check("%s：最长直道 %.1f m ≥ 下限 %.1f（0=不限）" % (
            name, ref.get("start_straight_length_m", 0.0), min_longest),
            min_longest <= 0.0
            or float(ref.get("start_straight_length_m", 0.0))
            >= min_longest - 1e-6)
        min_hairpins = int(params.get("min_hairpin_count", 0))
        actual_hairpins = int(ref.get("actual_hairpin_count", 0))
        check("%s：发卡弯数量 %d ≥ %d" % (
            name, actual_hairpins, min_hairpins),
            actual_hairpins >= min_hairpins)
        hairpin_angles = ref.get("generator", {}).get(
            "hairpin_turn_angles_deg", []) or []
        hairpin_threshold = float(params.get(
            "hairpin_min_turn_angle_deg", 135.0))
        qualified = sum(
            1 for angle in hairpin_angles
            if abs(float(angle)) >= hairpin_threshold - 1e-6)
        check("%s：中心线转角 ≥ %.0f° 的弯 %d 个" % (
            name, hairpin_threshold, qualified),
            min_hairpins == 0 or qualified >= min_hairpins)
        generator_info = ref.get("generator", {})
        check("%s：生成器版本 %s" % (
            name, generator.GENERATOR_VERSION),
            generator_info.get("version") == generator.GENERATOR_VERSION)
        left_count = int(ref.get("left_corner_count", 0))
        right_count = int(ref.get("right_corner_count", 0))
        diff_limit = params.get("max_left_right_diff")
        diff_ok = (diff_limit is None
                   or abs(left_count - right_count) <= int(diff_limit))
        check("%s：左/右弯 %d/%d，差 %d（上限 %s）" % (
            name, left_count, right_count, abs(left_count - right_count),
            "none" if diff_limit is None else diff_limit),
            diff_ok and left_count + right_count == ref["corner_count"])
        max_boundary = max(
            float(np.max(generator._boundary_curvature(left))),
            float(np.max(generator._boundary_curvature(right))))
        check("%s：边界曲率 %.3f ≤ %.3f" % (
            name, max_boundary, params["boundary_max_curvature"]),
            max_boundary <= params["boundary_max_curvature"] + 1e-4)
        check("%s：左右边界不自交" % name,
              LineString(np.vstack([left, left[0]])).is_simple
              and LineString(np.vstack([right, right[0]])).is_simple)
        labels = [corner["label"] for corner in data["corners"]]
        check("%s：自动弯道编号 T1..Tn" % name,
              labels == list(range(1, ref["corner_count"] + 1)),
              "labels=%s" % labels)
        check("%s：默认每弯 1 根柱子" % name,
              int(ref.get("corner_post_count", 0)) == 1)
        check("%s：后处理拉直直道" % name,
              bool(ref.get("postprocess", {}).get("straightened")))
        max_deviation = 0.0
        for element in data["elements"]:
            if element["type"] != "straight":
                continue
            start = int(element["start"]) % len(centerline)
            end = int(element["end"]) % len(centerline)
            indices = []
            index = start
            while True:
                indices.append(index)
                if index == end:
                    break
                index = (index + 1) % len(centerline)
            points = centerline[indices]
            chord = points[-1] - points[0]
            length = float(np.linalg.norm(chord))
            if length < 1e-6:
                continue
            chord /= length
            deviations = [abs(float(np.cross(chord, point - points[0])))
                          for point in points]
            max_deviation = max(max_deviation, max(deviations))
        check("%s：直道偏差 %.4f m ≤ 0.05 m" % (
            name, max_deviation), max_deviation <= 0.05)
        mask, runs = generator._strict_straight_runs(
            centerline, params.get("postprocess_straight_kappa", 0.0015))
        check("%s：起点在最长直道中点" % name,
              bool(ref.get("start_on_longest_straight"))
              and abs(float(ref.get("start_fraction", 0.0)) - 0.5) < 1e-6
              and ref.get("start_direction") in ("forward", "reverse"))
        longest = max(
            runs, key=lambda ids: float(np.linalg.norm(
                centerline[ids[-1]] - centerline[ids[0]])))
        longest_length = float(np.linalg.norm(
            centerline[longest[-1]] - centerline[longest[0]]))
        check("%s：起点直道 %.2f m 为最长直道" % (
            name, ref.get("start_straight_length_m", 0.0)),
              abs(float(ref.get("start_straight_length_m", 0.0))
                  - longest_length) <= 5.0)
        pp = centerline[longest]
        distances = np.concatenate(
            [[0.0], np.cumsum(np.linalg.norm(np.diff(pp, axis=0), axis=1))])
        half = float(distances[-1]) * 0.5
        segment = min(len(pp) - 2, int(np.searchsorted(distances, half)))
        span = max(1e-9, float(distances[segment + 1] - distances[segment]))
        frac = (half - float(distances[segment])) / span
        midpoint = pp[segment] + (pp[segment + 1] - pp[segment]) * frac
        check("%s：起点距直道中点 %.2f m" % (
            name, float(np.linalg.norm(centerline[0] - midpoint))),
              float(np.linalg.norm(centerline[0] - midpoint)) <= 4.5)
        start_heading = math.atan2(
            float(centerline[1][1] - centerline[0][1]),
            float(centerline[1][0] - centerline[0][0]))
        check("%s：起点朝向正右方 +x" % name,
              abs(start_heading) <= 1e-5
              and abs(float(ref.get("start_heading_rad", 1.0))) <= 1e-6)
        check("%s：recorded seed/params" % name,
              isinstance(ref["generator"].get("seed"), int)
              and len(ref["generator"].get("params", {})) >= 8)
        check("%s：中心线点数足够" % name, len(centerline) >= 100)
    print("\n%d/%d 项通过" % (_passed, _passed + len(_failed)))
    if _failed:
        print("失败：")
        for name in _failed:
            print("  - %s" % name)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
