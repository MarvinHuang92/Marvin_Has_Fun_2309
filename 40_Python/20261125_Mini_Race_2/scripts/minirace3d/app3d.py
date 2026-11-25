# -*- coding: utf-8 -*-
"""Mini Race 2 —— Panda3D 3D 显示原型。

物理层完全复用 scripts/minirace 的 Simulation / Track / LapTimer；
这里只负责 3D 场景、追车相机、输入和 HUD。不是正式渲染器，先验证视角和场景。
"""
import json
import math
import os
import sys
import time

from panda3d.core import (AmbientLight, DirectionalLight, Filename, Geom,
                          GeomNode, GeomTriangles, GeomVertexData,
                          GeomVertexFormat, GeomVertexWriter, KeyboardButton,
                          NodePath, Point3, TextNode, Vec3, Vec4,
                          loadPrcFileData)

from direct.showbase.ShowBase import ShowBase
from direct.task import Task

PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(PROJECT_DIR, "scripts"))

from minirace.audio import Audio  # noqa: E402
from minirace.config import load_config  # noqa: E402
from minirace.controls import Command  # noqa: E402
from minirace.laptiming import LapTimer, format_time  # noqa: E402
from minirace.sim import Simulation  # noqa: E402
from minirace3d.minimap import MiniMap  # noqa: E402
from minirace3d.scene import SceneBuilder  # noqa: E402


