# -*- coding: utf-8 -*-
"""圈速计时（纯数学，不依赖 pygame）。

只对闭环赛道（``track.kind == "circuit"``）计圈；圆形试车场没有圈数。
起跑线 = 赛道起点 ``track.start`` 处、沿比赛方向（切向）的法平面：
车从线后（negative 侧）穿到线前（positive 侧）且横向仍在赛道宽度内记一圈。

- 起跑后先离开起跑线一定距离才"武装"，避免一开始在线上/附近误触发；
- 完成一圈：记一圈时间、更新最快圈、当前圈号 +1；
- F5/HOME 复位：当前圈重新从 0 开始，最快圈保留（除非换地图）。
"""
import math


def format_time(seconds):
    if seconds is None:
        return "--:--:--"
    seconds = max(0.0, float(seconds))
    minutes = int(seconds // 60.0)
    rest = seconds - minutes * 60.0
    return "%02d:%06.3f" % (minutes, rest)


class LapTimer(object):
    CROSS_COOLDOWN = 5.0

    def __init__(self, track):
        self.track = track
        self.enabled = bool(track is not None and track.kind == "circuit")
        self.best = None
        self.lap = 1
        self._lap_start = 0.0
        self._armed = False
        self._prev_along = 0.0
        self._cooldown_until = 0.0
        self._start_x = 0.0
        self._start_y = 0.0
        self._tangent = (1.0, 0.0)
        self._normal = (0.0, 1.0)
        self._half_width = 15.0
        if self.enabled:
            points = track.points
            self._start_x, self._start_y, _heading = track.start
            nxt = points[1]
            dx = nxt[0] - self._start_x
            dy = nxt[1] - self._start_y
            length = math.hypot(dx, dy) or 1.0
            self._tangent = (dx / length, dy / length)
            self._normal = (-self._tangent[1], self._tangent[0])
            self._half_width = track.width_m * 0.5

    # ------------------------------------------------------------------ 对外
    def reset(self, sim_time, keep_best=True):
        self.lap = 1
        self._lap_start = float(sim_time)
        self._armed = False
        self._prev_along = 0.0
        self._cooldown_until = 0.0
        if not keep_best:
            self.best = None

    def home_reset(self, sim_time):
        """HOME：回到起点重新开始，当前圈号 +1，旧圈用时丢弃（不更新 best）。

        起跑后仍要先离开起跑线 ``arm_distance`` 才武装，防止复位抖动触发计时。
        """
        self.lap += 1
        self._lap_start = float(sim_time)
        self._armed = False
        self._prev_along = 0.0
        self._cooldown_until = 0.0

    def current_time(self, sim_time):
        return max(0.0, float(sim_time) - self._lap_start)

    def update(self, sim_time, x, y):
        """每个物理步调用；返回本步是否完成了一圈。"""
        if not self.enabled:
            return False
        dx = x - self._start_x
        dy = y - self._start_y
        along = dx * self._tangent[0] + dy * self._tangent[1]
        perp = abs(dx * self._normal[0] + dy * self._normal[1])
        if not self._armed:
            if abs(along) > 25.0:
                self._armed = True
            self._prev_along = along
            return False
        crossed = (self._prev_along < 0.0 and along >= 0.0
                   and perp <= self._half_width + 2.0
                   and abs(along) < 10.0)
        self._prev_along = along
        if not crossed:
            return False
        # 过线后 5 秒内的重复穿越不计圈、不改时间（用于防止倒车/抖动重复计数）
        if float(sim_time) < self._cooldown_until:
            return False
        completed = float(sim_time) - self._lap_start
        if completed > 5.0:
            if self.best is None or completed < self.best:
                self.best = completed
        self.lap += 1
        self._lap_start = float(sim_time)
        self._armed = False
        self._cooldown_until = float(sim_time) + self.CROSS_COOLDOWN
        return True
