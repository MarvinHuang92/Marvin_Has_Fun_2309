# -*- coding: utf-8 -*-
"""模拟器本体：车辆 + 输入模型 + 轨迹 + 时间（世界坐标单位：米）。

这一层**不 import pygame，也不依赖窗口/显示缩放**：世界大小直接来自
``cfg/sim.json`` 的 ``world.width_m / height_m``（米），轨迹也按米保存。
窗口大小、pixels_per_meter、相机是否跟随，全部只影响渲染层。

可以无窗口地按固定步长推进，方便：
- ``scripts/tests_physics.py`` / ``scripts/probe_physics.py`` 自检与标定；
- 将来 AI 驾驶员 / 强化学习环境直接拿来当 ``env.step()`` 的内核。
"""
import math
import logging
import os
from collections import deque

from minirace.config import DEFAULT_CONFIG
from minirace.controls import Command, Controls  # noqa: F401  (Command 便于调用方 import)
from minirace.track import Track
from minirace.vehicle import Vehicle, VehicleParams

# 车头朝屏幕上方（世界坐标 y 向上，所以是 +90°）
SPAWN_HEADING = math.pi / 2.0


class Simulation(object):
    """一个可复位的模拟世界：赛道（或矩形场地）+ 一辆车 + 一条历史轨迹。"""

    def __init__(self, config=None, x=None, y=None, project_dir=None):
        self.config = config or DEFAULT_CONFIG
        world = self.config.get("world", {}) or {}
        self.width = float(world.get("width_m", 129.6))
        self.height = float(world.get("height_m", 81.0))
        if self.width <= 0.0 or self.height <= 0.0:
            raise ValueError("world.width_m / height_m 必须为正数")

        self.params = VehicleParams(self.config)
        self.controls = Controls(self.config.get("controls", {}))
        self.step_dt = 1.0 / self.params.step_hz
        self.max_substeps = max(1, int(self.params.max_substeps))

        # 赛道模式：加载中心线/起点；失败时退回矩形世界（并写日志）
        self.track = None
        track_cfg = self.config.get("track", {}) or {}
        if track_cfg.get("enabled", False):
            if project_dir is None:
                project_dir = os.path.dirname(os.path.dirname(os.path.dirname(
                    os.path.abspath(__file__))))
            try:
                self.track = Track(project_dir, self.config)
                bbox = self.track.bbox
                self.width = max(1.0, bbox[2] - bbox[0])
                self.height = max(1.0, bbox[3] - bbox[1])
            except (IOError, OSError, ValueError, KeyError) as exc:
                logging.getLogger(__name__).warning(
                    "赛道加载失败，退回矩形世界：%s", exc)
                self.track = None

        if self.track is not None:
            start_x, start_y, heading = self.track.start
            origin_x = start_x if x is None else float(x)
            origin_y = start_y if y is None else float(y)
            bounds = None
        else:
            origin_x = self.width / 2.0 if x is None else float(x)
            origin_y = self.height / 2.0 if y is None else float(y)
            heading = SPAWN_HEADING
            bounds = (self.width, self.height)
        self.spawn = (origin_x, origin_y, heading)
        self.vehicle = Vehicle(self.params, origin_x, origin_y,
                               heading=heading, bounds=bounds)

        render = self.config.get("render", {}) or {}
        trail_points = int(render.get("trail_points", 300) or 0)
        self.trail = deque(maxlen=trail_points) if trail_points > 0 else deque()

        self.time = 0.0
        self.distance = 0.0
        self.telemetry = None

    # ------------------------------------------------------------------ 生命周期
    def reset(self):
        self.controls.reset()
        self.vehicle.reset(*self.spawn)
        self.trail.clear()
        self.time = 0.0
        self.distance = 0.0
        self.telemetry = None
        if self.track is not None:
            self.track._last_index = 0

    # ------------------------------------------------------------------ 步进
    def step(self, command=None, dt=None):
        """推进一个物理步（走"人"的踏板/方向盘回弹模型），返回 Telemetry。"""
        dt = self.step_dt if dt is None else float(dt)
        command = command or Command()
        self.controls.update(command, dt)
        return self._step_vehicle(dt)

    def step_raw(self, throttle, brake, steer, dt=None):
        """绕过输入回弹，直接给定踏板/方向盘位置（脚本测试 / 将来 AI 驾驶员用）。"""
        controls = self.controls
        controls.throttle = max(0.0, min(controls.throttle_limit, float(throttle)))
        controls.brake = max(0.0, min(controls.brake_limit, float(brake)))
        controls.steer = max(-1.0, min(1.0, float(steer)))
        return self._step_vehicle(self.step_dt if dt is None else float(dt))

    def _step_vehicle(self, dt):
        telem = self.vehicle.step(self.controls, dt)
        if self.track is not None:
            self.track.resolve_collision(self.vehicle, telem, dt)
        self.time += dt
        self.distance += telem.speed_abs * dt
        self.trail.append((telem.x, telem.y))
        self.telemetry = telem
        return telem

    def advance(self, command, seconds):
        """按固定步长推进 seconds 秒（自检/无窗口批量跑时用）。"""
        remaining = float(seconds)
        last = self.telemetry
        while remaining > 1e-9:
            dt = min(self.step_dt, remaining)
            last = self.step(command, dt)
            remaining -= dt
        return last

    def toggle_reverse(self):
        return self.vehicle.toggle_reverse()
