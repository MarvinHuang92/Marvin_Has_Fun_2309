# -*- coding: utf-8 -*-
"""pygame 主循环：事件、固定步长推进、渲染、音频、遥测录制。

时间结构
--------
- 渲染：``clock.tick(window.fps)`` 限制帧率。
- 物理：固定 ``1 / vehicle.step_hz`` 秒步长（默认 240 Hz），用累加器补帧。
  渲染帧再慢，物理步长也不变，所以行为与帧率基本无关。
- 一帧最多补 ``vehicle.max_substeps`` 步，多余时间丢弃，避免"追帧"越追越卡。
- 音频按渲染帧更新（转速/油门/滑移量），断油换挡/打滑时声音自然跟着变化。
"""
import copy
import json
import logging
import math
import os
import time

import pygame
from pygame.locals import (
    KEYDOWN, K_DOWN, K_EQUALS, K_ESCAPE, K_F2, K_F5, K_F9, K_HOME, K_KP_MINUS,
    K_KP_PLUS, K_LEFT, K_MINUS, K_m, K_RIGHT, K_UP, K_a, K_d, K_p, K_r, K_s,
    K_w, QUIT,
)

from minirace.audio import Audio
from minirace.controls import Command
from minirace.diagnostics import Diagnostics
from minirace.laptiming import LapTimer
from minirace.render import Renderer
from minirace.sim import Simulation
from minirace.storage import TelemetryRecorder
from minirace.warnings import WrongWayMonitor

LOG = logging.getLogger(__name__)

MAX_FRAME_SECONDS = 0.25


