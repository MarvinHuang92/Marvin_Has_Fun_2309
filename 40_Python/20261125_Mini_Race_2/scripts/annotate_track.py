# -*- coding: utf-8 -*-
"""半自动弯道标注工具（tkinter）。

用途：在赛道原图上按比赛方向依次点击每个弯的弯心，自动生成
``cfg/tracks/track_*.json`` 里的 ``corners`` / ``elements``（5 要素窗口数据）。

前提：赛道 JSON 是从同一张图片生成的，并且 ``reference`` 里有
``start_pixel`` + ``scale_m_per_px``（``build_baoshan_track.py`` /
``build_track.py`` 生成的地图通常都有）。

跑法::

    python scripts/annotate_track.py ^
        --image images/track_baoshan_kartin.bmp ^
        --track cfg/tracks/track_baoshan.json

也可以半自动批量（不用 GUI）::

    python scripts/annotate_track.py --image ... --track ... ^
        --pixels "166,220; 245,180; ..."

操作：
- 先点 "Set Start / Direction"，依次点击起点、起点前方行驶方向上的一个点；
  工具会重排中心线、左右边界、start/heading，并把图片像素映射更新到新起点；
- 然后按比赛方向依次点击弯心（自动吸附最近中心线点）；
- Undo / Clear 重来；
- Save 写回 JSON（即使还没标弯，也可以保存新的起点/方向）。

注意：更改起点/方向会使旧的弯心索引失效，因此会清空已有弯道标注；
请优先确定起点和方向，再标 T1、T2、...。弯的 start/end 由曲率自动展开。
"""
import argparse
import json
import math
import os
import sys
import tkinter as tk
from tkinter import messagebox, ttk

import numpy as np
from PIL import Image, ImageDraw, ImageTk

PROJECT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(PROJECT, "scripts"))

import build_track as bt  # noqa: E402

DEFAULT_IMAGE = os.path.join(PROJECT, "images", "track_baoshan_kartin.bmp")
DEFAULT_TRACK = os.path.join(PROJECT, "cfg", "tracks", "track_baoshan.json")
CANVAS_W = 1180
CANVAS_H = 720


def _reference_transform(track):
    ref = track.get("reference", {}) or {}
    origin = ref.get("start_pixel")
    scale = ref.get("scale_m_per_px")
    if origin is None or not scale:
        return None
    return (float(origin[0]), float(origin[1]), float(scale))


def world_to_pixel(track, x, y, transform=None):
    values = transform or _reference_transform(track)
    if values is None:
        return None
    origin_x, origin_y, scale = values
    return (origin_x + float(x) / scale,
            origin_y - float(y) / scale)


def pixel_to_world(track, px, py, transform=None):
    values = transform or _reference_transform(track)
    if values is None:
        return None
    origin_x, origin_y, scale = values
    return ((float(px) - origin_x) * scale,
            -(float(py) - origin_y) * scale)


