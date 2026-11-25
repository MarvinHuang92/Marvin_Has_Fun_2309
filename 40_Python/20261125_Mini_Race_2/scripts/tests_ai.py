# -*- coding: utf-8 -*-
"""AI 驾驶接口 / 规则驾驶员 / 多 AI 独立性 自检。

跑法::

    python scripts/tests_ai.py

不依赖 pygame/显示；AI 车辆用独立的 headless ``Simulation``。
"""
import copy
import math
import os
import sys

PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(PROJECT_DIR, "scripts"))

from minirace.ai import (AI_CONFIG_DEFAULTS, AIManager, _merge_ai_config,
                        load_ai_config)  # noqa: E402
from minirace.ai_colors import AI_COLOR_NAMES, AI_COLORS, ai_rgb  # noqa: E402
from minirace.config import load_config  # noqa: E402
from minirace.ranking import build_standings, format_gap  # noqa: E402
from minirace.driver import DEFAULT_AI_PARAMS, DriveCommand, RuleDriver  # noqa: E402

_results = []


def check(name, ok, detail=""):
    _results.append((name, bool(ok), detail))
    print("[%s] %s%s" % ("PASS" if ok else "FAIL", name,
                         ("  <- " + detail) if detail else ""))


def _config_for_map(base, map_id="shanghai"):
    config = copy.deepcopy(base)
    maps = list((config.get("maps", {}) or {}).get("list", []))
    item = None
    for candidate in maps:
        if candidate.get("id") == map_id:
            item = candidate
            break
    if item is None and maps:
        item = maps[min(2, len(maps) - 1)]
    if item is not None:
        track = config.setdefault("track", {})
        track["enabled"] = True
        track["file"] = item.get("file", track.get("file", "cfg/track.json"))
    return config


def test_driver_interface():
    check("AI 配色固定为 10 种且顺序正确",
          len(AI_COLORS) == 10
          and AI_COLOR_NAMES == ("red", "yellow", "green", "blue", "magenta",
                                 "orange", "cyan", "dark_blue",
                                 "light_gray", "white")
          and len(set(AI_COLORS)) == 10
          and ai_rgb(10) == AI_COLORS[0]
          and ai_rgb(19) == AI_COLORS[9],
          "%d colors, cycle 10" % len(AI_COLORS))
    rows, player = build_standings(1000.0, None, [
        ("AI_01", 1200.0, None), ("AI_02", 800.0, None)])
    ahead = next(row for row in rows if row.name == "AI_01")
    behind = next(row for row in rows if row.name == "AI_02")
    check("名次差距：领先为负、落后为正，超过一圈显示 LAP",
          format_gap(ahead, player) == "-200m"
          and format_gap(behind, player) == "+200m"
          and format_gap(ahead, player, 100.0) == "-2LAP"
          and format_gap(behind, player, 100.0) == "+2LAP",
          "%s / %s / %s / %s" % (
              format_gap(ahead, player), format_gap(behind, player),
              format_gap(ahead, player, 100.0),
              format_gap(behind, player, 100.0)))
    check("驾驶接口默认参数完整",
          all(key in DEFAULT_AI_PARAMS for key in
              ("decision_hz", "lookahead_base_m", "target_lat_accel",
               "max_speed_mps")))
    command = DriveCommand(2.0, -1.0, -3.0).clamped()
    check("DriveCommand 会把控制量限制到合法范围",
          command.throttle == 1.0 and command.brake == 0.0
          and command.steer == -1.0,
          "throttle=%.1f brake=%.1f steer=%.1f" % (
              command.throttle, command.brake, command.steer))


def test_rule_driver_closed_loop():
    base = load_config(PROJECT_DIR)
    config = _config_for_map(base, "shanghai")
    params = _merge_ai_config({"count": 1, "decision_hz": 60.0})
    manager = AIManager(config, params, PROJECT_DIR)
    for _ in range(600):  # 10 s @ 60 fps
        manager.update(1.0 / 60.0)
    car = manager.cars[0]
    telem = car.telemetry
    finite = (math.isfinite(telem.x) and math.isfinite(telem.y)
              and math.isfinite(telem.speed_abs))
    check("规则驾驶员能在上海赛道闭环行驶 10 s",
          car.sim.distance > 100.0 and car.sim.time > 9.5 and finite,
          "distance=%.1f m, sim_time=%.2f s, speed=%.1f km/h"
          % (car.sim.distance, car.sim.time, telem.speed_abs * 3.6))
    check("规则驾驶员会输出油门/刹车/方向盘连续量",
          telem.throttle >= 0.0 and telem.brake >= 0.0
          and -1.0 <= telem.steer <= 1.0,
          "throttle=%.2f brake=%.2f steer=%.2f"
          % (telem.throttle, telem.brake, telem.steer))
    check("AI 车速受 max_speed_mps 限制",
          telem.speed_abs <= float(params["max_speed_mps"]) + 1.5,
          "speed=%.2f m/s limit=%.2f" % (
              telem.speed_abs, params["max_speed_mps"]))


def test_multi_ai_independent():
    base = load_config(PROJECT_DIR)
    config = _config_for_map(base, "oval")
    params = _merge_ai_config({"count": 3, "decision_hz": 60.0,
                               "spawn_spacing_m": 10.0})
    manager = AIManager(config, params, PROJECT_DIR)
    for _ in range(180):
        manager.update(1.0 / 60.0)
    cars = manager.cars
    distinct_sims = len(set(id(car.sim) for car in cars)) == len(cars)
    distinct_vehicles = len(set(id(car.sim.vehicle) for car in cars)) == len(cars)
    distances = [car.sim.distance for car in cars]
    check("AI 数量参数可生成多个独立车辆",
          len(cars) == 3 and distinct_sims and distinct_vehicles,
          "cars=%d, distances=%s" % (len(cars),
                                     ", ".join("%.0f" % value for value in distances)))
    check("多 AI 各自独立决策且都在前进",
          all(car.telemetry is not None for car in cars)
          and all(car.sim.distance > 5.0 for car in cars),
          "sim_times=%s" % ", ".join("%.2f" % car.sim.time for car in cars))


def main():
    test_driver_interface()
    test_rule_driver_closed_loop()
    test_multi_ai_independent()
    failed = [name for name, ok, _ in _results if not ok]
    print()
    print("%d/%d 项通过" % (len(_results) - len(failed), len(_results)))
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
