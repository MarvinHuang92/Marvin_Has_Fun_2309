# -*- coding: utf-8 -*-
"""赛道：从 ``cfg/tracks/track.json`` 读取中心线/宽度/起点，提供碰撞与最近点查询。

几何数据由 ``scripts/build_track.py`` 从 ``images/track.jpg`` 生成（构建期工具），
运行期只需要 JSON，不依赖 numpy/PIL/opencv。

坐标系与物理一致：米、y 向上；``start`` 为起点（世界原点附近），
``heading_rad`` 为出发方向（沿弯道编号 T1→T2→… 的比赛方向）。

碰撞：把车体近似成"中心点在中心线上、外接投影半径由车头朝向决定"的矩形，
只允许中心离中心线不超过 ``width/2 - 投影半径``；越界时把车推回边界内，
并去掉世界速度沿墙外的分量（保留切向分量）→ 沿墙滑动，不瞬间停车、无车损。
"""
import json
import math
import os


def _wrap_index(index, count):
    return index % count


class Track(object):
    """可行驶赛道（闭环中心线 + 宽度 + 起点）或圆形试车场。

    ``kind``：
    - ``"circuit"``（默认）：闭环赛道带，边界 = 中心线两侧 ``width/2``；
    - ``"circle"``：圆形试车场，只有最外侧半径 ``outer_radius_m`` 是墙，
      内部 ``guide_radius_m`` 的白色虚线只是参考线，不是墙。

    ``enabled`` 为 False 时所有查询安全地返回空结果（旧版矩形世界仍可用）。
    """

    def __init__(self, project_dir, config):
        cfg = (config or {}).get("track", {}) or {}
        self.enabled = bool(cfg.get("enabled", False))
        self.kind = "circuit"
        self.name = "Mini Race 2"
        self.display_name = self.name
        self.width_m = 15.0
        self.center = (0.0, 0.0)
        self.outer_radius_m = 0.0
        self.guide_radius_m = 0.0
        self.reset_to_start = False
        self.points = []
        self.corners = []
        self.elements = []
        self.segments = []
        self.start = (0.0, 0.0, math.pi / 2.0)
        self.reference = {}
        self.bbox = (0.0, 0.0, 0.0, 0.0)
        self.slide_drag = float(cfg.get("wall_slide_drag", 0.3))
        self.margin = float(cfg.get("wall_margin", 0.02))
        self._last_index = 0

        if not self.enabled:
            return

        rel = cfg.get("file", "cfg/tracks/track.json")
        path = rel if os.path.isabs(rel) else os.path.join(str(project_dir), rel)
        with open(path, "r", encoding="utf-8") as handle:
            data = json.load(handle)

        self.kind = str(data.get("kind", "circuit"))
        self.name = data.get("name", self.name)
        self.display_name = data.get("display_name", self.name)
        self.width_m = float(data.get("width_m", 15.0))
        if self.width_m <= 0.0:
            raise ValueError("track.width_m 必须为正数")
        self.center = tuple(float(value) for value in data.get("center", [0.0, 0.0]))
        self.outer_radius_m = float(data.get("outer_radius_m", 0.0))
        self.guide_radius_m = float(data.get("guide_radius_m", 0.0))
        self.reference = data.get("reference", {}) or {}
        self.reset_to_start = bool(self.reference.get("reset_to_start", False))
        self.points = [(float(point[0]), float(point[1]))
                       for point in data.get("centerline", [])]
        if len(self.points) < 20:
            raise ValueError("赛道中心线点太少：%d" % len(self.points))
        self.corners = list(data.get("corners", []) or [])
        for element in data.get("elements", []) or []:
            self.elements.append({
                "type": str(element.get("type", "straight")),
                "label": str(element.get("label", "-")),
                "start": int(element.get("start", 0)),
                "end": int(element.get("end", 0)),
            })
        self.left_edge = [(float(point[0]), float(point[1]))
                          for point in data.get("left_edge", [])] or None
        self.right_edge = [(float(point[0]), float(point[1]))
                           for point in data.get("right_edge", [])] or None
        start = data.get("start", {}) or {}
        self.start = (float(start.get("x", 0.0)),
                      float(start.get("y", 0.0)),
                      float(start.get("heading_rad", math.pi / 2.0)))

        if self.kind == "circle":
            if self.outer_radius_m <= 0.0 or self.guide_radius_m <= 0.0:
                raise ValueError("圆形地图需要 outer_radius_m / guide_radius_m")
            cx, cy = self.center
            margin = self.outer_radius_m + 20.0
            self.bbox = (cx - margin, cy - margin, cx + margin, cy + margin)
        else:
            xs = [point[0] for point in self.points]
            ys = [point[1] for point in self.points]
            margin = self.width_m * 2.0 + 20.0
            self.bbox = (min(xs) - margin, min(ys) - margin,
                         max(xs) + margin, max(ys) + margin)

        count = len(self.points)
        self.segments = []
        for index in range(count):
            x0, y0 = self.points[index]
            x1, y1 = self.points[(index + 1) % count]
            dx = x1 - x0
            dy = y1 - y0
            length = math.hypot(dx, dy)
            if length <= 1e-9:
                continue
            self.segments.append((x0, y0, dx / length, dy / length, length, index))

    # ------------------------------------------------------------------ 弯道
    def element_index_at(self, point_index):
        """返回中心线索引所属的元素下标（弯/直道交替序列）。"""
        if not self.elements:
            return None
        count = len(self.points)
        for index, element in enumerate(self.elements):
            start = element["start"]
            end = element["end"]
            if start <= end:
                if start <= point_index <= end:
                    return index
            else:
                if point_index >= start or point_index <= end:
                    return index
        return None

    def element_window_at(self, x, y, radius=2):
        """当前元素及前后各 2 个元素：返回 (labels, types, center_index)。"""
        if not self.elements:
            return None
        nearest = self.nearest(x, y)
        if nearest is None:
            return None
        element_index = self.element_index_at(nearest[5])
        if element_index is None:
            return None
        count = len(self.elements)
        labels = [self.elements[(element_index + offset) % count]["label"]
                  for offset in range(-radius, radius + 1)]
        types = [self.elements[(element_index + offset) % count]["type"]
                 for offset in range(-radius, radius + 1)]
        return labels, types, radius

    def direction_error(self, x, y, heading):
        """车头方向与最近中心线前进方向的夹角（弧度，wrap 到 [-pi, pi]）。"""
        nearest = self.nearest(x, y)
        if nearest is None:
            return 0.0
        tx, ty = nearest[3], nearest[4]
        target = math.atan2(ty, tx)
        return (float(heading) - target + math.pi) % (2.0 * math.pi) - math.pi

    # ------------------------------------------------------------------ 对外
    @property
    def lap_length_m(self):
        return float(self.reference.get("lap_length_m", 0.0)) or sum(
            segment[4] for segment in self.segments)

    def nearest(self, x, y, hint_index=None):
        """返回离 (x, y) 最近的中心线点：(距离, 最近点x, 最近点y, 切向x, 切向y, 段索引)。"""
        if not self.segments:
            return None
        if self.kind == "circle":
            cx, cy = self.center
            dx = x - cx
            dy = y - cy
            distance = math.hypot(dx, dy)
            if distance < 1e-9:
                angle = self.start[2] + math.pi * 0.5
            else:
                angle = math.atan2(dy, dx)
            radius = self.guide_radius_m
            px = cx + radius * math.cos(angle)
            py = cy + radius * math.sin(angle)
            # 虚线圆的"前进方向"与起点方向一致（逆时针）
            tx = -math.sin(angle)
            ty = math.cos(angle)
            return (abs(distance - radius), px, py, tx, ty, 0)
        total = len(self.segments)
        if hint_index is None:
            hint_index = self._last_index
        start = hint_index - 24
        indices = [(start + offset) % total for offset in range(48)]
        best = None
        for index in indices:
            x0, y0, tx, ty, length, _point_index = self.segments[index]
            dx = x - x0
            dy = y - y0
            along = dx * tx + dy * ty
            if along < 0.0:
                along = 0.0
            elif along > length:
                along = length
            cx = x0 + tx * along
            cy = y0 + ty * along
            distance = math.hypot(x - cx, y - cy)
            if best is None or distance < best[0]:
                best = (distance, cx, cy, tx, ty, index)
        if best[0] > self.width_m * 2.0:
            # 偏离太远（传送/复位异常）：退化为全量搜索，避免锁定在错误的局部段
            for index in range(total):
                x0, y0, tx, ty, length, _point_index = self.segments[index]
                dx = x - x0
                dy = y - y0
                along = max(0.0, min(length, dx * tx + dy * ty))
                cx = x0 + tx * along
                cy = y0 + ty * along
                distance = math.hypot(x - cx, y - cy)
                if distance < best[0]:
                    best = (distance, cx, cy, tx, ty, index)
        self._last_index = best[5]
        return best

    def progress_at(self, x, y):
        """返回沿比赛方向、从起点量起的中心线里程（米）。"""
        nearest = self.nearest(x, y)
        if nearest is None or not self.segments:
            return 0.0
        segment_index = int(nearest[5]) % len(self.segments)
        x0, y0, tx, ty, length, _point_index = self.segments[segment_index]
        along = (float(x) - x0) * tx + (float(y) - y0) * ty
        along = max(0.0, min(length, along))
        cumulative = sum(segment[4] for segment in
                         self.segments[:segment_index])
        value = float(cumulative + along)
        lap_length = float(self.lap_length_m)
        if lap_length > 1.0:
            value %= lap_length
        return value

    def resolve_collision(self, vehicle, telemetry, dt):
        """把车限制在赛道内；撞墙时沿墙滑动。返回是否发生碰撞。"""
        if not self.segments:
            return False
        if self.kind == "circle":
            return self._resolve_circle(vehicle, telemetry, dt)
        nearest = self.nearest(vehicle.x, vehicle.y)
        if nearest is None:
            return False
        distance, cx, cy, tx, ty, index = nearest
        if distance <= 1e-6:
            return False
        # 车体在"墙法线"方向上的投影半宽（矩形投影）
        tangent_angle = math.atan2(ty, tx)
        relative = vehicle.heading - tangent_angle
        support = (abs(math.cos(relative)) * vehicle.p.half_width
                   + abs(math.sin(relative)) * vehicle.p.half_length)
        allowed = self.width_m * 0.5 - support - self.margin
        if allowed < 0.0:
            allowed = 0.0
        if distance <= allowed:
            return False

        ux = (vehicle.x - cx) / distance
        uy = (vehicle.y - cy) / distance
        push = distance - allowed
        vehicle.x -= ux * push
        vehicle.y -= uy * push
        self._apply_wall_response(vehicle, telemetry, ux, uy, dt)
        return True

    def _resolve_circle(self, vehicle, telemetry, dt):
        """圆形试车场：只有最外侧半径是墙，内部虚线可自由跨越。"""
        cx, cy = self.center
        dx = vehicle.x - cx
        dy = vehicle.y - cy
        radius = math.hypot(dx, dy)
        if radius < 1e-9:
            return False
        ux = dx / radius
        uy = dy / radius
        radial_angle = math.atan2(uy, ux)
        relative = vehicle.heading - radial_angle
        support = (abs(math.cos(relative)) * vehicle.p.half_length
                   + abs(math.sin(relative)) * vehicle.p.half_width)
        allowed = self.outer_radius_m - support - self.margin
        if allowed < 0.0:
            allowed = 0.0
        if radius <= allowed:
            return False
        push = radius - allowed
        vehicle.x -= ux * push
        vehicle.y -= uy * push
        self._apply_wall_response(vehicle, telemetry, ux, uy, dt)
        return True

    def _apply_wall_response(self, vehicle, telemetry, ux, uy, dt):
        """去掉速度沿墙外法线 (ux, uy) 的分量，保留切向分量（沿墙滑动）。"""
        cos_h = math.cos(vehicle.heading)
        sin_h = math.sin(vehicle.heading)
        world_vx = vehicle.vx * cos_h - vehicle.vy * sin_h
        world_vy = vehicle.vx * sin_h + vehicle.vy * cos_h
        outward = world_vx * ux + world_vy * uy
        if outward > 0.0:
            world_vx -= outward * ux
            world_vy -= outward * uy
        factor = math.exp(-self.slide_drag * max(0.0, dt))
        world_vx *= factor
        world_vy *= factor
        vehicle.vx = world_vx * cos_h + world_vy * sin_h
        vehicle.vy = -world_vx * sin_h + world_vy * cos_h

        telemetry.wall_hit = True
        telemetry.x = vehicle.x
        telemetry.y = vehicle.y
        telemetry.vx = vehicle.vx
        telemetry.vy = vehicle.vy
        telemetry.speed_abs = math.hypot(vehicle.vx, vehicle.vy)
        telemetry.beta_deg = math.degrees(math.atan2(vehicle.vy, vehicle.vx))
