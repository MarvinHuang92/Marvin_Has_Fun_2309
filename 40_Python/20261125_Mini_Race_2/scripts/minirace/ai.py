# -*- coding: utf-8 -*-
"""AI 场上车辆管理 + 算力基准。

每个 AI 拥有一套独立的 ``Simulation``（共享同一份赛道几何），因此：
- 各自独立决策；
- AI 之间没有车-车碰撞，可以互相穿过；
- 每个 AI 只和自己的环境边界（赛道墙）发生碰撞。

AI 决策频率与物理频率解耦：物理默认 240 Hz，AI 默认 60 Hz。
"""
import copy
import json
import math
import os
import time

from minirace.driver import DEFAULT_AI_PARAMS, Driver, RuleDriver
from minirace.laptiming import LapTimer
from minirace.sim import Simulation

AI_CONFIG_DEFAULTS = {
    "enabled": True,
    "count": 1,
    "decision_hz": 60.0,
    "spawn_spacing_m": 12.0,
    "lookahead_base_m": 8.0,
    "lookahead_time_s": 0.50,
    "steering_gain": 1.0,
    "steer_slew_rate": 6.0,
    "target_lat_accel": 8.0,
    "brake_decel": 8.0,
    "max_speed_mps": 42.0,
    "throttle_gain": 0.35,
    "brake_gain": 0.55,
}

AI_CONFIG_NAME = "cfg/ai.json"


def _merge_ai_config(raw):
    cfg = dict(AI_CONFIG_DEFAULTS)
    cfg.update(raw or {})
    cfg["count"] = max(0, min(64, int(cfg.get("count", 1))))
    cfg["decision_hz"] = max(5.0, min(240.0, float(cfg.get("decision_hz", 60.0))))
    cfg["spawn_spacing_m"] = max(0.0, float(cfg.get("spawn_spacing_m", 12.0)))
    return cfg


def load_ai_config(project_dir, path=AI_CONFIG_NAME):
    full = path if os.path.isabs(path) else os.path.join(str(project_dir), path)
    raw = {}
    try:
        with open(full, "r", encoding="utf-8") as handle:
            raw = json.load(handle) or {}
    except (IOError, OSError, ValueError):
        raw = {}
    return _merge_ai_config(raw)


