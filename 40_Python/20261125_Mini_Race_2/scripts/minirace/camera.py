# -*- coding: utf-8 -*-
"""世界坐标（米）<-> 屏幕坐标（像素）的相机换算（纯数学，不 import pygame）。

物理层只认米；渲染层通过本模块决定"显示哪一块世界、放大多少、怎么旋转"：

- :class:`Camera`：旧版固定/跟随相机（矩形世界，不旋转）；
- :class:`ChaseCamera`：赛道相机（V3.0），车固定在屏幕正中，画面按**实际速度方向**
  旋转（速度朝上），并做角度平滑/低速冻结，详见该类文档。
"""
import math


def _clamp(value, low, high):
    if value < low:
        return low
    if value > high:
        return high
    return value


class ChaseCamera(object):
    """赛道模式相机：车固定在屏幕正中，画面按"实际速度方向朝上"旋转。

    - 屏幕上方 = 世界速度方向（不是车头朝向）；倒车时速度向量的方向同样朝上，
      所以不会出现"倒着开画面翻转"；角度连续插值，不做 180° 翻转；
    - 速度低于 ``freeze_speed`` 时冻结角度（避免低速抖动/停车后乱转）；
    - 车始终在屏幕正中（在 ±10% 容差内，实际就是 0 偏移）。

    只在渲染层使用；所有物理量仍是世界坐标（米）。
    """

    def __init__(self, screen_width, screen_height, pixels_per_meter,
                 angle_rate=5.0, freeze_speed=1.5, max_angle_rate=6.0):
        if screen_width <= 0 or screen_height <= 0:
            raise ValueError("屏幕尺寸必须为正数")
        if pixels_per_meter <= 0:
            raise ValueError("pixels_per_meter 必须为正数")
        self.screen_width = float(screen_width)
        self.screen_height = float(screen_height)
        self.pixels_per_meter = float(pixels_per_meter)
        self.center_x = 0.0
        self.center_y = 0.0
        self.angle = None
        self.angle_rate = max(0.1, float(angle_rate))
        self.freeze_speed = max(0.0, float(freeze_speed))
        self.max_angle_rate = max(0.1, float(max_angle_rate))
        self.frozen = True

    # ------------------------------------------------------------------ 几何
    @property
    def view_width_m(self):
        return self.screen_width / self.pixels_per_meter

    @property
    def view_height_m(self):
        return self.screen_height / self.pixels_per_meter

    def meters_to_pixels(self, meters):
        return meters * self.pixels_per_meter

    def pixels_to_meters(self, pixels):
        return pixels / self.pixels_per_meter

    # ------------------------------------------------------------------ 相机
    def update(self, target_x, target_y, world_vx, world_vy, speed, dt,
               reverse=False):
        """更新相机中心与旋转角（target 永远在屏幕正中）。"""
        self.center_x = float(target_x)
        self.center_y = float(target_y)
        dt = max(1e-4, min(0.1, float(dt)))
        if speed >= self.freeze_speed and (abs(world_vx) + abs(world_vy)) > 1e-6:
            target_angle = math.atan2(world_vy, world_vx)
            if reverse:
                target_angle += math.pi
            if self.angle is None:
                self.angle = target_angle
            else:
                delta = self._wrap(target_angle - self.angle)
                # 先平滑再限速：大角度（如倒车/掉头）能在 ~0.5 s 内跟上，同时不会猛转
                step = delta * min(1.0, self.angle_rate * dt)
                max_step = self.max_angle_rate * dt
                step = max(-max_step, min(max_step, step))
                self.angle += step
            self.frozen = False
        else:
            self.frozen = True
        if self.angle is None:
            self.angle = math.pi / 2.0

    def reset_angle(self, heading):
        self.angle = float(heading)
        self.frozen = True

    @staticmethod
    def _wrap(angle):
        while angle > math.pi:
            angle -= math.pi * 2.0
        while angle < -math.pi:
            angle += math.pi * 2.0
        return angle

    # ------------------------------------------------------------------ 变换
    def world_to_screen(self, x, y):
        dx = x - self.center_x
        dy = y - self.center_y
        cos_a = math.cos(self.angle)
        sin_a = math.sin(self.angle)
        sx = dx * sin_a - dy * cos_a
        sy = -(dx * cos_a + dy * sin_a)
        return (self.screen_width / 2.0 + sx * self.pixels_per_meter,
                self.screen_height / 2.0 + sy * self.pixels_per_meter)

    def screen_to_world(self, sx, sy):
        cos_a = math.cos(self.angle)
        sin_a = math.sin(self.angle)
        sx_m = (sx - self.screen_width / 2.0) / self.pixels_per_meter
        sy_m = (sy - self.screen_height / 2.0) / self.pixels_per_meter
        dx = sx_m * sin_a - sy_m * cos_a
        dy = -sx_m * cos_a - sy_m * sin_a
        return (self.center_x + dx, self.center_y + dy)

    def visible_rect(self):
        """可见区域的世界 AABB（旋转后取四个角的包围盒）。"""
        corners = [self.screen_to_world(0.0, 0.0),
                   self.screen_to_world(self.screen_width, 0.0),
                   self.screen_to_world(0.0, self.screen_height),
                   self.screen_to_world(self.screen_width, self.screen_height)]
        xs = [point[0] for point in corners]
        ys = [point[1] for point in corners]
        return (min(xs), min(ys), max(xs), max(ys))

    def clipped_rect(self):
        return self.visible_rect()


