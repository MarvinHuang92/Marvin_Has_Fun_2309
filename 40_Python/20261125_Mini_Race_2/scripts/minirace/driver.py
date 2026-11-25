# -*- coding: utf-8 -*-
"""AI 驾驶员接口 + 规则驾驶员（纯数学，不依赖 pygame / 显示层）。

驾驶接口
--------
一个驾驶员只需要实现三个动作：

``reset(track)``
    换地图/复位时清空内部状态，获得赛道几何。

``decide(observation)``
    输入一帧观测量（车辆状态 + 时间），返回一个连续控制量
    :class:`DriveCommand`（油门/刹车/方向盘，范围 0~1 / 0~1 / -1~1）。

``observe(simulation)``
    可选：把 ``Simulation`` 转成标准观测量。规则驾驶员和将来的 RL 环境
    都通过这层接口，不直接依赖键盘回弹模型。

物理层仍由 ``Simulation.step_raw(throttle, brake, steer)`` 推进；
AI 决策频率与物理频率解耦（默认 AI 60 Hz、物理 240 Hz）。
"""
import math


class DriverObservation(object):
    """一帧 AI 观测量（SI 单位）。"""

    __slots__ = ("time", "x", "y", "heading", "speed_mps", "vx", "vy",
                 "yaw_rate", "rpm", "gear", "slip_amount", "wall_hit")

    def __init__(self, time, x, y, heading, speed_mps, vx, vy, yaw_rate,
                 rpm, gear, slip_amount, wall_hit):
        self.time = float(time)
        self.x = float(x)
        self.y = float(y)
        self.heading = float(heading)
        self.speed_mps = float(speed_mps)
        self.vx = float(vx)
        self.vy = float(vy)
        self.yaw_rate = float(yaw_rate)
        self.rpm = float(rpm)
        self.gear = int(gear)
        self.slip_amount = float(slip_amount)
        self.wall_hit = bool(wall_hit)


class DriveCommand(object):
    """AI 输出的连续控制量。"""

    __slots__ = ("throttle", "brake", "steer")

    def __init__(self, throttle=0.0, brake=0.0, steer=0.0):
        self.throttle = float(throttle)
        self.brake = float(brake)
        self.steer = float(steer)

    def clamped(self):
        return DriveCommand(
            max(0.0, min(1.0, self.throttle)),
            max(0.0, min(1.0, self.brake)),
            max(-1.0, min(1.0, self.steer)),
        )


class Driver(object):
    """所有 AI 驾驶员的基类（接口约定）。"""

    name = "driver"

    def reset(self, track):
        raise NotImplementedError

    def decide(self, observation):
        raise NotImplementedError

    @staticmethod
    def observe(simulation):
        vehicle = simulation.vehicle
        telem = simulation.telemetry
        return DriverObservation(
            time=float(simulation.time),
            x=float(vehicle.x),
            y=float(vehicle.y),
            heading=float(vehicle.heading),
            speed_mps=float(telem.speed_abs) if telem is not None else 0.0,
            vx=float(vehicle.vx),
            vy=float(vehicle.vy),
            yaw_rate=float(vehicle.yaw_rate),
            rpm=float(telem.rpm) if telem is not None else 0.0,
            gear=int(telem.gear) if telem is not None else int(vehicle.gear),
            slip_amount=float(telem.slip_amount) if telem is not None else 0.0,
            wall_hit=bool(telem.wall_hit) if telem is not None else False,
        )