class App3D(ShowBase):
    def __init__(self, map_id=None, offscreen=False):
        self.offscreen = offscreen
        if offscreen:
            loadPrcFileData("", "window-type offscreen")
        loadPrcFileData("", "audio-library-name null")
        loadPrcFileData("", "win-size 1440 900")
        loadPrcFileData("", "framebuffer-srgb true")
        ShowBase.__init__(self)
        self.disableMouse()
        self.setBackgroundColor(0.52, 0.70, 0.92, 1.0)
        self.camLens.setFov(68)
        self.camLens.setNearFar(0.2, 4000.0)
        self.hud_font = self._load_hud_font()

        self.project_dir = PROJECT_DIR
        self.base_config = load_config(PROJECT_DIR)
        self.audio = Audio(self.base_config.get("audio", {}),
                           project_dir=self.project_dir)
        self.maps = list((self.base_config.get("maps", {}) or {}).get("list", []))
        if not self.maps:
            raise RuntimeError("cfg/sim.json 中没有 maps.list")
        self.map_index = self._initial_map_index(map_id)
        self.best_laps = {}
        self.paused = False
        self._accumulator = 0.0
        self._clock = self.taskMgr  # 只用于命名避免误用
        self.last_frame_time = time.time()
        self.steer_keys = {}
        self.cam_mode = 0  # 0=车尾追车，1=车头视角
        self.cam_current = None
        self.scene_root = None
        self.track_scene = None
        self.car = None
        self.minimap = None
        self._notice_until = 0.0
        self._build_lights()
        self._build_hud()
        self._bind_keys()
        self._load_map(self.map_index, announce=False)
        self.taskMgr.add(self._update_task, "mini-race-3d-update")
        self.accept("escape", self._quit)
        self.accept("f2", self._cycle_map)
        self.accept("f5", self._quick_reset)
        self.accept("home", self._home_reset)
        self.accept("r", self._toggle_reverse)
        self.accept("c", self._toggle_camera)
        self.accept("p", self._toggle_pause)
        self.accept("m", self._toggle_mute)

    # ------------------------------------------------------------------ 初始化
    def _initial_map_index(self, map_id):
        if map_id:
            for index, item in enumerate(self.maps):
                if item.get("id") == map_id:
                    return index
        session = os.path.join(PROJECT_DIR, "data", "last_map.json")
        try:
            with open(session, "r", encoding="utf-8") as handle:
                saved = json.load(handle).get("id")
            for index, item in enumerate(self.maps):
                if item.get("id") == saved:
                    return index
        except (IOError, OSError, ValueError):
            pass
        return 0

    def _load_hud_font(self):
        # 和 2D 一样用等宽字体，避免数字变化时宽度跳动
        windows = os.environ.get("WINDIR", r"C:\Windows")
        for path in (os.path.join(windows, "Fonts", "consola.ttf"),
                     os.path.join(windows, "Fonts", "Consolas.ttf")):
            if not os.path.isfile(path):
                continue
            path = os.path.realpath(path)  # 统一 Windows 路径大小写
            # Panda3D 1.10 的 loadFont 接受 Unix 风格虚拟路径（C:\ -> /c/）
            panda_path = path.replace("\\", "/")
            if len(panda_path) >= 2 and panda_path[1] == ":":
                panda_path = "/" + panda_path[0].lower() + panda_path[2:]
            try:
                return self.loader.loadFont(panda_path)
            except Exception:
                pass
        try:
            return self.loader.loadFont("cmtt12")  # Panda3D 自带等宽字体兜底
        except Exception:
            return None

    def _build_lights(self):
        ambient = AmbientLight("ambient")
        ambient.setColor(Vec4(0.58, 0.60, 0.66, 1.0))
        self.render.setLight(self.render.attachNewNode(ambient))
        sun = DirectionalLight("sun")
        sun.setColor(Vec4(1.0, 0.96, 0.86, 1.0))
        sun_node = self.render.attachNewNode(sun)
        sun_node.setHpr(35.0, -42.0, 0.0)
        self.render.setLight(sun_node)
        fill = DirectionalLight("fill")
        fill.setColor(Vec4(0.30, 0.38, 0.55, 1.0))
        fill_node = self.render.attachNewNode(fill)
        fill_node.setHpr(-145.0, -20.0, 0.0)
        self.render.setLight(fill_node)

    def _build_hud(self):
        self.hud_map = self._text("", (-0.98, 0.91), 0.042,
                                  (0.92, 0.94, 1.0, 1))
        self.hud_status = self._text("", (-0.98, 0.835), 0.038,
                                     (0.78, 0.82, 0.90, 1))
        self.hud_speed = self._text("", (-0.98, 0.69), 0.10,
                                    (1.0, 1.0, 1.0, 1))
        self.hud_gear = self._text("", (-0.98, 0.585), 0.045,
                                   (1.0, 0.86, 0.42, 1))
        self.hud_lap = self._text("", (0.80, 0.91), 0.043,
                                  (1.0, 1.0, 1.0, 1), align="right")
        self.hud_time = self._text("", (0.80, 0.835), 0.050,
                                   (0.92, 1.0, 0.82, 1), align="right")
        self.hud_best = self._text("", (0.80, 0.765), 0.038,
                                   (0.75, 0.85, 1.0, 1), align="right")
        self.corner_texts = []
        self.corner_start_x = 0.54
        self.corner_step = 0.070
        self.corner_y = 0.685
        for index in range(5):
            item = self._text("", (self.corner_start_x + self.corner_step * index,
                                   self.corner_y), 0.036,
                              (0.92, 0.94, 1.0, 1), align="center")
            self.corner_texts.append(item)
        self.corner_triangle = self._build_corner_triangle(
            self.corner_start_x + self.corner_step * 2, self.corner_y - 0.036)
        self.hud_notice = self._text("", (0.0, 0.26), 0.055,
                                     (1.0, 0.72, 0.25, 1), align="center")
        self.hud_help = self._text(
            "W/S throttle-brake   A/D steer   R gear   M mute   F2 map   F5 reset   "
            "HOME start   C camera   P pause   ESC quit",
            (0.0, -0.94), 0.026, (0.78, 0.82, 0.90, 1), align="center")

    def _build_corner_triangle(self, x, y):
        # 固定朝向的小三角，颜色由 update 控制
        vdata = GeomVertexData("corner_triangle", GeomVertexFormat.getV3(),
                               Geom.UHStatic)
        vdata.setNumRows(3)
        writer = GeomVertexWriter(vdata, "vertex")
        writer.addData3f(x, 0.0, y + 0.018)
        writer.addData3f(x - 0.009, 0.0, y)
        writer.addData3f(x + 0.009, 0.0, y)
        prim = GeomTriangles(Geom.UHStatic)
        prim.addVertices(0, 1, 2)
        prim.closePrimitive()
        geom = Geom(vdata)
        geom.addPrimitive(prim)
        node = GeomNode("corner_triangle")
        node.addGeom(geom)
        path = self.render2d.attachNewNode(node)
        path.setColor(Vec4(1.0, 0.58, 0.12, 1.0))
        path.setLightOff()
        return path

    def _text(self, text, pos, scale, color, align="left"):
        from direct.gui.OnscreenText import OnscreenText
        return OnscreenText(
            text=text, pos=pos, scale=scale, fg=color, bg=(0, 0, 0, 0.38),
            shadow=(0, 0, 0, 0.55), align=(TextNode.ARight if align == "right"
                                          else TextNode.ACenter if align == "center"
                                          else TextNode.ALeft),
            font=self.hud_font, parent=self.render2d, mayChange=True)

    def _bind_keys(self):
        # 持续按住的驾驶键在 update 里轮询
        pass

    # ------------------------------------------------------------------ 地图
    def _map_config(self, map_def):
        config = json.loads(json.dumps(self.base_config))
        track = config.setdefault("track", {})
        track["enabled"] = True
        track["file"] = map_def.get("file", "cfg/track.json")
        camera = track.setdefault("camera", {})
        camera["pixels_per_meter"] = 6.0
        config["active_map"] = {
            "id": map_def.get("id", ""),
            "name": map_def.get("name", ""),
            "display_name": map_def.get("display_name", ""),
            "number": map_def.get("number", ""),
        }
        return config

    def _load_map(self, index, announce=True):
        if self.minimap is not None:
            self.minimap.destroy()
            self.minimap = None
        if self.track_scene is not None:
            self.track_scene.root.removeNode()
        if self.scene_root is not None:
            self.scene_root.removeNode()
        self.map_index = int(index) % len(self.maps)
        self.current_map = self.maps[self.map_index]
        config = self._map_config(self.current_map)
        self.sim = Simulation(config, project_dir=PROJECT_DIR)
        self.sim.step(Command(), 0.0)
        self.lap_timer = LapTimer(self.sim.track)
        self.best_laps = getattr(self, "best_laps", {})
        if self.current_map.get("id") in self.best_laps:
            self.lap_timer.best = self.best_laps[self.current_map.get("id")]
        self.scene_root = self.render.attachNewNode("scene")
        self.track_scene = SceneBuilder(self.sim.track, self.scene_root)
        self.track_scene.build()
        self.car = self.track_scene.build_car()
        self.minimap = MiniMap(self, self.sim.track, self.current_map,
                               font=self.hud_font)
        self.cam_current = None
        self._accumulator = 0.0
        if announce:
            self._notice_until = time.time() + 2.0
        self._update_hud_static()
        self._place_car()
        self._update_camera(0.0, snap=True)
        self.setBackgroundColor(0.52, 0.70, 0.92, 1.0)

    def _cycle_map(self):
        self._load_map((self.map_index + 1) % len(self.maps))

    def _update_hud_static(self):
        info = self.current_map
        number = info.get("number", "")
        prefix = ("[%s] " % number) if number not in (None, "") else ""
        self.hud_map.setText("MINI RACE 2 / 3D PROTOTYPE   MAP %s%s" % (
            prefix, info.get("display_name", "")))
        kind = self.sim.track.kind if self.sim.track is not None else ""
        self.hud_status.setText("TRACK %s   length %.0f m   width %.1f m" % (
            kind.upper(), self.sim.track.lap_length_m
            if self.sim.track is not None else 0.0,
            self.sim.track.width_m if self.sim.track is not None else 0.0))

    # ------------------------------------------------------------------ 输入/复位
    def _key(self, code):
        if self.mouseWatcherNode is None:
            return False
        return bool(self.mouseWatcherNode.is_button_down(code))

    def _read_command(self):
        throttle = self._key(KeyboardButton.ascii_key("w")) or self._key(
            KeyboardButton.up())
        brake = self._key(KeyboardButton.ascii_key("s")) or self._key(
            KeyboardButton.down())
        left = self._key(KeyboardButton.ascii_key("a")) or self._key(
            KeyboardButton.left())
        right = self._key(KeyboardButton.ascii_key("d")) or self._key(
            KeyboardButton.right())
        return Command(throttle=throttle, brake=brake, left=left, right=right)

    def _quick_reset(self):
        nearest = self.sim.track.nearest(self.sim.vehicle.x, self.sim.vehicle.y)
        if nearest is not None:
            _distance, cx, cy, tx, ty, _index = nearest
            self.sim.vehicle.reset(cx, cy, math.atan2(ty, tx))
            self.sim.trail.clear()
            self.sim.telemetry = None
        else:
            self.sim.reset()
        self._place_car()
        self._update_camera(0.0, snap=True)

    def _home_reset(self):
        self.sim.reset()
        self.lap_timer.home_reset(self.sim.time)
        self._place_car()
        self._update_camera(0.0, snap=True)

    def _toggle_reverse(self):
        self.sim.toggle_reverse()

    def _toggle_camera(self):
        self.cam_mode = 1 - self.cam_mode
        self._notice_until = time.time() + 1.5
        self.hud_notice.setText("CAMERA: %s" % (
            "FRONT BUMPER" if self.cam_mode else "REAR CHASE"))

    def _toggle_pause(self):
        self.paused = not self.paused
        self.hud_notice.setText("PAUSED" if self.paused else "")
        if not self.paused:
            self._notice_until = 0.0

    def _toggle_mute(self):
        muted = self.audio.toggle_mute()
        self.hud_notice.setText("MUTED" if muted else "SOUND ON")
        self._notice_until = time.time() + 1.2

    # ------------------------------------------------------------------ 场景/相机
    def _place_car(self):
        if self.car is None:
            return
        vehicle = self.sim.vehicle
        self.car.setPos(vehicle.x, vehicle.y, 0.0)
        fx = math.cos(vehicle.heading)
        fy = math.sin(vehicle.heading)
        self.car.lookAt(Point3(vehicle.x + fx, vehicle.y + fy, 0.0), Vec3(0, 0, 1))

    def _update_camera(self, dt, snap=False):
        vehicle = self.sim.vehicle
        fx = math.cos(vehicle.heading)
        fy = math.sin(vehicle.heading)
        if self.cam_mode == 0:
            desired = Vec3(vehicle.x - fx * 9.5, vehicle.y - fy * 9.5, 3.8)
            look = Vec3(vehicle.x + fx * 12.0, vehicle.y + fy * 12.0, 0.9)
        else:
            desired = Vec3(vehicle.x + fx * 3.6, vehicle.y + fy * 3.6, 1.85)
            look = Vec3(vehicle.x + fx * 22.0, vehicle.y + fy * 22.0, 0.15)
        if snap or self.cam_current is None:
            self.cam_current = desired
        else:
            factor = min(1.0, max(0.0, dt * 7.0))
            self.cam_current = self.cam_current + (desired - self.cam_current) * factor
        self.camera.setPos(self.cam_current)
        self.camera.lookAt(Point3(look.x, look.y, look.z), Vec3(0, 0, 1))

    # ------------------------------------------------------------------ 主循环
    def _update_task(self, task):
        now = time.time()
        dt = now - self.last_frame_time
        self.last_frame_time = now
        dt = min(max(dt, 0.0), 0.05)
        if not self.paused:
            command = self._read_command()
            self._accumulator += dt
            steps = 0
            while (self._accumulator >= self.sim.step_dt
                   and steps < self.sim.max_substeps):
                self.sim.step(command)
                if self.lap_timer.enabled:
                    self.lap_timer.update(self.sim.time, self.sim.vehicle.x,
                                          self.sim.vehicle.y)
                self._accumulator -= self.sim.step_dt
                steps += 1
            if steps >= self.sim.max_substeps:
                self._accumulator = 0.0
        self._place_car()
        self._update_camera(dt)
        if self.minimap is not None:
            self.minimap.update(self.sim.vehicle)
        self.audio.update(self.sim.telemetry, paused=self.paused)
        self._update_hud()
        return Task.cont

    def _update_hud(self):
        telem = self.sim.telemetry
        if telem is not None:
            self.hud_speed.setText("%.0f km/h" % (telem.speed_abs * 3.6))
            gear = "R" if telem.gear < 0 else str(telem.gear)
            self.hud_gear.setText("GEAR %s    RPM %.0f" % (gear, telem.rpm))
        if self.lap_timer.enabled:
            self.hud_lap.setText("LAP %d" % self.lap_timer.lap)
            self.hud_time.setText(format_time(self.lap_timer.current_time(
                self.sim.time)))
            self.hud_best.setText("BEST " + format_time(self.lap_timer.best))
        else:
            self.hud_lap.setText("")
            self.hud_time.setText(format_time(self.sim.time))
            self.hud_best.setText("")
        window = None
        if self.sim.track is not None:
            window = self.sim.track.element_window_at(
                self.sim.vehicle.x, self.sim.vehicle.y)
        if window is not None:
            labels = window[0]
            for index, item in enumerate(self.corner_texts):
                label = labels[index]
                item.setText(label)
                if index == 2:
                    item.setFg(Vec4(1.0, 0.58, 0.12, 1.0))
                elif label == "-":
                    item.setFg(Vec4(0.62, 0.68, 0.80, 1.0))
                else:
                    item.setFg(Vec4(0.94, 0.96, 1.0, 1.0))
            self.corner_triangle.show()
        else:
            for item in self.corner_texts:
                item.setText("")
            self.corner_triangle.hide()
        if time.time() < self._notice_until:
            if not self.hud_notice.getText():
                self.hud_notice.setText("MAP %s" % self.current_map.get(
                    "display_name", ""))
        elif not self.paused:
            self.hud_notice.setText("")

    # ------------------------------------------------------------------ 退出/截图
    def destroy(self):
        try:
            if getattr(self, "audio", None) is not None:
                self.audio.close()
        except Exception:
            pass
        if getattr(self, "minimap", None) is not None:
            self.minimap.destroy()
            self.minimap = None
        super(App3D, self).destroy()

    def _quit(self):
        self.userExit()

    def screenshot(self, path, frames=8):
        for _ in range(frames):
            self.taskMgr.step()
        self.graphicsEngine.renderFrame()
        self.win.saveScreenshot(Filename.fromOsSpecific(path))
        self.graphicsEngine.renderFrame()