class Camera(object):
    def __init__(self, screen_width, screen_height, world_width, world_height,
                 pixels_per_meter, follow=True):
        if screen_width <= 0 or screen_height <= 0:
            raise ValueError("屏幕尺寸必须为正数")
        if world_width <= 0 or world_height <= 0:
            raise ValueError("世界尺寸必须为正数")
        if pixels_per_meter <= 0:
            raise ValueError("pixels_per_meter 必须为正数")
        self.screen_width = float(screen_width)
        self.screen_height = float(screen_height)
        self.world_width = float(world_width)
        self.world_height = float(world_height)
        self.pixels_per_meter = float(pixels_per_meter)
        self.follow = bool(follow)
        self.center_x = self.world_width / 2.0
        self.center_y = self.world_height / 2.0

    # ------------------------------------------------------------------ 几何
    @property
    def view_width_m(self):
        return self.screen_width / self.pixels_per_meter

    @property
    def view_height_m(self):
        return self.screen_height / self.pixels_per_meter

    def meters_to_pixels(self, meters):
        return meters * self.pixels_per_meter

    def pixels_to_meters(self, pixels):
        return pixels / self.pixels_per_meter

    # ------------------------------------------------------------------ 相机
    def update(self, target_x, target_y):
        """更新相机中心（follow=True 时把目标夹在世界的可视范围内）。"""
        if not self.follow:
            self.center_x = self.world_width / 2.0
            self.center_y = self.world_height / 2.0
            return
        half_w = self.view_width_m / 2.0
        half_h = self.view_height_m / 2.0
        if self.world_width >= 2.0 * half_w:
            self.center_x = _clamp(target_x, half_w, self.world_width - half_w)
        else:
            self.center_x = self.world_width / 2.0
        if self.world_height >= 2.0 * half_h:
            self.center_y = _clamp(target_y, half_h, self.world_height - half_h)
        else:
            self.center_y = self.world_height / 2.0

    # ------------------------------------------------------------------ 变换
    def world_to_screen(self, x, y):
        """世界坐标（米，y 向上）-> 屏幕坐标（像素，y 向下，可为浮点）。"""
        return (self.screen_width / 2.0 + (x - self.center_x) * self.pixels_per_meter,
                self.screen_height / 2.0 - (y - self.center_y) * self.pixels_per_meter)

    def screen_to_world(self, sx, sy):
        return (self.center_x + (sx - self.screen_width / 2.0) / self.pixels_per_meter,
                self.center_y - (sy - self.screen_height / 2.0) / self.pixels_per_meter)

    def visible_rect(self):
        """当前可见的世界矩形 (x0, y0, x1, y1)，单位米，未裁剪到世界边界。"""
        half_w = self.view_width_m / 2.0
        half_h = self.view_height_m / 2.0
        return (self.center_x - half_w, self.center_y - half_h,
                self.center_x + half_w, self.center_y + half_h)

    def clipped_rect(self):
        """可见矩形裁剪到世界范围内；返回 (x0, y0, x1, y1) 或 None。"""
        x0, y0, x1, y1 = self.visible_rect()
        cx0 = _clamp(x0, 0.0, self.world_width)
        cy0 = _clamp(y0, 0.0, self.world_height)
        cx1 = _clamp(x1, 0.0, self.world_width)
        cy1 = _clamp(y1, 0.0, self.world_height)
        if cx1 <= cx0 or cy1 <= cy0:
            return None
        return (cx0, cy0, cx1, cy1)
