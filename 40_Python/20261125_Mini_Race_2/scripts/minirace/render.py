# -*- coding: utf-8 -*-
"""pygame 渲染层：背景、轨迹、车、HUD。

世界坐标一律是 **米**（物理层输出），本层通过 :class:`minirace.camera.Camera`
把世界映射到屏幕像素：

- ``render.pixels_per_meter``：显示缩放，只影响画面；
- ``render.follow_car``：世界比视野大时相机跟随车辆；
- 背景贴图被映射到 ``world.width_m × world.height_m`` 的整个矩形上，
  所以改世界大小/缩放/相机都不会改变任何物理量。

HUD 显示实际值：速度、发动机转速/挡位、踏板/方向盘开度、实际纵/横向加速度、
附着利用率、前轮转角、转弯半径、车身侧偏角，以及打滑状态和摩擦圆示波器。
另外显示当前显示缩放和世界尺寸，方便调整场地/镜头。
"""
import math
import os

import pygame
from pygame.locals import (
    K_a, K_d, K_DOWN, K_ESCAPE, K_F2, K_F5, K_F9, K_HOME, K_LEFT, K_m, K_p,
    K_r, K_RIGHT, K_s, K_UP, K_w,
)

from minirace import __version__
from minirace.ai_colors import AI_OUTLINE, ai_rgb
from minirace.camera import Camera, ChaseCamera
from minirace.laptiming import format_time
from minirace.ranking import format_gap, ordinal
from minirace.track import Track
from minirace.zoom import adjust_level, zoom_factor, zoom_label

WHITE = (232, 236, 242)
DIM = (138, 148, 164)
GREEN = (96, 222, 132)
YELLOW = (240, 212, 92)
RED = (242, 96, 88)
ORANGE = (255, 168, 64)
BLUE = (92, 168, 255)
CYAN = (96, 216, 232)
PANEL_BG = (8, 10, 14, 190)
PANEL_BORDER = (70, 80, 96)
OUTSIDE_COLOR = (22, 26, 30)
GRASS = (74, 124, 64)
ASPHALT = (52, 54, 58)
TRACK_WHITE = (235, 235, 235)
TRAIL_TRACK = (120, 220, 255)
TRAIL_OLD = (42, 56, 70)

PANEL_W = 650
PANEL_H = 340
PANEL_POS = (16, 14)
PRESSED_COLOR = (120, 240, 160)

# 底部按键说明：按 (文本, 关联键码元组, 类型) 切成 token，按下时单独换色。
# 类型：key（可高亮按键）/ desc（说明文字）/ sep（分隔符）
HELP_TOKENS = (
    ("W", (K_w,), "key"), ("/", (), "sep"), ("UP", (K_UP,), "key"),
    (" throttle    ", (), "desc"),
    ("S", (K_s,), "key"), ("/", (), "sep"), ("DOWN", (K_DOWN,), "key"),
    (" brake    ", (), "desc"),
    ("A", (K_a,), "key"), ("/", (), "sep"), ("LEFT", (K_LEFT,), "key"),
    ("  ", (), "desc"),
    ("D", (K_d,), "key"), ("/", (), "sep"), ("RIGHT", (K_RIGHT,), "key"),
    (" steer    ", (), "desc"),
    ("R", (K_r,), "key"), (" gear    ", (), "desc"),
    ("M", (K_m,), "key"), (" mute    ", (), "desc"),
    ("P", (K_p,), "key"), (" pause    ", (), "desc"),
    ("F5", (K_F5,), "key"), (" reset pos   ", (), "desc"),
    ("F2", (K_F2,), "key"), (" map    ", (), "desc"),
    ("HOME", (K_HOME,), "key"), (" reset    ", (), "desc"),
    ("F9", (K_F9,), "key"), (" diag    ", (), "desc"),
    ("ESC", (K_ESCAPE,), "key"), (" quit", (), "desc"),
)


def _clamp(value, low, high):
    if value < low:
        return low
    if value > high:
        return high
    return value


def _load_image(project_dir, rel_path):
    path = rel_path if os.path.isabs(rel_path) else os.path.join(str(project_dir), rel_path)
    return pygame.image.load(path)