DEFAULT_AI_PARAMS = {
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


def _wrap(value):
    return (value + math.pi) % (2.0 * math.pi) - math.pi


class RuleDriver(Driver):
    """纯追踪转向 + 曲率限速的规则驾驶员。

    转向：
        在中心线上取一个随速度变长的前视点，按纯追踪
        ``delta = atan2(2 L sin(alpha), d)`` 算出前轮角，再归一化到方向盘。

    速度：
        沿前方一段路预扫描曲率，按 ``v = sqrt(a_lat / kappa)`` 得到各点限速，
        再用 ``v² = v_corner² + 2 a_brake s`` 提前刹车，取最小值。

    没有倒车逻辑：正常赛道闭环只需要前进挡。
    """

    name = "rule"

    def __init__(self, params=None, wheelbase_m=2.70, max_steer_deg=33.5):
        cfg = dict(DEFAULT_AI_PARAMS)
        cfg.update(params or {})
        self.params = cfg
        self.wheelbase_m = max(0.5, float(wheelbase_m))
        self.max_steer_rad = math.radians(max(1.0, min(80.0, max_steer_deg)))
        self.track = None
        self._hint_index = 0
        self._last_steer = 0.0
        self._last_time = None

    def reset(self, track):
        self.track = track
        self._hint_index = 0
        self._last_steer = 0.0
        self._last_time = None

    # ------------------------------------------------------------------ 赛道采样
    def _point_ahead(self, index, distance):
        """从 ``index`` 沿闭环中心线前进 ``distance`` 米（可负=后退）。"""
        points = self.track.points
        count = len(points)
        if count < 2:
            return points[0] if points else (0.0, 0.0), index
        if distance >= 0.0:
            step = 1
            remaining = float(distance)
        else:
            step = -1
            remaining = -float(distance)
        current = index % count
        while remaining > 1e-9:
            nxt = (current + step) % count
            x0, y0 = points[current]
            x1, y1 = points[nxt]
            seg = math.hypot(x1 - x0, y1 - y0)
            if seg >= remaining:
                weight = remaining / max(seg, 1e-9)
                return ((x0 + (x1 - x0) * weight,
                         y0 + (y1 - y0) * weight), current)
            remaining -= seg
            current = nxt
        return points[current], current

    def _curvature_at(self, index, span=5):
        points = self.track.points
        count = len(points)
        if count < 3:
            return 0.0
        p0 = points[(index - span) % count]
        p1 = points[index % count]
        p2 = points[(index + span) % count]
        a1 = math.atan2(p1[1] - p0[1], p1[0] - p0[0])
        a2 = math.atan2(p2[1] - p1[1], p2[0] - p1[0])
        ds = 0.5 * (math.hypot(p1[0] - p0[0], p1[1] - p0[1])
                    + math.hypot(p2[0] - p1[0], p2[1] - p1[1]))
        return abs(_wrap(a2 - a1)) / max(ds, 1e-6)

    def _target_speed(self, current_index, speed):
        """预扫描前方曲率，返回当前允许的目标速度（m/s）。"""
        cfg = self.params
        max_speed = float(cfg.get("max_speed_mps", 42.0))
        lat_accel = max(0.5, float(cfg.get("target_lat_accel", 8.0)))
        brake_decel = max(1.0, float(cfg.get("brake_decel", 8.0)))
        target = max_speed
        # 前方 0~90 m 采样，提前制动
        horizon = 90.0
        distance = 0.0
        sample_step = 6.0
        while distance <= horizon:
            point, index = self._point_ahead(current_index, distance)
            curvature = self._curvature_at(index)
            corner_speed = math.sqrt(lat_accel / max(curvature, 1e-6))
            corner_speed = min(corner_speed, max_speed)
            allowed = math.sqrt(corner_speed * corner_speed
                                + 2.0 * brake_decel * distance)
            target = min(target, allowed)
            distance += sample_step
        return max(2.0, target)

    # ------------------------------------------------------------------ 决策
    def decide(self, observation):
        cfg = self.params
        if self.track is None or not self.track.points:
            return DriveCommand()
        nearest = self.track.nearest(observation.x, observation.y,
                                     self._hint_index)
        if nearest is None:
            return DriveCommand()
        _distance, _cx, _cy, _tx, _ty, index = nearest
        self._hint_index = int(index)
        speed = max(0.0, float(observation.speed_mps))
        lookahead = (float(cfg.get("lookahead_base_m", 8.0))
                     + speed * float(cfg.get("lookahead_time_s", 0.5)))
        lookahead = max(4.0, lookahead)
        target, target_index = self._point_ahead(index, lookahead)

        # 纯追踪：把前视点变换到车体系
        dx = target[0] - observation.x
        dy = target[1] - observation.y
        cos_h = math.cos(observation.heading)
        sin_h = math.sin(observation.heading)
        local_x = cos_h * dx + sin_h * dy
        local_y = -sin_h * dx + cos_h * dy
        alpha = math.atan2(local_y, max(0.1, local_x))
        steer_angle = math.atan2(
            2.0 * self.wheelbase_m * math.sin(alpha), max(lookahead, 1e-3))
        steer = steer_angle / self.max_steer_rad
        steer *= float(cfg.get("steering_gain", 1.0))
        steer = max(-1.0, min(1.0, steer))

        # 方向盘速率限制（AI 60 Hz，避免瞬间满舵）
        if self._last_time is not None:
            dt = max(0.0, min(0.2, observation.time - self._last_time))
        else:
            dt = 1.0 / max(10.0, float(cfg.get("decision_hz", 60.0)))
        rate = float(cfg.get("steer_slew_rate", 6.0))
        if rate > 0.0:
            max_delta = rate * dt
            steer = self._last_steer + max(-max_delta, min(max_delta,
                                                           steer - self._last_steer))
        self._last_steer = steer
        self._last_time = observation.time

        target_speed = self._target_speed(target_index, speed)
        error = target_speed - speed
        if error >= 0.0:
            throttle = min(1.0, error * float(cfg.get("throttle_gain", 0.35)))
            brake = 0.0
        else:
            throttle = 0.0
            brake = min(1.0, -error * float(cfg.get("brake_gain", 0.55)))
        return DriveCommand(throttle, brake, steer).clamped()
