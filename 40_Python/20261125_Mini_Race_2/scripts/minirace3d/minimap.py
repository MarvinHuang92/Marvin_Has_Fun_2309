# -*- coding: utf-8 -*-
"""Panda3D 右下角缩略图（不旋转，和 2D 版信息一致）。"""
import math

from direct.gui.DirectGui import DirectFrame
from direct.gui.OnscreenText import OnscreenText
from panda3d.core import (Geom, GeomNode, GeomTriangles, GeomVertexData,
                          GeomVertexFormat, GeomVertexWriter, LineSegs,
                          NodePath, TextNode, Vec3, Vec4)

GREEN = (0.18, 0.95, 0.42, 1.0)
WHITE = (0.92, 0.94, 0.98, 1.0)
GREY = (0.70, 0.73, 0.80, 1.0)
RED = (0.95, 0.12, 0.12, 1.0)
PANEL = (0.045, 0.055, 0.075, 0.86)


class MiniMap(object):
    WIDTH = 360
    HEIGHT = 255
    MARGIN = 21
    BOTTOM_MARGIN = 60
    TOP = 33

    def __init__(self, base, track, map_info, font=None):
        self.base = base
        self.track = track
        self.map_info = map_info or {}
        self.font = font
        self.screen_width, self.screen_height = base.getSize()
        self.aspect_width = 2.0 * (self.screen_width / float(self.screen_height))
        self.root = base.a2dBottomRight
        self._nodes = []
        self._build_panel()
        self._build_track()
        self._build_start()
        self._build_car()
        self._build_title()

    # ------------------------------------------------------------------ 坐标
    def _pixel_to_ndc(self, px, py):
        # a2dBottomRight：本地点 = 右下角为 (0,0)，x 向左为负，y 向上为正
        return (-(self.screen_width - px) * self.aspect_width / float(self.screen_width),
                py * 2.0 / float(self.screen_height))

    def _bbox(self):
        track = self.track
        if track.kind == "circle":
            center = track.center
            radius = track.outer_radius_m
            return (center[0] - radius, center[1] - radius,
                    center[0] + radius, center[1] + radius)
        xs = [point[0] for point in track.points]
        ys = [point[1] for point in track.points]
        pad = track.width_m
        return min(xs) - pad, min(ys) - pad, max(xs) + pad, max(ys) + pad

    def _layout(self):
        width, height = self.screen_width, self.screen_height
        x0 = width - self.WIDTH - self.MARGIN
        y0 = self.BOTTOM_MARGIN
        x1, y1 = x0 + self.WIDTH, y0 + self.HEIGHT
        min_x, min_y, max_x, max_y = self._bbox()
        span_x = max(1.0, max_x - min_x)
        span_y = max(1.0, max_y - min_y)
        pad = 15
        scale = min((self.WIDTH - pad * 2) / span_x,
                    (self.HEIGHT - self.TOP - pad * 2) / span_y)
        offset_x = x0 + pad + (self.WIDTH - pad * 2 - span_x * scale) * 0.5
        offset_y = y0 + self.TOP + pad + (
            self.HEIGHT - self.TOP - pad * 2 - span_y * scale) * 0.5
        self._x0, self._y0, self._x1, self._y1 = x0, y0, x1, y1
        self._min_x, self._min_y = min_x, min_y
        self._max_y = max_y
        self._scale = scale
        self._offset_x, self._offset_y = offset_x, offset_y

    def _to_px(self, wx, wy):
        # 3D 的 render2d y 向上；这里用 (wy - min_y) 保持世界北向朝上
        return (self._offset_x + (wx - self._min_x) * self._scale,
                self._offset_y + (wy - self._min_y) * self._scale)

    def _to_ndc(self, wx, wy):
        return self._pixel_to_ndc(*self._to_px(wx, wy))

    # ------------------------------------------------------------------ 面板
    def _build_panel(self):
        self._layout()
        left, bottom = self._pixel_to_ndc(self._x0, self._y0)
        right, top = self._pixel_to_ndc(self._x1, self._y1)
        # 用 2D Geom 面片画面板，避免 DirectFrame 在 a2d 节点下的绘制顺序问题
        vdata = GeomVertexData("minimap_panel", GeomVertexFormat.getV3(),
                               Geom.UHStatic)
        vdata.setNumRows(4)
        writer = GeomVertexWriter(vdata, "vertex")
        for x, y in ((left, bottom), (right, bottom),
                     (right, top), (left, top)):
            writer.addData3f(x, 0.0, y)
        prim = GeomTriangles(Geom.UHStatic)
        prim.addVertices(0, 1, 2)
        prim.addVertices(0, 2, 3)
        prim.closePrimitive()
        geom = Geom(vdata)
        geom.addPrimitive(prim)
        node = GeomNode("minimap_panel")
        node.addGeom(geom)
        panel = self.root.attachNewNode(node)
        panel.setColor(Vec4(0.018, 0.022, 0.032, 0.94))
        panel.setLightOff()
        panel.setBin('fixed', -10)
        panel.setDepthTest(False)
        panel.setDepthWrite(False)
        self._nodes.append(panel)
        # 面板边框（和 2D 缩略图一致）
        border = LineSegs("minimap_border")
        border.setColor(Vec4(0.45, 0.48, 0.55, 1.0))
        border.setThickness(1)
        border.moveTo(left, 0, bottom)
        border.drawTo(right, 0, bottom)
        border.drawTo(right, 0, top)
        border.drawTo(left, 0, top)
        border.drawTo(left, 0, bottom)
        border_path = self.root.attachNewNode(border.create())
        border_path.setBin("fixed", -5)
        self._nodes.append(border_path)
    def _build_title(self):
        left, bottom = self._pixel_to_ndc(self._x0, self._y0)
        right, top = self._pixel_to_ndc(self._x1, self._y1)
        number = self.map_info.get("number", "")
        prefix = ("[%s] " % number) if number not in (None, "") else ""
        title = "MAP %s%s" % (prefix, self.map_info.get("display_name", ""))
        text = OnscreenText(
            text=title, parent=self.root, mayChange=True,
            pos=(left + 0.012, top - 0.055), scale=0.020,
            fg=WHITE, shadow=(0, 0, 0, 0.8), align=TextNode.ALeft,
            font=self.font, sort=30,
        )
        self._nodes.append(text)
        self._title = text

    def _line_node(self, color, thickness=2):
        segs = LineSegs("minimap_lines")
        segs.setColor(Vec4(*color))
        segs.setThickness(thickness)
        node = segs.create()
        path = self.root.attachNewNode(node)
        self._nodes.append(path)
        return path

    # ------------------------------------------------------------------ 赛道
    def _build_track(self):
        track = self.track
        if track.kind == "circle":
            path = self._line_node(GREY, 2)
            center = track.center
            radius = track.outer_radius_m
            segments = 96
            points = []
            for index in range(segments + 1):
                angle = 2.0 * math.pi * index / segments
                points.append(self._to_ndc(
                    center[0] + radius * math.cos(angle),
                    center[1] + radius * math.sin(angle)))
            # LineSegs 只能一条线段一个 Node；用另一个节点画虚线参考圆
            path.removeNode()
            path = self._polyline(points, GREY, 4)
            guide = track.guide_radius_m
            for start in range(0, segments, 4):
                points = []
                for step in (0, 1, 2):
                    angle = 2.0 * math.pi * (start + step) / segments
                    points.append(self._to_ndc(
                        center[0] + guide * math.cos(angle),
                        center[1] + guide * math.sin(angle)))
                self._polyline(points, (0.82, 0.84, 0.90, 1.0), 1)
        else:
            points = [self._to_ndc(point[0], point[1])
                      for point in track.points]
            points.append(points[0])
            self._polyline(points, GREY, 7)

    def _polyline(self, points, color, thickness):
        segs = LineSegs("minimap_poly")
        segs.setColor(Vec4(*color))
        segs.setThickness(thickness)
        first = True
        for point in points:
            if first:
                segs.moveTo(point[0], 0.0, point[1])
                first = False
            else:
                segs.drawTo(point[0], 0.0, point[1])
        node = segs.create()
        path = self.root.attachNewNode(node)
        self._nodes.append(path)
        return path

    def _filled_circle(self, center_world, radius_px, color, sort=18):
        center_px = self._to_px(center_world[0], center_world[1])
        center = self._pixel_to_ndc(*center_px)
        segments = 12
        vdata = GeomVertexData("dot", GeomVertexFormat.getV3(), Geom.UHStatic)
        vdata.setNumRows(1 + segments)
        writer = GeomVertexWriter(vdata, "vertex")
        cx, cy = center
        writer.addData3f(cx, 0, cy)
        for index in range(segments):
            angle = 2.0 * math.pi * index / segments
            px = center_px[0] + math.cos(angle) * radius_px
            py = center_px[1] + math.sin(angle) * radius_px
            nx, ny = self._pixel_to_ndc(px, py)
            writer.addData3f(nx, 0, ny)
        prim = GeomTriangles(Geom.UHStatic)
        for index in range(segments):
            prim.addVertices(0, index + 1, (index + 1) % segments + 1)
        prim.closePrimitive()
        geom = Geom(vdata)
        geom.addPrimitive(prim)
        node = GeomNode("minimap_dot")
        node.addGeom(geom)
        path = self.root.attachNewNode(node)
        path.setColor(Vec4(*color))
        path.setLightOff()
        self._nodes.append(path)
        return path

    def _build_start(self):
        start = self.track.start
        self._filled_circle((start[0], start[1]), 6.0, GREEN, sort=18)
        self._filled_circle((start[0], start[1]), 3.0, WHITE, sort=19)

    # ------------------------------------------------------------------ 自车
    def _build_car(self):
        # 固定本地三角形，位置/角度每帧用 NodePath 变换更新
        unit_x = self.aspect_width / float(self.screen_width)
        unit_y = 2.0 / float(self.screen_height)
        vdata = GeomVertexData("minimap_car", GeomVertexFormat.getV3(),
                               Geom.UHStatic)
        vdata.setNumRows(3)
        writer = GeomVertexWriter(vdata, "vertex")
        writer.addData3f(0.0, 0.0, 15.0 * unit_y)
        writer.addData3f(-7.5 * unit_x, 0.0, -4.5 * unit_y)
        writer.addData3f(7.5 * unit_x, 0.0, -4.5 * unit_y)
        prim = GeomTriangles(Geom.UHStatic)
        prim.addVertices(0, 1, 2)
        prim.closePrimitive()
        geom = Geom(vdata)
        geom.addPrimitive(prim)
        node = GeomNode("minimap_car")
        node.addGeom(geom)
        self._car = self.root.attachNewNode(node)
        self._car.setColor(Vec4(*RED))
        self._car.setLightOff()
        self._nodes.append(self._car)

    def update(self, vehicle):
        px, py = self._to_px(vehicle.x, vehicle.y)
        x, y = self._pixel_to_ndc(px, py)
        self._car.setPos(x, 0.0, y)
        self._car.setR(90.0 - math.degrees(vehicle.heading))

    def destroy(self):
        for node in self._nodes:
            try:
                node.removeNode()
            except Exception:
                pass
        self._nodes = []