class Renderer(object):
    def __init__(self, screen, config, project_dir):
        self.screen = screen
        self.width, self.height = screen.get_size()
        self.config = config or {}

        world = self.config.get("world", {}) or {}
        self.world_width = float(world.get("width_m", 129.6))
        self.world_height = float(world.get("height_m", 81.0))

        scale = self.config.get("scale", {}) or {}
        self.gravity = float(scale.get("gravity", 9.81) or 9.81)
        tires = self.config.get("tires", {}) or {}
        self.friction = float(tires.get("friction", 1.1) or 1.1)
        drivetrain = self.config.get("drivetrain", {}) or {}
        self.redline_rpm = float(drivetrain.get("redline_rpm", 7000.0) or 7000.0)
        self.idle_rpm = float(drivetrain.get("idle_rpm", 900.0) or 900.0)

        render = self.config.get("render", {}) or {}
        self.show_hud = bool(render.get("show_hud", True))
        self.show_help = bool(render.get("show_help", True))
        self.show_trail = bool(render.get("show_trail", True))
        self.pixels_per_meter = float(render.get("pixels_per_meter", 11.111111) or 11.111111)
        self.follow_car = bool(render.get("follow_car", True))

        track_cfg = self.config.get("track", {}) or {}
        try:
            self.track = Track(project_dir, self.config)
        except (IOError, OSError, ValueError, KeyError):
            self.track = Track(project_dir, {"track": {"enabled": False}})
        self.track_mode = self.track.enabled
        if self.track_mode:
            camera_cfg = track_cfg.get("camera", {}) or {}
            self.pixels_per_meter = float(
                camera_cfg.get("pixels_per_meter", 5.0) or 5.0)
            self.camera = ChaseCamera(
                self.width, self.height, self.pixels_per_meter,
                angle_rate=float(camera_cfg.get("angle_rate", 5.0)),
                freeze_speed=float(camera_cfg.get("freeze_speed", 1.5)),
                max_angle_rate=float(camera_cfg.get("max_angle_rate", 6.0)))
        else:
            self.camera = Camera(self.width, self.height, self.world_width,
                                 self.world_height, self.pixels_per_meter,
                                 follow=self.follow_car)
            background = _load_image(
                project_dir, render.get("background", "images/track.jpg"))
            self.background = background.convert()
            self.background_width, self.background_height = self.background.get_size()
        self._camera_heading_hint = None

        sprite = _load_image(project_dir, render.get("car_sprite", "images/red-car-small.png"))
        self.sprite = sprite.convert_alpha()
        self.sprite_width, self.sprite_height = self.sprite.get_size()

        self.font_small = pygame.font.SysFont("consolas", 16)
        self.font = pygame.font.SysFont("consolas", 18)
        self.font_mid = pygame.font.SysFont("consolas", 24, bold=True)
        self.font_big = pygame.font.SysFont("consolas", 52, bold=True)

        self.panel = pygame.Surface((PANEL_W, PANEL_H), pygame.SRCALPHA)
        self.panel.fill(PANEL_BG)
        pygame.draw.rect(self.panel, PANEL_BORDER, self.panel.get_rect(), 1)

        self.help_token_widths = [
            self.font_small.size(text)[0] for text, _keys, _kind in HELP_TOKENS]
        help_width = sum(self.help_token_widths) + 20
        help_height = self.font_small.get_height() + 10
        self.help_bg = pygame.Surface((help_width, help_height), pygame.SRCALPHA)
        self.help_bg.fill(PANEL_BG)
        minimap = render.get("minimap", {}) or {}
        self.minimap_enabled = bool(minimap.get("enabled", True))
        self.minimap_width = int(minimap.get("width", 240))
        self.minimap_height = int(minimap.get("height", 170))
        self.minimap_margin = int(minimap.get("margin", 14))
        if self.track_mode:
            active_map = self.config.get("active_map") or {}
            display_name = active_map.get("display_name") or "CIRCUIT"
            if active_map.get("number") not in (None, ""):
                display_name = "[%s] %s" % (active_map.get("number"), display_name)
            self.title = self.font.render(
                "MINI RACE 2 v%s  ·  %s" % (__version__, display_name), True, DIM)
        else:
            self.title = self.font.render(
                "MINI RACE 2 v%s  ·  VEHICLE SIMULATOR" % __version__, True, DIM)

        # 显示倍率：7 档，进入/切换地图时回到默认 0 档
        self.base_pixels_per_meter = float(self.camera.pixels_per_meter)
        self.pixels_per_meter = self.base_pixels_per_meter
        self.zoom_level = 0

    # ------------------------------------------------------------------ 缩放
    def set_zoom_level(self, level):
        """设置绝对档位（切换地图时用于保留本次窗口内的倍率）。"""
        self.zoom_level = max(-3, min(3, int(level)))
        self.pixels_per_meter = (self.base_pixels_per_meter
                                 * zoom_factor(self.zoom_level))
        self.camera.pixels_per_meter = self.pixels_per_meter
        return self.zoom_level

    def adjust_zoom(self, delta):
        return self.set_zoom_level(adjust_level(self.zoom_level, delta))

    def zoom_text(self):
        return zoom_label(self.zoom_level)

    # ------------------------------------------------------------------ 对外
    def draw(self, sim, stats=None):
        stats = stats or {}
        frame_dt = float(stats.get("frame_dt", 1.0 / 60.0))
        if self.track_mode:
            heading = sim.vehicle.heading
            if self.camera.angle is None:
                self.camera.reset_angle(
                    self._camera_heading_hint if self._camera_heading_hint is not None
                    else heading)
            cos_h = math.cos(heading)
            sin_h = math.sin(heading)
            world_vx = sim.vehicle.vx * cos_h - sim.vehicle.vy * sin_h
            world_vy = sim.vehicle.vx * sin_h + sim.vehicle.vy * cos_h
            speed = math.hypot(world_vx, world_vy)
            self.camera.update(sim.vehicle.x, sim.vehicle.y,
                               world_vx, world_vy, speed, frame_dt,
                               reverse=(getattr(sim.vehicle, "gear", 1) < 0))
        else:
            self.camera.update(sim.vehicle.x, sim.vehicle.y)
        self._draw_background()
        if self.show_trail:
            self._draw_trail(sim)
        self._draw_ai_cars(stats.get("ai_cars") or [])
        self._draw_car(sim)
        if self.show_hud:
            self._draw_hud(sim, stats)
        if self.show_help:
            self._draw_help()
        if self.track_mode:
            self._draw_timing(stats)
            self._draw_standings(stats)
            self._draw_corners(stats)
            self._draw_minimap(sim, stats)
            if stats.get("map_notice"):
                self._draw_map_notice(stats)
        if self.track_mode:
            title_y = (self.height - self.help_bg.get_height() - 9
                       - self.title.get_height() - 6)
            self.screen.blit(self.title,
                             (self.width // 2 - self.title.get_width() // 2, title_y))
            diag_y = 136
        else:
            self.screen.blit(self.title, (self.width - self.title.get_width() - 18, 18))
            diag_y = 44
        if stats.get("diag"):
            diag_text = "● DIAG REC   events %d" % stats.get("diag_events", 0)
            diag_surface = self.font_small.render(diag_text, True, RED)
            self.screen.blit(diag_surface,
                             (self.width - diag_surface.get_width() - 18, diag_y))
        if stats.get("wrong_way_active") and stats.get("wrong_way_visible"):
            self._draw_wrong_way()
        if stats.get("paused"):
            self._draw_paused()

    def reset_camera(self):
        """HOME 复位后让镜头重新对准车头方向（速度低于阈值时用）。"""
        self._camera_heading_hint = None
        if self.track_mode:
            self.camera.angle = None

    # ------------------------------------------------------------------ 背景
    def _draw_background(self):
        if self.track_mode:
            self._draw_track()
        else:
            self._draw_old_background()

    def _draw_track(self):
        """画草皮 + 沥青带 + 白色边界 + 起跑线（世界坐标点随相机旋转）。"""
        if self.track.kind == "circle":
            self._draw_circle_pad()
            return
        self.screen.fill(GRASS)
        camera = self.camera
        points = self.track.points
        if not points:
            return
        screen_points = [camera.world_to_screen(x, y) for x, y in points]
        # 沥青带：粗线 + 每个顶点补圆（圆角连接，急弯处不留缺口）
        track_width_px = int(round(self.track.width_m * camera.pixels_per_meter))
        track_width_px = max(3, track_width_px)
        pygame.draw.lines(self.screen, ASPHALT, True, screen_points, track_width_px)
        asphalt_radius = track_width_px // 2
        for point in screen_points:
            pygame.draw.circle(self.screen, ASPHALT,
                               (int(point[0]), int(point[1])), asphalt_radius)

        # 白色边界：用预计算好的左/右边界折线（比"白粗线再盖沥青"干净）
        edge_width = max(2, int(round(0.12 * camera.pixels_per_meter)) + 1)
        for edge in (self.track.left_edge, self.track.right_edge):
            if not edge:
                continue
            edge_points = [camera.world_to_screen(x, y) for x, y in edge]
            pygame.draw.lines(self.screen, TRACK_WHITE, True, edge_points, edge_width)

        # 起跑线：起点处垂直于赛道方向的一条白线
        start_x, start_y, _heading = self.track.start
        count = len(points)
        next_point = points[1 % count]
        tangent_x = next_point[0] - start_x
        tangent_y = next_point[1] - start_y
        tangent_length = math.hypot(tangent_x, tangent_y)
        if tangent_length > 1e-9:
            normal_x = -tangent_y / tangent_length
            normal_y = tangent_x / tangent_length
            half = self.track.width_m * 0.5
            line = [camera.world_to_screen(start_x + normal_x * half,
                                           start_y + normal_y * half),
                    camera.world_to_screen(start_x - normal_x * half,
                                           start_y - normal_y * half)]
            pygame.draw.line(self.screen, TRACK_WHITE, line[0], line[1], 4)

    def _draw_circle_pad(self):
        """圆形试车场：Ø400 m 沥青空地 + Ø360 m 白色虚线（不是墙）。"""
        self.screen.fill(GRASS)
        camera = self.camera
        center_x, center_y = self.track.center
        center_screen = camera.world_to_screen(center_x, center_y)
        outer_px = int(round(self.track.outer_radius_m * camera.pixels_per_meter))
        if outer_px < 4:
            return
        pygame.draw.circle(self.screen, ASPHALT,
                           (int(center_screen[0]), int(center_screen[1])), outer_px)
        pygame.draw.circle(self.screen, TRACK_WHITE,
                           (int(center_screen[0]), int(center_screen[1])), outer_px, 4)

        # 虚线参考圆：沿圆周画短弧段
        guide_radius = self.track.guide_radius_m
        if guide_radius > 0.0:
            dash_m, gap_m = 6.0, 6.0
            count = max(16, int(round(2.0 * math.pi * guide_radius / (dash_m + gap_m))))
            step = 2.0 * math.pi / count
            dash = step * dash_m / (dash_m + gap_m)
            edge_width = max(2, int(round(0.1 * camera.pixels_per_meter)) + 1)
            for index in range(count):
                angle = 2.0 * math.pi * index / count
                points = []
                for sub in range(4):
                    a = angle + dash * sub / 3.0
                    points.append(camera.world_to_screen(
                        center_x + guide_radius * math.cos(a),
                        center_y + guide_radius * math.sin(a)))
                pygame.draw.lines(self.screen, TRACK_WHITE, False, points, edge_width)

        # 起点线：在虚线圆顶部（车面向左，起跑线沿半径方向）
        start_x, start_y, _heading = self.track.start
        pygame.draw.line(self.screen, TRACK_WHITE,
                         camera.world_to_screen(start_x, start_y - 6.0),
                         camera.world_to_screen(start_x, start_y + 6.0), 4)

    # ------------------------------------------------------------------ 弯道提示
    def _draw_corners(self, stats):
        """5 要素弯道窗口：中间要素橙色高亮，下方小三角指向它。"""
        labels = stats.get("corner_labels")
        if not labels:
            return
        width = 160
        height = 42
        x = self.width - 16 - width
        y = 14 + 64 + 6
        panel = pygame.Surface((width, height), pygame.SRCALPHA)
        panel.fill(PANEL_BG)
        pygame.draw.rect(panel, PANEL_BORDER, panel.get_rect(), 1)
        self.screen.blit(panel, (x, y))
        center_index = int(stats.get("corner_center", 2))
        slot = width / float(len(labels))
        for index, label in enumerate(labels):
            cx = x + slot * (index + 0.5)
            if index == center_index:
                color = ORANGE
            elif label == "-":
                color = DIM
            else:
                color = WHITE
            surface = self.font.render(label, True, color)
            self.screen.blit(surface, (int(cx - surface.get_width() / 2),
                                       y + 7))
        center_x = x + slot * (center_index + 0.5)
        triangle = [(center_x, y + 29), (center_x - 5, y + 38),
                    (center_x + 5, y + 38)]
        pygame.draw.polygon(self.screen, ORANGE, triangle)

    # ------------------------------------------------------------------ 圈速
    def _draw_timing(self, stats):
        """右上角：圈数 / 当前圈时间 / 最快圈；圆形试车场只显示当前时间。"""
        lap_enabled = bool(stats.get("lap_enabled", False))
        width = 400 if lap_enabled else 232
        height = 64
        x = self.width - 16 - width
        y = 14
        panel = pygame.Surface((width, height), pygame.SRCALPHA)
        panel.fill(PANEL_BG)
        pygame.draw.rect(panel, PANEL_BORDER, panel.get_rect(), 1)
        self.screen.blit(panel, (x, y))

        def label(text, lx):
            self.screen.blit(self.font_small.render(text, True, DIM),
                             (lx, y + 7))

        def value(text, vx, color=WHITE):
            self.screen.blit(self.font_mid.render(text, True, color),
                             (vx, y + 24))

        lap_time = float(stats.get("lap_time", 0.0) or 0.0)
        if lap_enabled:
            label("LAP", x + 16)
            value("%d" % int(stats.get("lap", 1)), x + 16)
            label("TIME", x + 92)
            value(format_time(lap_time), x + 92)
            label("BEST", x + 262)
            best = stats.get("best_lap")
            value(format_time(best), x + 262,
                  GREEN if best is not None else DIM)
        else:
            label("TIME", x + 16)
            value(format_time(lap_time), x + 16)

    def _draw_standings(self, stats):
        """右上角名次表：总是 4 行以内（第一名/玩家前后）。"""
        rows = stats.get("standings") or []
        if not rows or self.track is None or self.track.kind != "circuit":
            return
        player_row = next((row for row in rows if row.is_player), None)
        width = 400
        line_h = 22
        height = 8 + line_h * len(rows)
        x = self.width - 16 - width
        y = 14 + 64 + 6 + 42 + 6
        panel = pygame.Surface((width, height), pygame.SRCALPHA)
        panel.fill(PANEL_BG)
        pygame.draw.rect(panel, PANEL_BORDER, panel.get_rect(), 1)
        self.screen.blit(panel, (x, y))
        for index, row in enumerate(rows):
            gap = format_gap(row, player_row, self.track.lap_length_m)
            best = format_time(row.best_lap)
            text = "%s  %-7s  %6s  %s" % (
                ordinal(row.rank), row.name, gap, best)
            color = YELLOW if row.is_player else WHITE
            surface = self.font_small.render(text, True, color)
            self.screen.blit(surface, (x + 10, y + 5 + line_h * index))

    # ------------------------------------------------------------------ 缩略图
    def _minimap_rect(self):
        help_h = self.help_bg.get_height() if self.show_help else 0
        y = self.height - help_h - 16 - self.minimap_height
        y = max(80, y)
        return (self.width - self.minimap_margin - self.minimap_width, y,
                self.minimap_width, self.minimap_height)

    def _draw_minimap(self, sim, stats):
        """右下角赛道缩略图（不旋转）：赛道形状 + 起点 + 自车位置。"""
        if not self.minimap_enabled:
            return
        x, y, width, height = self._minimap_rect()
        panel = pygame.Surface((width, height), pygame.SRCALPHA)
        panel.fill(PANEL_BG)
        pygame.draw.rect(panel, PANEL_BORDER, panel.get_rect(), 1)
        self.screen.blit(panel, (x, y))

        active_map = self.config.get("active_map") or {}
        title = active_map.get("display_name") or "MAP"
        if active_map.get("number") not in (None, ""):
            title = "[%s] %s" % (active_map.get("number"), title)
        self.screen.blit(self.font_small.render("MAP · " + title, True, WHITE),
                         (x + 8, y + 4))

        if self.track.kind == "circle":
            min_x = self.track.center[0] - self.track.outer_radius_m
            min_y = self.track.center[1] - self.track.outer_radius_m
            max_x = self.track.center[0] + self.track.outer_radius_m
            max_y = self.track.center[1] + self.track.outer_radius_m
        else:
            xs = [point[0] for point in self.track.points]
            ys = [point[1] for point in self.track.points]
            pad = self.track.width_m
            min_x, min_y = min(xs) - pad, min(ys) - pad
            max_x, max_y = max(xs) + pad, max(ys) + pad

        pad_px = 10
        top = 22
        span_x = max(1.0, max_x - min_x)
        span_y = max(1.0, max_y - min_y)
        scale = min((width - pad_px * 2) / span_x,
                    (height - top - pad_px * 2) / span_y)
        offset_x = x + pad_px + (width - pad_px * 2 - span_x * scale) * 0.5
        offset_y = y + top + pad_px + (height - top - pad_px * 2 - span_y * scale) * 0.5

        def to_map(wx, wy):
            return (offset_x + (wx - min_x) * scale,
                    offset_y + (max_y - wy) * scale)

        if self.track.kind == "circle":
            center = to_map(self.track.center[0], self.track.center[1])
            radius = int(round(self.track.outer_radius_m * scale))
            pygame.draw.circle(self.screen, (180, 186, 196),
                               (int(center[0]), int(center[1])), radius, 2)
            guide = int(round(self.track.guide_radius_m * scale))
            # 虚线圆：缩略图上用 40 段短弧
            segments = 40
            for index in range(0, segments, 2):
                a0 = 2.0 * math.pi * index / segments
                a1 = 2.0 * math.pi * (index + 1) / segments
                pygame.draw.line(
                    self.screen, (210, 214, 222),
                    to_map(self.track.center[0] + self.track.guide_radius_m * math.cos(a0),
                           self.track.center[1] + self.track.guide_radius_m * math.sin(a0)),
                    to_map(self.track.center[0] + self.track.guide_radius_m * math.cos(a1),
                           self.track.center[1] + self.track.guide_radius_m * math.sin(a1)),
                    1)
        else:
            track_width = max(2, int(round(self.track.width_m * scale * 1.2)))
            map_points = [to_map(point[0], point[1]) for point in self.track.points]
            pygame.draw.lines(self.screen, (180, 186, 196), True, map_points,
                              track_width)

        start_x, start_y, _heading = self.track.start
        start_map = to_map(start_x, start_y)
        pygame.draw.circle(self.screen, GREEN,
                           (int(start_map[0]), int(start_map[1])), 4)
        pygame.draw.circle(self.screen, WHITE,
                           (int(start_map[0]), int(start_map[1])), 4, 1)

        # AI：小彩色三角（和玩家车一样不旋转，只做缩略图标记）
        for ai_index, ai_telem in enumerate(stats.get("ai_cars") or []):
            if ai_telem is None:
                continue
            ai_map = to_map(ai_telem.x, ai_telem.y)
            ai_forward = (math.cos(ai_telem.heading), -math.sin(ai_telem.heading))
            ai_side = (-ai_forward[1], ai_forward[0])
            ai_nose = (ai_map[0] + ai_forward[0] * 5.0,
                       ai_map[1] + ai_forward[1] * 5.0)
            ai_rear_l = (ai_map[0] - ai_forward[0] * 2.0 + ai_side[0] * 2.0,
                         ai_map[1] - ai_forward[1] * 2.0 + ai_side[1] * 2.0)
            ai_rear_r = (ai_map[0] - ai_forward[0] * 2.0 - ai_side[0] * 2.0,
                         ai_map[1] - ai_forward[1] * 2.0 - ai_side[1] * 2.0)
            ai_color = ai_rgb(ai_index)
            pygame.draw.polygon(self.screen, ai_color,
                                [ai_nose, ai_rear_l, ai_rear_r])
            pygame.draw.polygon(self.screen, AI_OUTLINE,
                                [ai_nose, ai_rear_l, ai_rear_r], 1)

        # 自车：红色小三角形（方向随 heading，缩略图本身不旋转）
        car_map = to_map(sim.vehicle.x, sim.vehicle.y)
        heading = sim.vehicle.heading
        forward = (math.cos(heading), -math.sin(heading))
        side = (-forward[1], forward[0])
        nose = (car_map[0] + forward[0] * 6.0, car_map[1] + forward[1] * 6.0)
        rear_l = (car_map[0] - forward[0] * 3.0 + side[0] * 3.0,
                  car_map[1] - forward[1] * 3.0 + side[1] * 3.0)
        rear_r = (car_map[0] - forward[0] * 3.0 - side[0] * 3.0,
                  car_map[1] - forward[1] * 3.0 - side[1] * 3.0)
        pygame.draw.polygon(self.screen, RED, [nose, rear_l, rear_r])
        pygame.draw.polygon(self.screen, WHITE, [nose, rear_l, rear_r], 1)

    def _draw_wrong_way(self):
        text = "[WRONG WAY]"
        surface = self.font_mid.render(text, True, ORANGE)
        x = self.width // 2 - surface.get_width() // 2
        y = self.height // 3 - surface.get_height() // 2
        box = pygame.Surface((surface.get_width() + 20,
                              surface.get_height() + 10), pygame.SRCALPHA)
        box.fill(PANEL_BG)
        pygame.draw.rect(box, ORANGE, box.get_rect(), 1)
        self.screen.blit(box, (x - 10, y - 5))
        self.screen.blit(surface, (x, y))

    def _draw_map_notice(self, stats):
        number = stats.get("map_number", "")
        prefix = ("[%s] " % number) if number not in (None, "") else ""
        title = "MAP %s%s" % (prefix, stats.get("map_display_name", ""))
        detail_lines = []
        if stats.get("map_kind") != "circle":
            length = stats.get("map_length_m")
            if length:
                detail_lines.append(("LENGTH  %.1f m" % float(length), DIM))
            best = stats.get("map_best_lap")
            detail_lines.append(("BEST    " + format_time(best),
                                 GREEN if best is not None else DIM))
        title_surface = self.font_mid.render(title, True, YELLOW)
        detail_surfaces = [(self.font_small.render(text, True, color), color)
                           for text, color in detail_lines]
        width = title_surface.get_width()
        for surface, _color in detail_surfaces:
            width = max(width, surface.get_width())
        line_height = self.font_small.get_height()
        height = title_surface.get_height() + 6 + line_height * len(detail_lines) + 8
        box = pygame.Surface((width + 18, height), pygame.SRCALPHA)
        box.fill(PANEL_BG)
        pygame.draw.rect(box, PANEL_BORDER, box.get_rect(), 1)
        x, y, mini_width, _mini_height = self._minimap_rect()
        box_x = x + mini_width - box.get_width()
        box_y = y - box.get_height() - 6
        self.screen.blit(box, (box_x, box_y))
        self.screen.blit(title_surface, (box_x + 9, box_y + 4))
        offset_y = box_y + title_surface.get_height() + 5
        for surface, _color in detail_surfaces:
            self.screen.blit(surface, (box_x + 9, offset_y))
            offset_y += line_height

    def _draw_old_background(self):
        """旧版：把背景贴图按世界矩形映射到相机可见区域。"""
        self.screen.fill(OUTSIDE_COLOR)
        rect = self.camera.clipped_rect()
        if rect is None:
            return
        x0, y0, x1, y1 = rect
        img_w, img_h = self.background_width, self.background_height

        sx0 = int(round(x0 / self.world_width * img_w))
        sx1 = int(round(x1 / self.world_width * img_w))
        # 图片 y 向下 = 世界 y 向下（世界 y 向上，所以翻转）
        sy0 = int(round((self.world_height - y1) / self.world_height * img_h))
        sy1 = int(round((self.world_height - y0) / self.world_height * img_h))
        sx0 = max(0, min(img_w - 1, sx0))
        sx1 = max(sx0 + 1, min(img_w, sx1))
        sy0 = max(0, min(img_h - 1, sy0))
        sy1 = max(sy0 + 1, min(img_h, sy1))

        left, top = self.camera.world_to_screen(x0, y1)
        right, bottom = self.camera.world_to_screen(x1, y0)
        dest_w = max(1, int(round(right - left)))
        dest_h = max(1, int(round(bottom - top)))
        sub = self.background.subsurface((sx0, sy0, sx1 - sx0, sy1 - sy0))
        if dest_w == sx1 - sx0 and dest_h == sy1 - sy0:
            # 1:1 时直接 blit，省一次缩放（默认配置走这里）
            scaled = sub
        else:
            scaled = pygame.transform.scale(sub, (dest_w, dest_h))
        self.screen.blit(scaled, (int(round(left)), int(round(top))))

    # ------------------------------------------------------------------ 世界
    def _draw_trail(self, sim):
        points = [self.camera.world_to_screen(x, y) for x, y in sim.trail]
        count = len(points)
        line_width = int(round(_clamp(self.camera.meters_to_pixels(0.18), 1, 4)))
        for index in range(1, count):
            fade = index / float(count)
            if self.track_mode:
                color = (int(80 + 40 * fade), int(150 + 70 * fade),
                         int(180 + 60 * fade))
            else:
                color = (int(42 + 210 * fade), int(56 + 60 * fade), int(70 + 20 * fade))
            pygame.draw.line(self.screen, color, points[index - 1], points[index],
                             line_width)

    def _draw_ai_cars(self, telemetries):
        """画 AI 车辆：独立彩色多边形，和玩家车明显区分。"""
        car_length = 4.5
        car_width = 1.9
        for index, telem in enumerate(telemetries):
            if telem is None:
                continue
            forward = (math.cos(telem.heading), math.sin(telem.heading))
            side = (-forward[1], forward[0])
            front = (telem.x + forward[0] * car_length * 0.5,
                     telem.y + forward[1] * car_length * 0.5)
            rear = (telem.x - forward[0] * car_length * 0.5,
                    telem.y - forward[1] * car_length * 0.5)
            corners = [
                self.camera.world_to_screen(front[0], front[1]),
                self.camera.world_to_screen(
                    rear[0] + side[0] * car_width * 0.5,
                    rear[1] + side[1] * car_width * 0.5),
                self.camera.world_to_screen(
                    rear[0] - side[0] * car_width * 0.5,
                    rear[1] - side[1] * car_width * 0.5),
            ]
            color = ai_rgb(index)
            pygame.draw.polygon(self.screen, color, corners)
            pygame.draw.polygon(self.screen, AI_OUTLINE, corners, 1)

    def _draw_car(self, sim):
        vehicle = sim.vehicle
        # 车身尺寸按米 → 像素缩放，保证任何显示比例下都是真实大小
        car_length_px = 2.0 * sim.params.half_length * self.camera.pixels_per_meter
        scale = car_length_px / float(self.sprite_height)
        if scale < 0.02:
            return
        camera_angle = getattr(self.camera, "angle", math.pi / 2.0)
        if camera_angle is None:
            camera_angle = math.pi / 2.0
        # 车贴图默认朝上；屏幕朝上 = 相机角度方向，所以转 heading - camera_angle
        angle = math.degrees(vehicle.heading - camera_angle)
        rotated = pygame.transform.rotozoom(self.sprite, angle, scale)
        sx, sy = self.camera.world_to_screen(vehicle.x, vehicle.y)
        if (sx < -rotated.get_width() or sx > self.width + rotated.get_width()
                or sy < -rotated.get_height() or sy > self.height + rotated.get_height()):
            return
        rect = rotated.get_rect(center=(int(round(sx)), int(round(sy))))
        self.screen.blit(rotated, rect)

    # ------------------------------------------------------------------ HUD
    def _draw_hud(self, sim, stats):
        ox, oy = PANEL_POS
        self.screen.blit(self.panel, PANEL_POS)
        telem = sim.telemetry
        params = sim.params

        # 大号速度
        speed_kmh = (telem.speed_abs if telem else 0.0) * 3.6
        big = self.font_big.render("%.0f" % speed_kmh, True, WHITE)
        self.screen.blit(big, (ox + 24, oy + 10))
        self.screen.blit(self.font_small.render("km/h", True, DIM),
                         (ox + 30 + big.get_width(), oy + 40))
        detail = "vx %5.1f  vy %5.1f m/s" % (
            telem.vx if telem else 0.0, telem.vy if telem else 0.0)
        self.screen.blit(self.font_small.render(detail, True, DIM), (ox + 24, oy + 72))
        zoom = self.zoom_text()
        view_word = "VIEW " + zoom if zoom else "VIEW"
        if self.track_mode:
            if self.track.kind == "circle":
                view = "%s %.1f px/m   PAD Ø%.0f m" % (
                    view_word, self.camera.pixels_per_meter,
                    self.track.outer_radius_m * 2.0)
            else:
                view = "%s %.1f px/m   TRACK %.0f m" % (
                    view_word, self.camera.pixels_per_meter,
                    self.track.lap_length_m)
        else:
            view = "%s %.2f px/m   WORLD %.1f×%.1f m" % (
                view_word, self.camera.pixels_per_meter,
                self.world_width, self.world_height)
        if stats.get("ai_count"):
            view += "   AI %d" % int(stats["ai_count"])
        self.screen.blit(self.font_small.render(view, True, DIM), (ox + 24, oy + 92))

        # 挡位 / 转速 / 转速表
        gear = telem.gear if telem else 1
        gear_text = "R" if gear < 0 else str(gear)
        self.screen.blit(self.font_mid.render("GEAR %s" % gear_text, True, WHITE),
                         (ox + 400, oy + 14))
        rpm = telem.rpm if telem else self.idle_rpm
        self.screen.blit(self.font.render("RPM %5.0f" % rpm, True, WHITE),
                         (ox + 400, oy + 46))
        self._tach_bar(ox + 400, oy + 74, 224, 12, rpm, params.redline_rpm, params.idle_rpm)
        if self.track_mode:
            cam_text = "VEL" if not self.camera.frozen else "VEL HOLD"
        else:
            cam_text = "FOLLOW" if self.camera.follow else "FIXED"
        self.screen.blit(self.font_small.render(
            "SIM %3.0fHz  FPS %3.0f  %s" % (
                stats.get("sim_hz", 0.0), stats.get("fps", 0.0), cam_text),
            True, DIM), (ox + 400, oy + 92))

        # 踏板 / 方向盘
        throttle = telem.throttle if telem else 0.0
        brake = telem.brake if telem else 0.0
        steer = telem.steer if telem else 0.0
        self._bar(ox + 24, oy + 120, "THR", throttle / 0.9, GREEN)
        self._bar(ox + 24, oy + 150, "BRK", brake / 0.8, RED)
        self._bar(ox + 24, oy + 180, "STR", steer, BLUE, centered=True)

        if telem is None:
            return

        # 实际加速度（g）
        self.screen.blit(self.font.render(
            "A_LONG %+6.2f g   A_LAT %+6.2f g" % (
                telem.a_long / self.gravity, telem.a_lat / self.gravity),
            True, WHITE), (ox + 24, oy + 212))

        # 附着利用率
        grip = _clamp(telem.grip_usage, 0.0, 1.2)
        if grip < 0.85:
            grip_color = GREEN
        elif grip < 0.99:
            grip_color = YELLOW
        else:
            grip_color = ORANGE
        self._bar(ox + 24, oy + 240, "GRIP", min(grip, 1.0), grip_color,
                  value_text="%3.0f%%" % (grip * 100.0))

        # 前轮转角 / 转弯半径 / 侧偏角
        steer_deg = telem.steer_deg
        direction = "L" if steer_deg > 0.2 else ("R" if steer_deg < -0.2 else "-")
        if telem.radius > 0.0:
            radius_text = "R %5.1f m" % telem.radius
        else:
            radius_text = "R   --"
        self.screen.blit(self.font.render(
            "STEER %+5.1f deg %s   %s   BETA %+5.1f deg" % (
                steer_deg, direction, radius_text, telem.beta_deg),
            True, WHITE), (ox + 24, oy + 266))

        # 打滑状态
        slip_text = "SLIP %4.2f" % telem.slip_amount
        flags = []
        if telem.wheelspin:
            flags.append("WHEELSPIN")
        if telem.lockup:
            flags.append("LOCKUP")
        if telem.sliding:
            flags.append("SLIDE")
        if telem.shifting:
            flags.append("SHIFTING")
        if flags:
            slip_color = RED if (telem.wheelspin or telem.lockup) else ORANGE
            slip_text += "   " + " ".join(flags)
        else:
            slip_color = DIM
            slip_text += "   GRIP OK"
        self.screen.blit(self.font.render(slip_text, True, slip_color), (ox + 24, oy + 302))

        self._draw_friction_circle(ox + 570, oy + 214, 52, telem,
                                   params.friction * self.gravity)

    def _tach_bar(self, x, y, width, height, rpm, redline, idle):
        pygame.draw.rect(self.screen, (34, 38, 46), (x, y, width, height))
        pygame.draw.rect(self.screen, (72, 80, 94), (x, y, width, height), 1)
        span = max(1.0, redline - idle)
        ratio = _clamp((rpm - idle) / span, 0.0, 1.0)
        color = GREEN if rpm < redline * 0.85 else (ORANGE if rpm < redline * 0.98 else RED)
        fill = int((width - 2) * ratio)
        if fill > 0:
            pygame.draw.rect(self.screen, color, (x + 1, y + 1, fill, height - 2))
        red_x = x + int((width - 2) * 0.85)
        pygame.draw.line(self.screen, RED, (red_x, y), (red_x, y + height))

    def _bar(self, x, y, label, ratio, color, centered=False, value_text=None):
        self.screen.blit(self.font.render(label, True, DIM), (x, y - 1))
        left = x + 70
        width = 240
        height = 14
        pygame.draw.rect(self.screen, (34, 38, 46), (left, y, width, height))
        pygame.draw.rect(self.screen, (72, 80, 94), (left, y, width, height), 1)
        ratio = _clamp(ratio, -1.0, 1.0)
        if centered:
            center = left + width // 2
            half = int((width // 2 - 1) * ratio)
            if half >= 0:
                pygame.draw.rect(self.screen, color, (center, y + 1, half, height - 2))
            else:
                pygame.draw.rect(self.screen, color,
                                 (center + half, y + 1, -half, height - 2))
            pygame.draw.line(self.screen, (120, 130, 148),
                             (center, y), (center, y + height))
        else:
            fill = int((width - 2) * ratio)
            if fill > 0:
                pygame.draw.rect(self.screen, color, (left + 1, y + 1, fill, height - 2))
        if value_text is not None:
            self.screen.blit(self.font.render(value_text, True, WHITE),
                             (left + width + 10, y - 2))

    def _draw_friction_circle(self, cx, cy, radius, telem, scale_limit):
        """摩擦圆示波器：横向/纵向加速度，方向已按 V3.7 翻转（前→后、左→右）。"""
        ring = (60, 66, 78)
        pygame.draw.circle(self.screen, (26, 30, 38), (cx, cy), radius)
        pygame.draw.circle(self.screen, ring, (cx, cy), radius, 1)
        pygame.draw.circle(self.screen, ring, (cx, cy), radius // 2, 1)
        pygame.draw.line(self.screen, ring, (cx - radius, cy), (cx + radius, cy))
        pygame.draw.line(self.screen, ring, (cx, cy - radius), (cx, cy + radius))
        if telem is None or scale_limit <= 0.0:
            return
        # V3.7：G 力球方向翻转——前变后、左变右
        nx = _clamp(telem.a_lat / scale_limit, -1.2, 1.2)
        ny = _clamp(-telem.a_long / scale_limit, -1.2, 1.2)
        dot_x = int(cx + nx * radius)
        dot_y = int(cy - ny * radius)
        pygame.draw.circle(self.screen, WHITE, (dot_x, dot_y), 5)
        pygame.draw.circle(self.screen, BLUE, (dot_x, dot_y), 5, 1)

    def _draw_help(self):
        pressed = pygame.key.get_pressed()
        x = 26
        y = self.height - self.help_bg.get_height() - 9
        self.screen.blit(self.help_bg, (16, y - 5))
        for index, (text, keys, kind) in enumerate(HELP_TOKENS):
            if kind == "key":
                color = PRESSED_COLOR if any(pressed[key] for key in keys) else WHITE
            else:
                color = DIM
            surface = self.font_small.render(text, True, color)
            self.screen.blit(surface, (x, y))
            x += self.help_token_widths[index]

    def _draw_paused(self):
        overlay = pygame.Surface((self.width, self.height), pygame.SRCALPHA)
        overlay.fill((0, 0, 0, 90))
        self.screen.blit(overlay, (0, 0))
        text = self.font_big.render("PAUSED", True, WHITE)
        self.screen.blit(text, (self.width // 2 - text.get_width() // 2,
                                self.height // 2 - text.get_height() // 2))
        hint = self.font_small.render("press P to resume", True, DIM)
        self.screen.blit(hint, (self.width // 2 - hint.get_width() // 2,
                                self.height // 2 + 40))
