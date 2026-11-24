# -*- coding: utf-8 -*-
"""行驶方向提示（纯数学，可单测）。

WRONG WAY：车头朝向与赛道中心线前进方向的夹角超过 120° 并持续 1.5 s 后触发；
显示 1 s、消失 1 s 循环，每次进入"显示"相位时提示音；车头转回 120° 内后隐藏并
重置 1.5 s 计时。
"""
import math


class WrongWayMonitor(object):
    THRESHOLD_DEG = 120.0
    DELAY = 1.5
    BLINK_ON = 1.0
    BLINK_OFF = 1.0

    def __init__(self):
        self.reset()

    def reset(self):
        self._wrong_time = 0.0
        self.active = False
        self.visible = False
        self.time_wrong = 0.0
        self._blink_on = False

    def update(self, angle_error, dt):
        """``angle_error``：车头方向 - 中心线方向（弧度，已 wrap）。

        返回 ``(active, visible, beep)``。
        """
        dt = max(0.0, float(dt))
        if abs(float(angle_error)) <= math.radians(self.THRESHOLD_DEG):
            was_active = self.active
            self.reset()
            return False, False, False
        self._wrong_time += dt
        self.time_wrong = self._wrong_time
        self.active = self._wrong_time >= self.DELAY
        if not self.active:
            self.visible = False
            return False, False, False
        elapsed = self._wrong_time - self.DELAY
        phase = int(elapsed // self.BLINK_ON)
        visible = (phase % 2 == 0)
        beep = visible and not self._blink_on
        self._blink_on = visible
        self.visible = visible
        return True, visible, beep
