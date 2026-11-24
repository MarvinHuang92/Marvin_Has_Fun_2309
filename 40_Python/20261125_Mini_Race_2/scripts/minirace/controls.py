# -*- coding: utf-8 -*-
"""驾驶输入模型：键盘开关 -> 连续的踏板 / 方向盘位置。

真车的踏板和方向盘不会"瞬间到底"，所以这里保留 V0 的思路：
按下按灵敏度爬升，松开以 ``spring_back`` 倍速率回弹，方向盘有中心虚位。

这一层是纯数学，不 import pygame，方便无窗口自检和将来的 AI 驾驶员直接复用
（AI 也可以不走这一层，直接给出踏板/方向盘位置）。
"""


class Command(object):
    """一帧的开关量输入。布尔值，来自键盘或 AI。"""

    __slots__ = ("throttle", "brake", "left", "right")

    def __init__(self, throttle=False, brake=False, left=False, right=False):
        self.throttle = bool(throttle)
        self.brake = bool(brake)
        self.left = bool(left)
        self.right = bool(right)

    def __repr__(self):
        return "Command(throttle=%r, brake=%r, left=%r, right=%r)" % (
            self.throttle, self.brake, self.left, self.right)


class Controls(object):
    """把开关量输入积分成连续量，单位：0~limit 的踏板开度、-1~1 的方向盘位置。

    ``steer`` 正数 = 左打方向（与 V0 一致，HUD 也按这个习惯显示）。
    """

    def __init__(self, cfg=None):
        cfg = cfg or {}
        self.sens_throttle = float(cfg.get("sensitivity_throttle", 1.8))
        self.sens_brake = float(cfg.get("sensitivity_brake", 1.8))
        self.sens_steer = float(cfg.get("sensitivity_steer", 2.0))
        self.spring_back = float(cfg.get("spring_back", 2.1))
        self.throttle_limit = float(cfg.get("throttle_limit", 0.9))
        self.brake_limit = float(cfg.get("brake_limit", 0.8))
        self.dead_zone = float(cfg.get("steer_dead_zone", 0.1))
        self.reset()

    def reset(self):
        self.throttle = 0.0
        self.brake = 0.0
        self.steer = 0.0

    def update(self, command, dt):
        """按 dt 秒推进一帧输入，返回 (throttle, brake, steer)。"""
        self._update_steer(command, dt)
        self._update_pedals(command, dt)
        return self.throttle, self.brake, self.steer

    # ------------------------------------------------------------------ 内部
    def _update_steer(self, command, dt):
        if command.left and not command.right:
            self.steer += self.sens_steer * dt
        elif command.right and not command.left:
            self.steer -= self.sens_steer * dt
        else:
            # 松开回弹；中心虚位内直接归零，避免轻微抖动
            if self.steer >= self.dead_zone:
                self.steer -= self.spring_back * self.sens_steer * dt
            elif self.steer <= -self.dead_zone:
                self.steer += self.spring_back * self.sens_steer * dt
            else:
                self.steer = 0.0
        if self.steer > 1.0:
            self.steer = 1.0
        elif self.steer < -1.0:
            self.steer = -1.0

    def _update_pedals(self, command, dt):
        if command.throttle:
            if self.throttle < self.throttle_limit:
                self.throttle += self.sens_throttle * dt
                if self.throttle > self.throttle_limit:
                    self.throttle = self.throttle_limit
        elif self.throttle > 0.0:
            self.throttle -= self.spring_back * self.sens_throttle * dt
            if self.throttle < 0.0:
                self.throttle = 0.0

        if command.brake:
            if self.brake < self.brake_limit:
                self.brake += self.sens_brake * dt
                if self.brake > self.brake_limit:
                    self.brake = self.brake_limit
        elif self.brake > 0.0:
            self.brake -= self.spring_back * self.sens_brake * dt
            if self.brake < 0.0:
                self.brake = 0.0