def save_ai_config(project_dir, config, path=AI_CONFIG_NAME):
    full = path if os.path.isabs(path) else os.path.join(str(project_dir), path)
    folder = os.path.dirname(full)
    if folder:
        os.makedirs(folder, exist_ok=True)
    cfg = _merge_ai_config(config)
    with open(full, "w", encoding="utf-8") as handle:
        json.dump(cfg, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    return full


def _point_ahead(points, index, distance):
    """沿闭环中心线（点列）前进 distance 米。"""
    count = len(points)
    if count < 2:
        return points[0] if points else (0.0, 0.0), 0
    remaining = float(distance)
    current = index % count
    step = 1 if remaining >= 0.0 else -1
    remaining = abs(remaining)
    while remaining > 1e-9:
        nxt = (current + step) % count
        x0, y0 = points[current]
        x1, y1 = points[nxt]
        seg = math.hypot(x1 - x0, y1 - y0)
        if seg >= remaining:
            weight = remaining / max(seg, 1e-9)
            return ((x0 + (x1 - x0) * weight, y0 + (y1 - y0) * weight),
                    current)
        remaining -= seg
        current = nxt
    return points[current], current


class AICar(object):
    """一个独立 AI 车辆：自己的 Simulation + RuleDriver。"""

    def __init__(self, config, ai_config, project_dir, index=0):
        self.index = int(index)
        self.config = copy.deepcopy(config)
        self.ai_config = dict(ai_config)
        self.sim = Simulation(self.config, project_dir=project_dir)
        self.driver = RuleDriver(
            self.ai_config,
            wheelbase_m=self.sim.params.wheelbase,
            max_steer_deg=self.sim.params.max_steer_deg,
        )
        self.driver.reset(self.sim.track)
        self._accumulator = 0.0
        self._decision_accumulator = 0.0
        self._command = None
        self.start_offset_m = 0.0
        self.lap_timer = LapTimer(self.sim.track)
        self._spawn(self.index)

    @property
    def telemetry(self):
        return self.sim.telemetry

    @property
    def label(self):
        return "AI_%02d" % (self.index + 1)

    @property
    def race_distance(self):
        return self.start_offset_m + self.sim.distance

    @property
    def best_lap(self):
        return self.lap_timer.best

    def _spawn(self, index):
        track = self.sim.track
        if track is not None and track.points:
            start_x, start_y, _heading = track.start
            nearest = track.nearest(start_x, start_y)
            if nearest is not None:
                start_index = nearest[5]
                spacing = float(self.ai_config.get("spawn_spacing_m", 12.0))
                # 发车放在玩家前方，启动后就能看到 AI 车辆；无车-车碰撞
                ahead_m = spacing * (index + 1)
                point, point_index = _point_ahead(track.points, start_index,
                                                  ahead_m)
                ahead, _ = _point_ahead(track.points, point_index, 2.0)
                heading = math.atan2(ahead[1] - point[1], ahead[0] - point[0])
                self.start_offset_m = ahead_m
                self.sim.vehicle.reset(point[0], point[1], heading)
                self.sim.track._last_index = point_index
                self.sim.time = 0.0
                self.sim.distance = 0.0
                self.sim.trail.clear()
                self.sim.telemetry = None
                self.sim.step_raw(0.0, 0.0, 0.0, 0.0)
        else:
            self.sim.reset()
            self.sim.step_raw(0.0, 0.0, 0.0, 0.0)
            self.start_offset_m = 0.0
        self.driver.reset(self.sim.track)
        self.lap_timer = LapTimer(self.sim.track)
        self._accumulator = 0.0
        self._decision_accumulator = 0.0
        self._command = None

    def reset(self):
        self._spawn(self.index)

    def update(self, frame_dt, paused=False):
        if paused:
            return
        frame_dt = max(0.0, min(0.1, float(frame_dt)))
        self._accumulator += frame_dt
        decision_period = 1.0 / max(5.0, float(
            self.ai_config.get("decision_hz", 60.0)))
        step_dt = self.sim.step_dt
        steps = 0
        while self._accumulator >= step_dt and steps < 64:
            if self._command is None or self._decision_accumulator >= decision_period:
                observation = Driver.observe(self.sim)
                self._command = self.driver.decide(observation)
                self._decision_accumulator = 0.0
            command = self._command
            self.sim.step_raw(command.throttle, command.brake, command.steer,
                              step_dt)
            self.lap_timer.update(self.sim.time, self.sim.vehicle.x,
                                  self.sim.vehicle.y)
            self._decision_accumulator += step_dt
            self._accumulator -= step_dt
            steps += 1
        if steps >= 64:
            self._accumulator = 0.0


class AIManager(object):
    """管理场上所有 AI；默认数量来自 ``cfg/ai.json``。"""

    def __init__(self, config, ai_config, project_dir, count=None):
        self.config = config
        self.ai_config = _merge_ai_config(ai_config)
        self.project_dir = project_dir
        if not self.ai_config.get("enabled", True):
            count = 0
        if count is None:
            count = int(self.ai_config.get("count", 1))
        self.cars = [AICar(config, self.ai_config, project_dir, index)
                     for index in range(max(0, int(count)))]

    def reset(self):
        for car in self.cars:
            car.reset()

    def update(self, frame_dt, paused=False):
        for car in self.cars:
            car.update(frame_dt, paused=paused)

    @property
    def telemetries(self):
        return [car.telemetry for car in self.cars]


def benchmark_ai(base_config, ai_config, project_dir, map_index=None,
                 seconds=4.0, fps=60.0):
    """headless 闭环基准：返回算力/行驶统计，供 04_TuneAI 使用。"""
    cfg = copy.deepcopy(base_config)
    maps = list((cfg.get("maps", {}) or {}).get("list", []))
    if maps:
        index = int(map_index if map_index is not None else min(2, len(maps) - 1))
        item = maps[index % len(maps)]
        track_cfg = cfg.setdefault("track", {})
        track_cfg["enabled"] = True
        track_cfg["file"] = item.get("file", track_cfg.get("file", "cfg/track.json"))
    else:
        index = 0
    manager = AIManager(cfg, ai_config, project_dir, count=None)
    seconds = max(0.5, float(seconds))
    frames = max(1, int(round(seconds * float(fps))))
    frame_dt = 1.0 / max(1.0, float(fps))
    started = time.perf_counter()
    for _ in range(frames):
        manager.update(frame_dt)
    elapsed = time.perf_counter() - started
    count = len(manager.cars)
    per_frame_ms = elapsed * 1000.0 / frames
    budget_ms = 1000.0 / max(1.0, float(fps))
    per_ai_ms = per_frame_ms / count if count else 0.0
    half_budget_count = int((budget_ms * 0.5) / per_ai_ms) if per_ai_ms > 0 else 0
    full_budget_count = int(budget_ms / per_ai_ms) if per_ai_ms > 0 else 0
    distances = [car.sim.distance for car in manager.cars]
    return {
        "map_index": index,
        "seconds": seconds,
        "fps": fps,
        "ai_count": count,
        "elapsed_s": elapsed,
        "ms_per_frame": per_frame_ms,
        "ms_per_ai_frame": per_ai_ms,
        "budget_ms": budget_ms,
        "remaining_ms": budget_ms - per_frame_ms,
        "core_percent": per_frame_ms / budget_ms * 100.0,
        "count_at_50_percent": half_budget_count,
        "count_at_100_percent": full_budget_count,
        "distance_m": distances,
        "avg_speed_mps": [car.sim.distance / max(1e-6, seconds)
                          for car in manager.cars],
        "wall_hits": [car.sim.vehicle._wall_hits
                      if hasattr(car.sim.vehicle, "_wall_hits") else 0
                      for car in manager.cars],
    }