class Annotator(object):
    def __init__(self, image_path, track_path, out_path, start_label=1):
        with open(track_path, "r", encoding="utf-8") as handle:
            self.track = json.load(handle)
        self.track_path = track_path
        self.out_path = out_path
        self.image = Image.open(image_path).convert("RGB")
        self.transform = _reference_transform(self.track)
        if self.transform is None:
            raise ValueError(
                "赛道 JSON 缺少 reference.start_pixel / scale_m_per_px；"
                "请用 build_track.py / build_baoshan_track.py 风格生成")
        self.centerline = np.asarray(self.track["centerline"], dtype=np.float64)
        self.points_px = np.asarray(
            [world_to_pixel(self.track, x, y, self.transform)
             for x, y in self.centerline], dtype=np.float64)
        self.anchors = []
        self.next_label = max(1, int(start_label))
        self.start_mode = None
        self.pending_start = None

        self.root = tk.Tk()
        self.root.title("Mini Race 2 · 半自动弯道标注")
        self.root.geometry("%dx%d" % (CANVAS_W, CANVAS_H + 120))
        self._fit_scale = min(
            (CANVAS_W - 20) / float(self.image.width),
            (CANVAS_H - 20) / float(self.image.height))
        self._fit_scale = max(0.2, self._fit_scale)
        self._canvas_w = int(round(self.image.width * self._fit_scale))
        self._canvas_h = int(round(self.image.height * self._fit_scale))
        self._build_ui()
        self._redraw()

    # ------------------------------------------------------------------ UI
    def _build_ui(self):
        top = ttk.Frame(self.root)
        top.pack(fill=tk.X, padx=8, pady=(6, 2))
        ttk.Label(top, text="标注弯心：左键点弯道；起点/方向：点下方按钮后两次点击",
                  font=("Consolas", 10, "bold")).pack(side=tk.LEFT)
        self.info = ttk.Label(top, text="", foreground="#666")
        self.info.pack(side=tk.RIGHT)
        self.canvas = tk.Canvas(self.root, width=self._canvas_w,
                                height=self._canvas_h, bg="#111111",
                                highlightthickness=0)
        self.canvas.pack(padx=8, pady=4)
        self.canvas.bind("<Button-1>", self._on_click)
        self._photo = None

        settings = ttk.Frame(self.root)
        settings.pack(fill=tk.X, padx=8, pady=(0, 2))
        ttk.Label(settings, text="每个弯心的柱子数量（0=不显示，默认1）：").pack(
            side=tk.LEFT)
        ref = self.track.get("reference", {}) or {}
        self.post_count_var = tk.StringVar(
            value=str(int(ref.get("corner_post_count", 1) or 1)))
        tk.Spinbox(settings, from_=0, to=24, width=5,
                   textvariable=self.post_count_var).pack(side=tk.LEFT, padx=4)
        ttk.Label(settings, text="（存到 track.reference.corner_post_count）",
                  foreground="#666").pack(side=tk.LEFT)

        bar = ttk.Frame(self.root)
        bar.pack(fill=tk.X, padx=8, pady=4)
        ttk.Button(bar, text="Set Start / Direction",
                   command=self._begin_start).pack(side=tk.LEFT)
        ttk.Button(bar, text="Undo", command=self._undo).pack(side=tk.LEFT, padx=(8, 0))
        ttk.Button(bar, text="Clear", command=self._clear).pack(side=tk.LEFT, padx=6)
        ttk.Button(bar, text="Save", command=self._save).pack(side=tk.LEFT)
        ttk.Button(bar, text="Quit", command=self._quit).pack(side=tk.RIGHT)
        self.status = ttk.Label(self.root, text="", foreground="#555")
        self.status.pack(fill=tk.X, padx=8, pady=(0, 6))
        self._update_info()

    def _update_info(self):
        ref = self.track.get("reference", {}) or {}
        self.info.configure(
            text="%s  ·  lap %.0f m  ·  %d points" % (
                os.path.basename(self.track_path),
                float(ref.get("lap_length_m", 0.0)),
                len(self.centerline)))

    # ------------------------------------------------------------------ 绘制
    def _redraw(self):
        image = self.image.resize((self._canvas_w, self._canvas_h),
                                  Image.LANCZOS)
        draw = ImageDraw.Draw(image)

        def to_canvas(x, y):
            return (x * self._fit_scale, y * self._fit_scale)

        # 中心线
        path = [to_canvas(x, y) for x, y in self.points_px]
        if len(path) > 1:
            draw.line(path, fill=(60, 220, 255), width=2)
        # 每 10 个点显示索引，便于人工核对
        for index in range(0, len(path), 10):
            x, y = path[index]
            draw.ellipse([x - 1.5, y - 1.5, x + 1.5, y + 1.5],
                         fill=(80, 200, 120))
            if index % 30 == 0:
                draw.text((x + 3, y - 9), str(index), fill=(210, 235, 160))
        # 起点 + 行驶方向
        if len(path) > 1:
            sx, sy = path[0]
            nx, ny = path[min(10, len(path) - 1)]
            draw.ellipse([sx - 6, sy - 6, sx + 6, sy + 6],
                         outline=(80, 255, 140), width=3)
            draw.line([sx, sy, nx, ny], fill=(80, 255, 140), width=2)
            draw.text((sx + 8, sy - 10), "START", fill=(80, 255, 140))
        if self.pending_start is not None:
            px, py = self.pending_start
            draw.ellipse([px * self._fit_scale - 6,
                          py * self._fit_scale - 6,
                          px * self._fit_scale + 6,
                          py * self._fit_scale + 6],
                         outline=(255, 230, 60), width=3)

        # 已标注弯心
        for label, index in self.anchors:
            x, y = path[index]
            draw.ellipse([x - 5, y - 5, x + 5, y + 5],
                         outline=(255, 80, 60), width=2)
            draw.text((x + 6, y - 6), "T%d" % label, fill=(255, 220, 80))
        self._photo = ImageTk.PhotoImage(image)
        self.canvas.delete("all")
        self.canvas.create_image(0, 0, anchor=tk.NW, image=self._photo)
        if self.start_mode == "start":
            self.status.configure(text="设置起点：左键点击赛道上的起点位置。")
        elif self.start_mode == "direction":
            self.status.configure(text="定义方向：再点击该起点前方赛道上的一个点。")
        elif self.anchors:
            self.status.configure(
                text="已标 %d 个弯：%s" % (
                    len(self.anchors),
                    " ".join("T%d" % label for label, _ in self.anchors)))
        else:
            self.status.configure(text="尚未标注弯心；左键点击 T1 弯心开始。")

    # ------------------------------------------------------------------ 操作
    def _nearest_centerline(self, px, py):
        distances = ((self.points_px[:, 0] - px) ** 2
                     + (self.points_px[:, 1] - py) ** 2)
        index = int(np.argmin(distances))
        return index, math.sqrt(float(distances[index]))

    def _on_click(self, event):
        px = event.x / self._fit_scale
        py = event.y / self._fit_scale
        index, distance_px = self._nearest_centerline(px, py)
        if distance_px > 35.0:
            messagebox.showinfo("离赛道太远",
                                "点击位置离中心线约 %.1f px，请点弯道附近。"
                                % distance_px)
            return
        if self.start_mode == "start":
            self.pending_start = (self.points_px[index, 0],
                                  self.points_px[index, 1])
            self.pending_start_index = index
            self.start_mode = "direction"
            self._redraw()
            return
        if self.start_mode == "direction":
            self._apply_start_direction(index)
            return
        # 如果已经点过同一索引，不重复添加
        if any(existing == index for _, existing in self.anchors):
            messagebox.showinfo("重复点", "这个中心线点已经标注过了。")
            return
        self.anchors.append((self.next_label, index))
        self.next_label += 1
        self._redraw()

    def _begin_start(self):
        self.start_mode = "start"
        self.pending_start = None
        self._redraw()

    def _apply_start_direction(self, direction_index):
        """第一次点起点，第二次点行驶方向上的点；自动决定正/反向。"""
        if self.pending_start is None:
            self.start_mode = "start"
            return
        start_index = getattr(self, "pending_start_index", 0)
        count = len(self.centerline)
        forward = (int(direction_index) - start_index) % count
        backward = (-forward) % count
        if forward == 0 or min(forward, backward) < 2:
            messagebox.showinfo("方向不明确", "请点击起点前方一段距离处的赛道点。")
            self.start_mode = "direction"
            return
        reverse = backward < forward
        start_px = self.pending_start
        centerline = np.asarray(self.centerline, dtype=np.float64).copy()
        if reverse:
            centerline = centerline[::-1]
            start_index = (count - 1 - start_index) % count
        centerline = np.roll(centerline, -start_index, axis=0)
        centerline = centerline - centerline[0]
        heading = math.atan2(centerline[1][1] - centerline[0][1],
                             centerline[1][0] - centerline[0][0])
        width = float(self.track.get("width_m", 15.0))
        tangents = np.roll(centerline, -1, axis=0) - centerline
        lengths = np.hypot(tangents[:, 0], tangents[:, 1])
        tangents /= np.maximum(lengths, 1e-9)[:, None]
        normals = np.stack([-tangents[:, 1], tangents[:, 0]], axis=1)
        half = width * 0.5
        self.centerline = centerline
        self.track["centerline"] = [[round(float(x), 3), round(float(y), 3)]
                                    for x, y in centerline]
        self.track["left_edge"] = [[round(float(x), 3), round(float(y), 3)]
                                   for x, y in centerline + normals * half]
        self.track["right_edge"] = [[round(float(x), 3), round(float(y), 3)]
                                    for x, y in centerline - normals * half]
        self.track["start"] = {"x": 0.0, "y": 0.0, "heading_rad": heading}
        ref = self.track.setdefault("reference", {})
        ref["start_pixel"] = [round(float(start_px[0]), 3),
                             round(float(start_px[1]), 3)]
        ref["start_from"] = "annotator start click"
        ref["direction"] = "reverse" if reverse else "forward"
        self.transform = (float(start_px[0]), float(start_px[1]),
                          float(ref.get("scale_m_per_px", 1.0)))
        self.points_px = np.asarray(
            [world_to_pixel(self.track, x, y, self.transform)
             for x, y in self.centerline], dtype=np.float64)
        # 起点变了，旧弯心索引失效
        self.anchors = []
        self.next_label = 1
        self.track["corners"] = []
        self.track["elements"] = []
        self.start_mode = None
        self.pending_start = None
        self._redraw()
        messagebox.showinfo(
            "起点已设置",
            "起点和行驶方向已更新；方向：%s。\n"
            "之前的弯心标注已清空，请从 T1 重新标注。" %
            ("反向" if reverse else "正向"))

    def _undo(self):
        if self.anchors:
            self.anchors.pop()
            self.next_label = max(1, self.next_label - 1)
            self._redraw()

    def _clear(self):
        if self.anchors and not messagebox.askyesno("清空", "清空所有弯心标注？"):
            return
        self.anchors = []
        self.next_label = 1
        self._redraw()

    def _quit(self):
        self.root.destroy()

    def save(self):
        if len(self.anchors) == 1:
            raise ValueError("只标了 1 个弯心；请补到至少 2 个，或清空后再保存起点")
        try:
            post_count = max(0, min(24, int(self.post_count_var.get())))
        except ValueError:
            raise ValueError("柱子数量必须是 0~24 的整数")
        self.track.setdefault("reference", {})["corner_post_count"] = post_count
        if len(self.anchors) >= 2:
            anchors = {label: index for label, index in self.anchors}
            corners, elements = bt._build_corner_elements(
                self.centerline, anchors)
            self.track["corners"] = corners
            self.track["elements"] = elements
            self.track.setdefault("reference", {})["corner_labels"] = len(anchors)
        elif len(self.anchors) == 0:
            # 只改起点/方向/柱子数量时，保留已存在的弯道数据
            if "corners" not in self.track:
                self.track["corners"] = []
            if "elements" not in self.track:
                self.track["elements"] = []
        folder = os.path.dirname(os.path.abspath(self.out_path))
        if folder:
            os.makedirs(folder, exist_ok=True)
        with open(self.out_path, "w", encoding="utf-8") as handle:
            json.dump(self.track, handle, ensure_ascii=False, indent=1)
            handle.write("\n")
        self.status.configure(text="已保存：%s（%d 个弯）" % (
            self.out_path, len(self.anchors)))
        return self.out_path

    def _save(self):
        try:
            path = self.save()
        except (ValueError, IOError, OSError) as exc:
            messagebox.showerror("保存失败", str(exc))
            return
        messagebox.showinfo("已保存", "赛道数据已写入：\n%s\n\n重新进入地图即可看到 5 要素窗口/柱子数量。"
                            % path)

    def run(self):
        self.root.mainloop()


