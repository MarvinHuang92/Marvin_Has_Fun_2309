# -*- coding: utf-8 -*-
"""把现有 2D 赛道数据搭成 Panda3D 场景（物理保持不变）。"""
import math

from panda3d.core import NodePath, Vec3

from minirace3d.geometry import MeshBuilder, material

CURB_HEIGHT = 0.4
CURB_WIDTH = 1.2
POST_RADIUS = 0.12
POST_HEIGHT = 2.0

ASPHALT = (0.20, 0.21, 0.24)
ASPHALT_EDGE = (0.78, 0.78, 0.80)
WHITE = (0.94, 0.94, 0.92)
RED = (0.86, 0.08, 0.08)
DARK = (0.10, 0.10, 0.11)
GREEN = (0.16, 0.30, 0.13)
CAR_RED = (0.78, 0.03, 0.04)
CAR_DARK = (0.08, 0.08, 0.09)


def _point(x, y, z=0.0):
    return Vec3(float(x), float(y), float(z))


def _normalize(x, y):
    length = math.hypot(x, y)
    if length < 1e-9:
        return (1.0, 0.0)
    return (x / length, y / length)


class TrackScene(object):
    def __init__(self, track, parent):
        self.track = track
        self.parent = parent
        self.root = parent.attachNewNode("track_scene")
        self.posts = []
        self.materials = {
            "asphalt": material(ASPHALT),
            "edge": material(ASPHALT_EDGE),
            "white": material(WHITE),
            "red": material(RED),
            "dark": material(DARK),
            "green": material(GREEN),
            "car_red": material(CAR_RED, specular=0.3),
            "car_dark": material(CAR_DARK),
        }

    # ------------------------------------------------------------------ 主入口
    def build(self):
        self._build_ground()
        self._build_asphalt()
        self._build_curbs()
        if self.track.kind == "circuit":
            self._build_start_line()
            self._build_gantry()
        else:
            self._build_circle_guide()
            self._build_start_line()
        self._build_posts()
        return self.root

    # ------------------------------------------------------------------ 地面/赛道
    def _build_ground(self):
        builder = MeshBuilder("ground")
        extent = 3000.0
        builder.add_quad(_point(-extent, -extent, -0.03),
                         _point(extent, -extent, -0.03),
                         _point(extent, extent, -0.03),
                         _point(-extent, extent, -0.03), Vec3(0, 0, 1))
        builder.build(self.root, self.materials["green"])

    def _build_asphalt(self):
        builder = MeshBuilder("asphalt")
        if self.track.kind == "circle":
            radius = self.track.outer_radius_m
            center = self.track.center
            segments = 128
            for index in range(segments):
                a0 = 2.0 * math.pi * index / segments
                a1 = 2.0 * math.pi * (index + 1) / segments
                builder.add_triangle(
                    _point(center[0], center[1], 0.0),
                    _point(center[0] + radius * math.cos(a0),
                           center[1] + radius * math.sin(a0), 0.0),
                    _point(center[0] + radius * math.cos(a1),
                           center[1] + radius * math.sin(a1), 0.0),
                    Vec3(0, 0, 1))
        else:
            left = self.track.left_edge
            right = self.track.right_edge
            count = len(self.track.points)
            for index in range(count):
                nxt = (index + 1) % count
                if len(left) <= index or len(right) <= index:
                    break
                builder.add_quad(_point(left[index][0], left[index][1], 0.0),
                                 _point(left[nxt][0], left[nxt][1], 0.0),
                                 _point(right[nxt][0], right[nxt][1], 0.0),
                                 _point(right[index][0], right[index][1], 0.0),
                                 Vec3(0, 0, 1))
        builder.build(self.root, self.materials["asphalt"])

    # ------------------------------------------------------------------ 路肩
    def _add_curb_box(self, red_builder, white_builder, a, b, outward, color_index):
        inner_a = Vec3(float(a[0]), float(a[1]), 0.0)
        inner_b = Vec3(float(b[0]), float(b[1]), 0.0)
        normal = Vec3(outward[0], outward[1], 0.0)
        outer_a = inner_a + normal * CURB_WIDTH
        outer_b = inner_b + normal * CURB_WIDTH
        tangent = (inner_b - inner_a)
        if tangent.length() < 1e-6:
            return
        tangent.normalize()
        up = Vec3(0, 0, 1)
        top_z = CURB_HEIGHT
        inner_a_top = Vec3(inner_a.x, inner_a.y, top_z)
        inner_b_top = Vec3(inner_b.x, inner_b.y, top_z)
        outer_a_top = Vec3(outer_a.x, outer_a.y, top_z)
        outer_b_top = Vec3(outer_b.x, outer_b.y, top_z)
        builder = red_builder if color_index % 2 == 0 else white_builder
        # 顶面 / 内外侧面 / 两端
        builder.add_quad(inner_a_top, inner_b_top, outer_b_top, outer_a_top, up)
        builder.add_quad(inner_a, inner_b, inner_b_top, inner_a_top,
                         (-normal).normalized())
        builder.add_quad(outer_b, outer_a, outer_a_top, outer_b_top,
                         normal.normalized())
        builder.add_quad(inner_a, inner_a_top, outer_a_top, outer_a,
                         (-tangent).normalized())
        builder.add_quad(inner_b, outer_b, outer_b_top, inner_b_top,
                         tangent.normalized())

    def _build_curbs(self):
        red = MeshBuilder("curb_red")
        white = MeshBuilder("curb_white")
        track = self.track
        if track.kind == "circle":
            center = track.center
            radius = track.outer_radius_m
            segments = max(96, int(round(2.0 * math.pi * radius / 4.0)))
            for index in range(segments):
                a0 = 2.0 * math.pi * index / segments
                a1 = 2.0 * math.pi * (index + 1) / segments
                p0 = (center[0] + radius * math.cos(a0),
                      center[1] + radius * math.sin(a0))
                p1 = (center[0] + radius * math.cos(a1),
                      center[1] + radius * math.sin(a1))
                outward = _normalize((p0[0] + p1[0]) / 2.0 - center[0],
                                     (p0[1] + p1[1]) / 2.0 - center[1])
                self._add_curb_box(red, white, p0, p1, outward, index)
        else:
            center = track.points
            for edge in (track.left_edge, track.right_edge):
                count = len(center)
                color_index = 0
                for index in range(count):
                    nxt = (index + 1) % count
                    if len(edge) <= index:
                        break
                    a = edge[index]
                    b = edge[nxt]
                    mx = (a[0] + b[0]) * 0.5 - (center[index][0] + center[nxt][0]) * 0.5
                    my = (a[1] + b[1]) * 0.5 - (center[index][1] + center[nxt][1]) * 0.5
                    outward = _normalize(mx, my)
                    segment = math.hypot(b[0] - a[0], b[1] - a[1])
                    pieces = max(1, int(math.ceil(segment / 5.0)))
                    for piece in range(pieces):
                        t0 = piece / float(pieces)
                        t1 = (piece + 1) / float(pieces)
                        pa = (a[0] + (b[0] - a[0]) * t0,
                              a[1] + (b[1] - a[1]) * t0)
                        pb = (a[0] + (b[0] - a[0]) * t1,
                              a[1] + (b[1] - a[1]) * t1)
                        self._add_curb_box(red, white, pa, pb, outward,
                                           color_index)
                        color_index += 1
        red.build(self.root, self.materials["red"])
        white.build(self.root, self.materials["white"])

    # ------------------------------------------------------------------ 起点线 / 龙门架
    def _build_circle_guide(self):
        """圆形试车场：把 2D 里的 Ø360 m 白色虚线参考圆也画出来。"""
        center = self.track.center
        radius = self.track.guide_radius_m
        if radius <= 0:
            return
        builder = MeshBuilder("circle_guide")
        dash_angle = 5.0 / max(radius, 1.0)
        step = dash_angle * 2.0
        angle = 0.0
        width = 0.15
        while angle < 2.0 * math.pi:
            a0 = angle
            a1 = min(2.0 * math.pi, angle + dash_angle)
            p0 = (center[0] + (radius - width) * math.cos(a0),
                  center[1] + (radius - width) * math.sin(a0))
            p1 = (center[0] + (radius + width) * math.cos(a0),
                  center[1] + (radius + width) * math.sin(a0))
            p2 = (center[0] + (radius + width) * math.cos(a1),
                  center[1] + (radius + width) * math.sin(a1))
            p3 = (center[0] + (radius - width) * math.cos(a1),
                  center[1] + (radius - width) * math.sin(a1))
            builder.add_quad(_point(p0[0], p0[1], 0.016),
                             _point(p1[0], p1[1], 0.016),
                             _point(p2[0], p2[1], 0.016),
                             _point(p3[0], p3[1], 0.016), Vec3(0, 0, 1))
            angle += step
        builder.build(self.root, self.materials["white"])

    def _start_frame(self):
        points = self.track.points
        sx, sy, _heading = self.track.start
        tx = points[1][0] - sx
        ty = points[1][1] - sy
        tx, ty = _normalize(tx, ty)
        nx, ny = -ty, tx
        return (sx, sy), (tx, ty), (nx, ny)

    def _build_start_line(self):
        start, tangent, normal = self._start_frame()
        black = MeshBuilder("start_black")
        white = MeshBuilder("start_white")
        if self.track.kind == "circle":
            half_width = 12.0
        else:
            half_width = max(1.0, self.track.width_m * 0.5 - 0.25)
        line_length = 1.8
        tile = 0.6
        columns = max(2, int(round((2.0 * half_width) / tile)))
        rows = max(2, int(round(line_length / tile)))
        for row in range(rows):
            s0 = row * line_length / rows
            s1 = (row + 1) * line_length / rows
            for col in range(columns):
                u0 = -half_width + col * (2.0 * half_width) / columns
                u1 = -half_width + (col + 1) * (2.0 * half_width) / columns
                p0 = (start[0] + tangent[0] * s0 + normal[0] * u0,
                      start[1] + tangent[1] * s0 + normal[1] * u0, 0.012)
                p1 = (start[0] + tangent[0] * s0 + normal[0] * u1,
                      start[1] + tangent[1] * s0 + normal[1] * u1, 0.012)
                p2 = (start[0] + tangent[0] * s1 + normal[0] * u1,
                      start[1] + tangent[1] * s1 + normal[1] * u1, 0.012)
                p3 = (start[0] + tangent[0] * s1 + normal[0] * u0,
                      start[1] + tangent[1] * s1 + normal[1] * u0, 0.012)
                builder = black if (row + col) % 2 == 0 else white
                builder.add_quad(_point(*p0), _point(*p1), _point(*p2),
                                 _point(*p3), Vec3(0, 0, 1))
        black.build(self.root, self.materials["dark"])
        white.build(self.root, self.materials["white"])

    def _build_gantry(self):
        start, tangent, normal = self._start_frame()
        half_width = self.track.width_m * 0.5
        offset = half_width + CURB_WIDTH + 0.5
        red = MeshBuilder("gantry_red")
        white = MeshBuilder("gantry_white")
        dark = MeshBuilder("gantry_dark")
        tangent_v = Vec3(tangent[0], tangent[1], 0)
        normal_v = Vec3(normal[0], normal[1], 0)
        up = Vec3(0, 0, 1)
        axes = (normal_v, tangent_v, up)
        for side in (-1, 1):
            cx = start[0] + normal[0] * offset * side
            cy = start[1] + normal[1] * offset * side
            builder = red if side < 0 else white
            builder.add_box(Vec3(cx, cy, 2.2), (0.18, 0.18, 2.2), axes)
        # 横梁：底部离地 4 m；红白相间
        span = 2.0 * offset
        segments = 8
        for index in range(segments):
            part = span / segments
            center = (start[0] + normal[0] * (-span / 2.0 + part * (index + 0.5)),
                      start[1] + normal[1] * (-span / 2.0 + part * (index + 0.5)))
            builder = red if index % 2 == 0 else white
            builder.add_box(Vec3(center[0], center[1], 4.2),
                            (part * 0.5, 0.22, 0.2), axes)
        # 上方 START/FINISH 牌（深色 + 白条）
        dark.add_box(Vec3(start[0], start[1], 4.85), (span * 0.34, 0.10, 0.28), axes)
        for side in (-1, 1):
            cx = start[0] + normal[0] * span * 0.25 * side
            cy = start[1] + normal[1] * span * 0.25 * side
            white.add_box(Vec3(cx, cy, 4.85), (span * 0.06, 0.12, 0.20), axes)
        red.build(self.root, self.materials["red"])
        white.build(self.root, self.materials["white"])
        dark.build(self.root, self.materials["dark"])

    # ------------------------------------------------------------------ 弯心柱
    def _add_post(self, red, white, x, y, z=0.0):
        self.posts.append((x, y))
        for builder, z0, z1 in ((red, z, z + POST_HEIGHT / 3.0),
                                (white, z + POST_HEIGHT / 3.0,
                                 z + POST_HEIGHT * 2.0 / 3.0),
                                (red, z + POST_HEIGHT * 2.0 / 3.0,
                                 z + POST_HEIGHT)):
            builder.add_cylinder(x, y, z0, z1, POST_RADIUS, 10,
                                 top=(z1 >= z + POST_HEIGHT - 1e-6))

    def _inside_normal(self, index, direction=None):
        points = self.track.points
        count = len(points)
        prev = points[(index - 1) % count]
        nxt = points[(index + 1) % count]
        tx = nxt[0] - prev[0]
        ty = nxt[1] - prev[1]
        tx, ty = _normalize(tx, ty)
        # 左法线；direction=+1 左弯，内侧在左；direction=-1 右弯，内侧在右
        if direction is None:
            direction = 1
            for corner in self.track.corners:
                if int(corner.get("apex", -1)) == int(index):
                    direction = int(corner.get("direction", 1))
                    break
        left = (-ty, tx)
        if direction >= 0:
            return left
        return (-left[0], -left[1])

    def _post_position(self, index, direction=None):
        point = self.track.points[index]
        inside = self._inside_normal(index, direction)
        offset = self.track.width_m * 0.5 + CURB_WIDTH * 0.5
        return (point[0] + inside[0] * offset,
                point[1] + inside[1] * offset)

    def _sample_arc(self, start, end, count):
        points = self.track.points
        total = len(points)
        if end < start:
            end += total
        indices = list(range(start, end + 1))
        lengths = [0.0]
        for index in range(1, len(indices)):
            a = points[indices[index - 1] % total]
            b = points[indices[index] % total]
            lengths.append(lengths[-1] + math.hypot(b[0] - a[0], b[1] - a[1]))
        total_length = lengths[-1]
        result = []
        for sample in range(count):
            target = total_length * sample / float(max(1, count - 1))
            position = 0
            while (position + 1 < len(lengths)
                   and lengths[position + 1] < target):
                position += 1
            if position + 1 >= len(lengths):
                index = indices[-1]
            else:
                segment = lengths[position + 1] - lengths[position]
                frac = 0.0 if segment <= 1e-9 else (target - lengths[position]) / segment
                index = indices[position]
                # 使用最近点索引即可；柱子之间的距离已经足够均匀
                if frac > 0.5:
                    index = indices[position + 1]
            result.append(index % total)
        return result

    def _curvature(self, index, span=3):
        points = self.track.points
        count = len(points)
        a = points[(index - span) % count]
        b = points[index % count]
        c = points[(index + span) % count]
        a0 = math.atan2(b[1] - a[1], b[0] - a[0])
        a1 = math.atan2(c[1] - b[1], c[0] - b[0])
        delta = (a1 - a0 + math.pi) % (2.0 * math.pi) - math.pi
        distance = math.hypot(c[0] - a[0], c[1] - a[1])
        return delta / distance if distance > 1e-9 else 0.0

    def _corner_apex(self, corner):
        start = int(corner.get("start", 0))
        end = int(corner.get("end", start))
        total = len(self.track.points)
        if end < start:
            end += total
        best_index = start % total
        best_value = -1.0
        for extended in range(start, end + 1):
            index = extended % total
            value = abs(self._curvature(index))
            if value > best_value:
                best_value = value
                best_index = index
        return best_index

    def _build_posts(self):
        red = MeshBuilder("post_red")
        white = MeshBuilder("post_white")
        if self.track.kind == "circle":
            return
        if self.track.kind == "circuit" and self.track.name.startswith("Shanghai"):
            for corner in self.track.corners:
                index = self._corner_apex(corner)
                direction = int(corner.get("direction", 1))
                x, y = self._post_position(index, direction)
                self._add_post(red, white, x, y)
        elif self.track.kind == "circuit":
            # 椭圆：每个弯的进弯/出弯和中间共 8 根
            for corner in self.track.corners:
                indices = self._sample_arc(int(corner["start"]),
                                           int(corner["end"]), 8)
                direction = int(corner.get("direction", 1))
                for index in indices:
                    x, y = self._post_position(index, direction)
                    self._add_post(red, white, x, y)
        red.build(self.root, self.materials["red"])
        white.build(self.root, self.materials["white"])

    # ------------------------------------------------------------------ 车
    def build_car(self, color=None):
        root = self.root.attachNewNode("car")
        body = MeshBuilder("car_body")
        cabin = MeshBuilder("car_cabin")
        dark = MeshBuilder("car_dark")
        body.add_box(Vec3(0, 0, 0.55), (0.92, 2.10, 0.26))
        body.add_box(Vec3(0, 1.45, 0.68), (0.78, 0.42, 0.12))
        body.add_box(Vec3(0, -1.75, 0.66), (0.78, 0.28, 0.10))
        cabin.add_box(Vec3(0, -0.10, 0.86), (0.65, 0.92, 0.25))
        for x in (-0.92, 0.92):
            for y in (-1.35, 1.35):
                dark.add_box(Vec3(x, y, 0.34), (0.14, 0.34, 0.30))
        body_material = (self.materials["car_red"] if color is None
                         else material(tuple(color), specular=0.3))
        body.build(root, body_material)
        cabin.build(root, self.materials["car_dark"])
        dark.build(root, self.materials["car_dark"])
        return root


class SceneBuilder(object):
    """供 app 调用：构建赛道 + 车。"""

    def __init__(self, track, parent):
        self.track_scene = TrackScene(track, parent)

    @property
    def root(self):
        return self.track_scene.root

    def build(self):
        self.track_scene.build()
        return self.track_scene

    def build_car(self, color=None):
        return self.track_scene.build_car(color=color)