class App(object):
    def __init__(self, project_dir, config, record=False, capture=None, diagnose=False):
        self.project_dir = project_dir
        self.base_config = config
        self.config = config
        self.capture = capture
        self.capture_delay = 1.0 if capture else None

        # 只初始化用得到的子系统：pygame.init() 会顺带初始化手柄，
        # 本机实测手柄枚举要 10 秒，启动会被无谓拖慢。这里不需要手柄。
        pygame.display.init()
        pygame.font.init()
        window = config.get("window", {}) or {}
        self.width = int(window.get("width", 1440))
        self.height = int(window.get("height", 900))
        self.fps = int(window.get("fps", 60) or 60)
        self.screen = pygame.display.set_mode((self.width, self.height))
        pygame.display.set_caption(str(window.get("caption", "Mini Race 2")))

        self.clock = pygame.time.Clock()
        # 地图列表 + 上次退出的地图（V3.1）；默认加载上次地图的起点
        self.maps = self._load_map_list()
        self.map_info = self._load_map_info()
        maps_cfg = config.get("maps", {}) or {}
        self.session_path = maps_cfg.get(
            "session_file", os.path.join("data", "last_map.json"))
        self.best_laps = {}
        self.map_index = self._read_last_map_index()
        self.current_map = self.maps[self.map_index]
        self.config = self._config_for_map(self.map_index)
        self.sim = Simulation(self.config, project_dir=project_dir)
        # 先算一步 dt=0 的物理，保证第一帧就有观测量可画
        self.sim.step(Command(), 0.0)
        self.renderer = Renderer(self.screen, self.config, project_dir)
        self.audio = Audio(config.get("audio", {}), project_dir=self.project_dir)
        self.diagnostics = Diagnostics(project_dir, self.config)
        if diagnose:
            self.diagnostics.start()

        self.step_dt = self.sim.step_dt
        self.accumulator = 0.0
        self.paused = False
        self.running = True
        self.start_monotonic = time.monotonic()
        self.map_notice_until = 0.0
        self.lap_timer = LapTimer(self.sim.track)
        if self.current_map.get("id") in self.best_laps:
            self.lap_timer.best = self.best_laps[self.current_map.get("id")]
        self.wrong_way = WrongWayMonitor()

        self.recorder = TelemetryRecorder(
            os.path.join(str(project_dir), "data")) if record else None
        if self.recorder is not None and self.recorder.active:
            LOG.info("遥测录制已开启：%s", self.recorder.path)

        params = self.sim.params
        render_cfg = self.config.get("render", {}) or {}
        pixels_per_meter = float(render_cfg.get("pixels_per_meter", 11.111111) or 11.111111)
        if self.sim.track is not None:
            track_cfg = self.config.get("track", {}) or {}
            camera_cfg = track_cfg.get("camera", {}) or {}
            pixels_per_meter = float(camera_cfg.get("pixels_per_meter", 6.0) or 6.0)
        follow = bool(render_cfg.get("follow_car", True))
        LOG.info("模拟器启动：窗口 %dx%d @%dHz，物理 %.0f Hz；"
                 "质量 %.0f kg，轴距 %.2f m，前轴荷 %.0f%%，转动惯量 %.0f kg·m²",
                 self.width, self.height, self.fps, params.step_hz,
                 params.mass, params.wheelbase, params.front_weight_fraction * 100.0,
                 params.inertia)
        view_width = self.width / pixels_per_meter
        view_height = self.height / pixels_per_meter
        world_fits = (view_width >= self.sim.width + 1e-9
                      and view_height >= self.sim.height + 1e-9)
        camera_mode = "跟随车辆" if (follow and not world_fits) else "固定"
        LOG.info("地图：%s（%s）", self.current_map.get("name"),
                 self.current_map.get("display_name"))
        if self.sim.track is not None:
            LOG.info("赛道：%s，宽 %.1f m，圈长 %.0f m，起点 (%.1f, %.1f) 朝向 %.1f°",
                     self.sim.track.name, self.sim.track.width_m,
                     self.sim.track.lap_length_m, self.sim.spawn[0],
                     self.sim.spawn[1], math.degrees(self.sim.spawn[2]))
            camera_mode = "赛道跟车（速度朝上）"
        LOG.info("世界 %.1f × %.1f m；显示缩放 %.2f px/m（视野 %.1f × %.1f m），相机%s",
                 self.sim.width, self.sim.height, pixels_per_meter,
                 view_width, view_height, camera_mode)
        peak_slip = math.degrees(
            math.tan(math.pi / (2.0 * params.tire_shape))
            / (params.cornering_stiffness / (params.friction * params.tire_shape)))
        LOG.info("轮胎：friction=%.2f，侧偏刚度 %.0f/Fz，峰值侧偏约 %.1f deg；"
                 "传动：%dAT，主减速比 %.2f，红线 %.0f rpm",
                 params.friction, params.cornering_stiffness, peak_slip,
                 params.num_gears, params.final_drive, params.redline_rpm)

    # ------------------------------------------------------------------ 地图
    def _load_map_info(self):
        """读取每个地图的几何元信息：全长 / 是否圆环（圆形场地不显示）。"""
        info = {}
        for map_def in self.maps:
            map_id = map_def.get("id", "")
            item = {"length_m": None, "kind": None}
            try:
                path = map_def.get("file", "")
                if path and not os.path.isabs(path):
                    path = os.path.join(str(self.project_dir), path)
                with open(path, "r", encoding="utf-8") as handle:
                    data = json.load(handle)
                item["kind"] = data.get("kind", "circuit")
                if item["kind"] != "circle":
                    item["length_m"] = float(
                        (data.get("reference", {}) or {}).get("lap_length_m") or 0.0)
            except (IOError, OSError, ValueError, TypeError):
                pass
            info[map_id] = item
        return info
    def _load_map_list(self):
        maps = self.base_config.get("maps", {}) or {}
        items = list(maps.get("list") or [])
        if not items:
            track_cfg = self.base_config.get("track", {}) or {}
            items = [{
                "id": "default",
                "name": "默认赛道",
                "display_name": "TRACK",
                "file": track_cfg.get("file", "cfg/track.json"),
            }]
        return items

    def _config_for_map(self, index):
        map_def = self.maps[index]
        config = copy.deepcopy(self.base_config)
        track_cfg = config.setdefault("track", {})
        track_cfg["enabled"] = True
        track_cfg["file"] = map_def.get("file", track_cfg.get("file", "cfg/track.json"))
        camera_cfg = track_cfg.setdefault("camera", {})
        if map_def.get("pixels_per_meter") is not None:
            camera_cfg["pixels_per_meter"] = float(map_def["pixels_per_meter"])
        config["active_map"] = {
            "id": map_def.get("id", ""),
            "name": map_def.get("name", ""),
            "display_name": map_def.get("display_name", ""),
            "number": map_def.get("number", ""),
        }
        return config

    def _session_path(self):
        return (self.session_path if os.path.isabs(self.session_path)
                else os.path.join(str(self.project_dir), self.session_path))

    def _read_last_map_index(self):
        default_id = (self.base_config.get("maps", {}) or {}).get("default", "")
        try:
            with open(self._session_path(), "r", encoding="utf-8") as handle:
                saved = json.load(handle)
            self.best_laps = {str(key): float(value)
                              for key, value in (saved.get("best_laps") or {}).items()
                              if value is not None}
            saved_id = str(saved.get("id", ""))
            for index, map_def in enumerate(self.maps):
                if map_def.get("id") == saved_id:
                    return index
        except (IOError, OSError, ValueError, AttributeError, TypeError):
            self.best_laps = {}
        for index, map_def in enumerate(self.maps):
            if map_def.get("id") == default_id:
                return index
        return 0

    def _write_last_map(self):
        path = self._session_path()
        try:
            folder = os.path.dirname(os.path.abspath(path))
            if folder and not os.path.isdir(folder):
                os.makedirs(folder)
            map_id = self.current_map.get("id", "")
            if hasattr(self, "lap_timer") and self.lap_timer.best is not None:
                self.best_laps[map_id] = self.lap_timer.best
            with open(path, "w", encoding="utf-8") as handle:
                json.dump({"id": map_id,
                           "name": self.current_map.get("name", ""),
                           "best_laps": self.best_laps},
                          handle, ensure_ascii=False, indent=1)
        except (IOError, OSError) as exc:
            LOG.warning("保存上次地图失败：%s", exc)

    def _load_map(self, index, announce=True):
        if hasattr(self, "lap_timer") and self.lap_timer.best is not None:
            self.best_laps[self.current_map.get("id", "")] = self.lap_timer.best
        self.map_index = index % len(self.maps)
        self.current_map = self.maps[self.map_index]
        self.config = self._config_for_map(self.map_index)
        self.sim = Simulation(self.config, project_dir=self.project_dir)
        self.sim.step(Command(), 0.0)
        zoom_level = getattr(self.renderer, "zoom_level", 0)
        self.renderer = Renderer(self.screen, self.config, self.project_dir)
        # F2 切图只重建 Renderer：保留本次窗口内的显示倍率，关窗后自然回到默认
        self.renderer.set_zoom_level(zoom_level)
        self.step_dt = self.sim.step_dt
        self.accumulator = 0.0
        self.lap_timer = LapTimer(self.sim.track)
        if self.current_map.get("id") in self.best_laps:
            self.lap_timer.best = self.best_laps[self.current_map.get("id")]
        self.wrong_way = WrongWayMonitor()
        if self.diagnostics.active:
            summary = self.diagnostics.stop()
            self.diagnostics.start()
            LOG.info("切换地图时重开诊断模式（上一段摘要：%s）", summary)
        if announce:
            self.map_notice_until = time.monotonic() + 2.5
        self._write_last_map()
        LOG.info("切换地图：%s（%s，从起点开始）",
                 self.current_map.get("name"), self.current_map.get("file"))

    def _cycle_map(self):
        if len(self.maps) <= 1:
            return
        self._load_map((self.map_index + 1) % len(self.maps))

    def _quick_reset(self):
        """F5：放到离车最近的当前赛道中心线上；圆形试车场特殊回到起点。"""
        sim = self.sim
        track = sim.track
        if track is None:
            sim.reset()
            self.renderer.reset_camera()
            self.wrong_way.reset()
            LOG.info("F5 复位：旧版矩形场地 -> 场地中心")
            return
        if track.kind == "circle" and track.reset_to_start:
            sim.vehicle.reset(sim.spawn[0], sim.spawn[1], sim.spawn[2])
            sim.trail.clear()
            sim.telemetry = None
            self.renderer.reset_camera()
            self.wrong_way.reset()
            self.accumulator = 0.0
            LOG.info("F5 复位：圆形试车场 -> 起点（不重置计时）")
            return
        nearest = track.nearest(sim.vehicle.x, sim.vehicle.y)
        if nearest is None:
            sim.reset()
        else:
            _distance, cx, cy, tx, ty, _index = nearest
            heading = math.atan2(ty, tx)
            sim.vehicle.reset(cx, cy, heading)
            sim.trail.clear()
            sim.telemetry = None
        self.renderer.reset_camera()
        self.accumulator = 0.0
        LOG.info("F5 复位：最近中心线点 (%.1f, %.1f)，朝向 %.1f°，速度清零",
                 sim.vehicle.x, sim.vehicle.y, math.degrees(sim.vehicle.heading))

    # ------------------------------------------------------------------ 对外
    def run(self, smoke=False):
        smoke_seconds = 1.5 if smoke else None
        while self.running:
            frame_seconds = self.clock.tick(self.fps) / 1000.0
            elapsed = time.monotonic() - self.start_monotonic

            self._handle_events()
            command = self._read_command()
            if not self.paused:
                self._advance(command, frame_seconds)

            stats = {
                "fps": self.clock.get_fps(),
                "sim_hz": self.sim.params.step_hz,
                "paused": self.paused,
                "diag": self.diagnostics.active,
                "diag_events": len(self.diagnostics.events),
                "frame_dt": frame_seconds,
                "map_name": self.current_map.get("name", ""),
                "map_display_name": self.current_map.get("display_name", ""),
                "map_number": self.current_map.get("number", ""),
                "map_kind": (self.map_info.get(self.current_map.get("id"), {}) or {}).get("kind"),
                "map_length_m": (self.map_info.get(self.current_map.get("id"), {}) or {}).get("length_m"),
                "map_best_lap": self.lap_timer.best,
                "map_notice": time.monotonic() < self.map_notice_until,
                "lap_enabled": bool(self.lap_timer.enabled),
                "lap": self.lap_timer.lap if self.lap_timer.enabled else 0,
                "lap_time": (self.lap_timer.current_time(self.sim.time)
                             if self.lap_timer.enabled else self.sim.time),
                "best_lap": self.lap_timer.best,
                "wrong_way_active": self.wrong_way.active,
                "wrong_way_visible": self.wrong_way.visible,
            }
            if self.sim.track is not None and self.sim.track.elements:
                window = self.sim.track.element_window_at(
                    self.sim.vehicle.x, self.sim.vehicle.y)
                if window is not None:
                    labels, types, center = window
                    stats["corner_labels"] = labels
                    stats["corner_types"] = types
                    stats["corner_center"] = center
            self.renderer.draw(self.sim, stats)
            self.audio.update(self.sim.telemetry, paused=self.paused)
            pygame.display.flip()

            if smoke_seconds is not None and elapsed >= smoke_seconds:
                self.running = False
            if self.capture is not None and elapsed >= self.capture_delay:
                self._save_capture()
                self.running = False
        return 0

    def close(self):
        self._write_last_map()
        if self.recorder is not None:
            self.recorder.close()
        if self.diagnostics.active:
            summary_path = self.diagnostics.stop()
            LOG.info("退出时结束诊断模式，摘要：%s", summary_path)
        self.audio.close()
        average_speed = (self.sim.distance / self.sim.time
                         if self.sim.time > 0 else 0.0)
        LOG.info("退出：模拟时间 %.2f s，里程 %.0f m，平均速度 %.1f m/s (%.0f km/h)，"
                 "平均帧率 %.1f FPS",
                 self.sim.time, self.sim.distance, average_speed, average_speed * 3.6,
                 self.clock.get_fps())
        pygame.quit()

    # ------------------------------------------------------------------ 内部
    def _handle_events(self):
        for event in pygame.event.get():
            if event.type == QUIT:
                self.running = False
            elif event.type == KEYDOWN:
                if event.key == K_ESCAPE:
                    self.running = False
                elif event.key == K_r:
                    if self.sim.toggle_reverse():
                        LOG.info("换挡：%s（模拟时间 %.2f s）",
                                 "R" if self.sim.vehicle.gear < 0 else "D",
                                 self.sim.time)
                    else:
                        LOG.debug("速度过高，拒绝换挡：%.1f m/s", self.sim.vehicle.vx)
                elif event.key == K_p:
                    self.paused = not self.paused
                    LOG.info("暂停" if self.paused else "继续")
                elif event.key == K_m:
                    muted = self.audio.toggle_mute()
                    LOG.info("静音" if muted else "取消静音")
                elif event.key in (K_MINUS, K_KP_MINUS):
                    level = self.renderer.adjust_zoom(-1)
                    LOG.info("显示倍率：%s %.2fx（%d/3）",
                             self.renderer.zoom_text() or "默认",
                             self.renderer.pixels_per_meter
                             / max(self.renderer.base_pixels_per_meter, 1e-9),
                             abs(level))
                elif event.key in (K_EQUALS, K_KP_PLUS):
                    level = self.renderer.adjust_zoom(1)
                    LOG.info("显示倍率：%s %.2fx（%d/3）",
                             self.renderer.zoom_text() or "默认",
                             self.renderer.pixels_per_meter
                             / max(self.renderer.base_pixels_per_meter, 1e-9),
                             abs(level))
                elif event.key == K_F5:
                    self._quick_reset()
                elif event.key == K_F2:
                    self._cycle_map()
                elif event.key == K_F9:
                    active, path = self.diagnostics.toggle()
                    if active:
                        LOG.info("诊断模式：开（F9 关闭），CSV：%s", path)
                    else:
                        LOG.info("诊断模式：关，摘要：%s", path)
                elif event.key == K_HOME:
                    self.sim.reset()
                    self.accumulator = 0.0
                    self.lap_timer.home_reset(self.sim.time)
                    self.renderer.reset_camera()
                    self.wrong_way.reset()
                    LOG.info("复位车辆到起点")

    @staticmethod
    def _read_command():
        keys = pygame.key.get_pressed()
        return Command(
            throttle=keys[K_UP] or keys[K_w],
            brake=keys[K_DOWN] or keys[K_s],
            left=keys[K_LEFT] or keys[K_a],
            right=keys[K_RIGHT] or keys[K_d],
        )

    def _update_wrong_way(self):
        """每个物理步更新"逆行"判定，并在闪烁进入显示相位时响一声。"""
        track = self.sim.track
        if track is None or track.kind != "circuit":
            self.wrong_way.reset()
            return
        error = track.direction_error(self.sim.vehicle.x, self.sim.vehicle.y,
                                      self.sim.vehicle.heading)
        _active, _visible, beep = self.wrong_way.update(error, self.step_dt)
        if beep:
            self.audio.warning_beep()

    def _advance(self, command, frame_seconds):
        if frame_seconds > MAX_FRAME_SECONDS:
            frame_seconds = MAX_FRAME_SECONDS
        self.accumulator += frame_seconds
        steps = 0
        while (self.accumulator >= self.step_dt
               and steps < self.sim.max_substeps):
            self.sim.step(command)
            if self.lap_timer.enabled:
                self.lap_timer.update(self.sim.time, self.sim.vehicle.x,
                                      self.sim.vehicle.y)
            self._update_wrong_way()
            self.diagnostics.step(self.sim)
            if self.recorder is not None:
                self.recorder.write(self.sim)
            self.accumulator -= self.step_dt
            steps += 1
        if steps >= self.sim.max_substeps:
            # 追不上就丢掉积压，保持实时手感
            self.accumulator = 0.0

    def _save_capture(self):
        target = self.capture
        folder = os.path.dirname(os.path.abspath(target))
        try:
            if folder and not os.path.isdir(folder):
                os.makedirs(folder)
            pygame.image.save(self.screen, target)
            LOG.info("截图已保存：%s", target)
        except (OSError, pygame.error) as exc:
            LOG.warning("截图保存失败：%s", exc)