def annotate_from_pixels(image_path, track_path, out_path, pixels,
                         start_label=1):
    """无 GUI 测试/批量：pixels 是原始图片像素坐标 [(x,y), ...]。"""
    with open(track_path, "r", encoding="utf-8") as handle:
        track = json.load(handle)
    transform = _reference_transform(track)
    if transform is None:
        raise ValueError("缺少 reference.start_pixel / scale_m_per_px")
    centerline = np.asarray(track["centerline"], dtype=np.float64)
    points_px = np.asarray(
        [world_to_pixel(track, x, y, transform) for x, y in centerline],
        dtype=np.float64)
    anchors = []
    for offset, (px, py) in enumerate(pixels):
        distances = ((points_px[:, 0] - px) ** 2
                     + (points_px[:, 1] - py) ** 2)
        index = int(np.argmin(distances))
        if math.sqrt(float(distances[index])) > 35.0:
            raise ValueError("标注点 %d 离中心线太远：(%s,%s)" % (
                offset + 1, px, py))
        anchors.append((start_label + offset, index))
    if len(anchors) < 2:
        raise ValueError("至少需要 2 个弯心")
    corners, elements = bt._build_corner_elements(
        centerline, {label: index for label, index in anchors})
    track["corners"] = corners
    track["elements"] = elements
    track.setdefault("reference", {})["corner_labels"] = len(anchors)
    with open(out_path, "w", encoding="utf-8") as handle:
        json.dump(track, handle, ensure_ascii=False, indent=1)
        handle.write("\n")
    return out_path, corners, elements


def main():
    parser = argparse.ArgumentParser(description="半自动弯道标注")
    parser.add_argument("--image", default=DEFAULT_IMAGE)
    parser.add_argument("--track", default=DEFAULT_TRACK)
    parser.add_argument("--out", default=None,
                        help="默认写回 --track；可指定副本路径")
    parser.add_argument("--start-label", type=int, default=1)
    parser.add_argument("--pixels", default=None,
                        help="无 GUI 测试：'x,y;x,y;...' 原始图片像素点")
    args = parser.parse_args()
    out = args.out or args.track
    if args.pixels:
        pixels = []
        for pair in args.pixels.split(";"):
            pair = pair.strip()
            if not pair:
                continue
            x, y = pair.split(",")
            pixels.append((float(x), float(y)))
        path, corners, elements = annotate_from_pixels(
            args.image, args.track, out, pixels, args.start_label)
        print("已写出：%s" % path)
        for corner in corners:
            print("T%d apex=%d start=%d end=%d dir=%d" % (
                corner["label"], corner["apex"], corner["start"],
                corner["end"], corner["direction"]))
        print("elements=%d" % len(elements))
        return 0
    Annotator(args.image, args.track, out,
              start_label=args.start_label).run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
