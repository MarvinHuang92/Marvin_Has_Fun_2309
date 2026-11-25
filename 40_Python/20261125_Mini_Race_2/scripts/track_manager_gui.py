# -*- coding: utf-8 -*-
"""06 · 赛道候选管理器（tkinter）。

功能：
- 启用/禁用赛道（只影响 F2 候选，不删除固定赛道文件）；
- 随机赛道可删除（同时从 maps.list 和磁盘删除）；
- 显示长度/宽度/弯数/最长直道/状态；
- 按编号、名称、长度、宽度、弯数、最长直道排序；
- 设置为“下次启动”的起点（保存到主 cfg/sim.json 的 maps.startup）；
- 显示随机赛道的生成器版本与种子文件名；
- 输入参数生成随机赛道并加入候选列表；删除赛道保留种子文件。

管理器自己的状态保存在 cfg/track_manager.json；
下一局起点保存在主配置 cfg/sim.json，避免存两份。
"""
import copy
import json
import math
import os
import sys
import time
import tkinter as tk
from tkinter import messagebox, ttk

PROJECT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(PROJECT, "scripts"))

import build_random_track as generator  # noqa: E402
import track_manager as tm  # noqa: E402

FIELDS = [
    ("seed", "Seed", "20261126"),
    ("count", "Count", "1"),
    ("lap_min", "Lap min (m)", "1200"),
    ("lap_max", "Lap max (m)", "1800"),
    ("width_min", "Width min (m)", "15"),
    ("width_max", "Width max (m)", "25"),
    ("corner_min", "Corners min", "8"),
    ("corner_max", "Corners max", "12"),
    ("min_straight", "Min straight (m)", "12"),
    ("min_longest", "Min longest (m)", "0"),
    ("max_straight", "Max straight (m, 0=off)", "300"),
    ("hairpin_min", "Hairpins min (0=off)", "1"),
    ("hairpin_curv", "Hairpin curvature", "0.12"),
    ("diff_limit", "|L-R| max (none/0/N)", "none"),
]


def _read_json(path):
    try:
        with open(path, "r", encoding="utf-8") as handle:
            return json.load(handle)
    except (IOError, OSError, ValueError, TypeError):
        return {}


def _track_stats(project, map_def):
    path = map_def.get("file", "")
    if path and not os.path.isabs(path):
        path = os.path.join(project, path)
    data = _read_json(path)
    ref = data.get("reference", {}) or {}
    corners = data.get("corners", []) or []
    generator_version = (
        (ref.get("generator", {}) or {}).get("version") or "N.A")
    if not tm.is_random_map(map_def):
        generator_version = "N.A"
    seed_file = (map_def.get("seed_file", "")
                 if tm.is_random_map(map_def) else "")
    return {
        "kind": data.get("kind", "?"),
        "length_m": ref.get("lap_length_m"),
        "width_m": data.get("width_m", ref.get("width_m")),
        "corners": len(corners),
        "max_straight_m": ref.get("max_straight_m"),
        "generator_version": generator_version,
        "seed_file": (os.path.basename(seed_file) if seed_file else "N.A"),
    }


def _next_number(maps):
    numbers = []
    for item in maps:
        try:
            numbers.append(int(item.get("number", 0)))
        except (ValueError, TypeError):
            pass
    return (max(numbers) + 1) if numbers else 0


def _unique_id(maps, base):
    existing = {str(item.get("id", "")) for item in maps}
    if base not in existing:
        return base
    index = 2
    while "%s_%d" % (base, index) in existing:
        index += 1
    return "%s_%d" % (base, index)


def generate_random_tracks(project, values, count, seed_start, status=None):
    params = copy.deepcopy(generator.DEFAULTS)
    params.update({
        "lap_length_m": [float(values["lap_min"]), float(values["lap_max"])],
        "width_m": [float(values["width_min"]), float(values["width_max"])],
        "corner_count": [int(values["corner_min"]), int(values["corner_max"])],
        "min_straight_m": float(values["min_straight"]),
        "min_longest_straight_m": float(values["min_longest"]),
        "max_straight_m": float(values["max_straight"]),
        "hairpin_boundary_curvature": float(values["hairpin_curv"]),
        "min_hairpin_count": int(values["hairpin_min"]),
        "max_left_right_diff": (
            None if str(values["diff_limit"]).strip().lower() in ("none", "")
            else int(values["diff_limit"])),
        "max_attempts": int(generator.DEFAULTS["max_attempts"]),
    })
    config = tm.load_main_config(project)
    maps = tm.map_list(config)
    results = []
    seed = int(seed_start)
    for _ in range(int(count)):
        found = None
        seed_start_attempt = seed
        attempts = int(params["max_attempts"])
        for _attempt in range(attempts):
            found = generator._try_seed(seed, params)
            if found is not None:
                break
            seed += 1
        if found is None:
            seed_end_attempt = seed_start_attempt + attempts - 1
            raise RuntimeError(
                "已尝试 %d 次仍未找到合规赛道\n种子范围 %d - %d"
                % (attempts, seed_start_attempt, seed_end_attempt))
        track_id = _unique_id(maps, "random_%d" % seed)
        number = _next_number(maps)
        name = "随机赛道 %02d" % (len(results) + 1)
        display_name = "RANDOM TRACK %02d" % (len(results) + 1)
        filename = "track_%s.json" % track_id
        path = os.path.join(project, "cfg", "tracks", filename)
        found["name"] = name
        found["display_name"] = display_name
        seed_file = tm.create_seed_file(
            project, generator.GENERATOR_VERSION,
            found["reference"]["generator"]["seed"],
            found["reference"]["generator"]["params"],
            track_id, "cfg/tracks/%s" % filename)
        found["reference"]["generator"]["seed_file"] = seed_file
        with open(path, "w", encoding="utf-8") as handle:
            json.dump(found, handle, ensure_ascii=False, indent=1)
            handle.write("\n")
        map_def = {
            "id": track_id,
            "number": number,
            "name": name,
            "display_name": display_name,
            "file": "cfg/tracks/%s" % filename,
            "pixels_per_meter": 6.0,
            "random": True,
            "generator_version": generator.GENERATOR_VERSION,
            "seed_file": seed_file,
        }
        maps.append(map_def)
        results.append(map_def)
        config["maps"]["list"] = maps
        tm.save_main_config(config, project)
        if status is not None:
            status("已生成 %s（seed %d）" % (name, seed))
        seed += 1
    return results


class TrackManagerGUI(object):
    def __init__(self):
        self.manager = tm.load_manager(PROJECT)
        self.config = tm.load_main_config(PROJECT)
        self.root = tk.Tk()
        self.root.title("Mini Race 2 · Track Manager")
        self.root.geometry("1380x860")
        self.values = {}
        self.sort_key = tk.StringVar(
            value=str(self.manager.get("sort_key", "number")))
        self.sort_reverse = tk.BooleanVar(
            value=bool(self.manager.get("sort_reverse", False)))
        self.startup_var = tk.StringVar(value="")
        self._build_ui()
        self.refresh()

    # ------------------------------------------------------------------ UI
    def _build_ui(self):
        top = ttk.Frame(self.root)
        top.pack(fill=tk.X, padx=8, pady=6)
        ttk.Label(top, text="Sort:").pack(side=tk.LEFT)
        ttk.Combobox(top, textvariable=self.sort_key, width=16,
                     state="readonly",
                     values=("number", "name", "length", "width", "corners",
                             "max_straight")).pack(side=tk.LEFT, padx=4)
        ttk.Checkbutton(top, text="Descending",
                        variable=self.sort_reverse, command=self.refresh).pack(
            side=tk.LEFT)
        ttk.Button(top, text="Refresh", command=self.refresh).pack(
            side=tk.LEFT, padx=8)
        ttk.Button(top, text="Close", command=self.root.destroy).pack(
            side=tk.RIGHT)

        columns = ("number", "id", "name", "type", "generator", "seed_file",
                   "length", "width", "corners", "max_straight", "status",
                   "file")
        headings = {
            "number": "#", "id": "ID", "name": "Name", "type": "Type",
            "generator": "Generator", "seed_file": "Seed file",
            "length": "Length m", "width": "Width m", "corners": "Corners",
            "max_straight": "Max straight m", "status": "Status",
            "file": "File",
        }
        frame = ttk.Frame(self.root)
        frame.pack(fill=tk.BOTH, expand=True, padx=8, pady=4)
        self.tree = ttk.Treeview(frame, columns=columns, show="headings",
                                 height=16)
        widths = {"number": 45, "id": 140, "name": 150, "type": 80,
                  "generator": 85, "seed_file": 320, "length": 85,
                  "width": 75, "corners": 65, "max_straight": 120,
                  "status": 85, "file": 220}
        for column in columns:
            self.tree.heading(column, text=headings[column],
                              command=lambda key=column: self.sort_by(key))
            self.tree.column(column, width=widths[column],
                             anchor=tk.CENTER if column not in ("file",) else tk.W)
        scroll = ttk.Scrollbar(frame, orient=tk.VERTICAL,
                               command=self.tree.yview)
        self.tree.configure(yscrollcommand=scroll.set)
        self.tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scroll.pack(side=tk.RIGHT, fill=tk.Y)

        actions = ttk.Frame(self.root)
        actions.pack(fill=tk.X, padx=8, pady=4)
        ttk.Button(actions, text="Enable / Disable",
                   command=self.toggle_selected).pack(side=tk.LEFT)
        ttk.Button(actions, text="Delete Random",
                   command=self.delete_selected).pack(side=tk.LEFT, padx=6)
        ttk.Button(actions, text="Set as Next Start",
                   command=self.set_startup).pack(side=tk.LEFT, padx=6)
        self.startup_label = ttk.Label(actions, text="", foreground="#555")
        self.startup_label.pack(side=tk.LEFT, padx=16)

        gen = ttk.LabelFrame(self.root, text="Generate random track")
        gen.pack(fill=tk.X, padx=8, pady=4)
        for index, (key, label, default) in enumerate(FIELDS):
            row, col = divmod(index, 5)
            ttk.Label(gen, text=label).grid(row=row, column=col * 2,
                                             sticky=tk.W, padx=4, pady=2)
            saved = (self.manager.get("generator", {}) or {}).get(key)
            var = tk.StringVar(value=str(saved if saved is not None else default))
            ttk.Entry(gen, textvariable=var, width=12).grid(
                row=row, column=col * 2 + 1, sticky=tk.W, padx=4)
            self.values[key] = var
        ttk.Button(gen, text="Generate & Add",
                   command=self.generate).grid(row=3, column=8, padx=8,
                                               pady=6, sticky=tk.E)

        self.status = ttk.Label(self.root, text="", foreground="#555")
        self.status.pack(fill=tk.X, padx=8, pady=(0, 6))
        self.tree.bind("<Double-1>", lambda _event: self.toggle_selected())

    def _status(self, text):
        self.status.configure(text=text)
        self.root.update_idletasks()

    # ------------------------------------------------------------------ 数据
    def refresh(self):
        self.config = tm.load_main_config(PROJECT)
        self.manager = tm.load_manager(PROJECT)
        self.maps = tm.map_list(self.config)
        disabled = set(self.manager.get("disabled") or [])
        rows = []
        for map_def in self.maps:
            map_id = str(map_def.get("id", ""))
            stats = _track_stats(PROJECT, map_def)
            rows.append({
                "map": map_def, "stats": stats, "id": map_id,
                "disabled": map_id in disabled,
            })
        key = self.sort_key.get()
        reverse = bool(self.sort_reverse.get())

        def sort_value(row):
            stats = row["stats"]
            if key == "number":
                return int(row["map"].get("number", 0))
            if key == "name":
                return str(row["map"].get("name", ""))
            if key == "length":
                return float(stats["length_m"] or 0.0)
            if key == "width":
                return float(stats["width_m"] or 0.0)
            if key == "corners":
                return int(stats["corners"])
            if key == "max_straight":
                return float(stats["max_straight_m"] or 0.0)
            return str(row["id"])

        rows.sort(key=sort_value, reverse=reverse)
        for item in self.tree.get_children():
            self.tree.delete(item)
        for row in rows:
            map_def = row["map"]
            stats = row["stats"]
            kind = stats["kind"]
            is_random = tm.is_random_map(map_def)
            self.tree.insert("", tk.END, iid=row["id"], values=(
                map_def.get("number", ""), row["id"],
                map_def.get("name", ""),
                ("RANDOM" if is_random else "FIXED"),
                stats["generator_version"],
                stats["seed_file"],
                "" if stats["length_m"] is None else "%.1f" % stats["length_m"],
                "" if stats["width_m"] is None else "%.1f" % stats["width_m"],
                stats["corners"],
                "" if stats["max_straight_m"] is None else "%.1f" % stats["max_straight_m"],
                "DISABLED" if row["disabled"] else "enabled",
                map_def.get("file", ""),
            ))
        startup = (self.config.get("maps", {}) or {}).get("startup")
        self.startup_label.configure(
            text="Next start: %s" % (startup or "(last session / default)"))
        self.manager["sort_key"] = key
        self.manager["sort_reverse"] = reverse
        tm.save_manager(self.manager, PROJECT)
        self._status("%d tracks · %d disabled" % (
            len(rows), len(disabled)))

    def _selected(self):
        selection = self.tree.selection()
        if not selection:
            messagebox.showinfo("Select a track", "先选择一行赛道。")
            return None
        return selection[0]

    # ------------------------------------------------------------------ 操作
    def sort_by(self, key):
        mapping = {"number": "number", "name": "name", "length": "length",
                   "width": "width", "corners": "corners",
                   "max_straight": "max_straight"}
        if key not in mapping:
            return
        self.sort_key.set(mapping[key])
        self.refresh()

    def toggle_selected(self):
        map_id = self._selected()
        if not map_id:
            return
        disabled = set(self.manager.get("disabled") or [])
        if map_id in disabled:
            disabled.remove(map_id)
        else:
            disabled.add(map_id)
            if (self.config.get("maps", {}) or {}).get("startup") == map_id:
                tm.set_startup_id(None, PROJECT)
        self.manager["disabled"] = sorted(disabled)
        tm.save_manager(self.manager, PROJECT)
        self.refresh()

    def delete_selected(self):
        map_id = self._selected()
        if not map_id:
            return
        map_def = next((item for item in self.maps
                        if str(item.get("id", "")) == map_id), None)
        if map_def is None:
            return
        if not tm.is_random_map(map_def):
            messagebox.showwarning("固定赛道", "固定赛道只能禁用，不能删除。")
            return
        if not messagebox.askyesno("Delete random track",
                                   "删除随机赛道 %s 及其 JSON 文件？" % map_id):
            return
        file_path = map_def.get("file", "")
        if file_path and not os.path.isabs(file_path):
            file_path = os.path.join(PROJECT, file_path)
        tm.remove_map(map_id, PROJECT)
        self.manager["disabled"] = [
            item for item in (self.manager.get("disabled") or [])
            if item != map_id]
        tm.save_manager(self.manager, PROJECT)
        try:
            if file_path and os.path.isfile(file_path):
                os.remove(file_path)
        except OSError as exc:
            messagebox.showwarning("文件删除失败", str(exc))
        self.refresh()

    def set_startup(self):
        map_id = self._selected()
        if not map_id:
            return
        if map_id in set(self.manager.get("disabled") or []):
            messagebox.showwarning("赛道已禁用", "请先启用该赛道。")
            return
        tm.set_startup_id(map_id, PROJECT)
        self.refresh()
        self._status("下次启动将使用：%s" % map_id)

    def generate(self):
        try:
            values = {key: self.values[key].get().strip()
                      for key, _label, _default in FIELDS}
            count = int(values["count"])
            seed = int(values["seed"])
            self.manager = tm.load_manager(PROJECT)
            self.manager["generator"] = dict(values)
            tm.save_manager(self.manager, PROJECT)
            self._status("生成中…")
            self.root.config(cursor="watch")
            self.root.update()
            tracks = generate_random_tracks(
                PROJECT, values, count, seed, status=self._status)
        except Exception as exc:  # noqa: BLE001
            messagebox.showerror("生成失败", str(exc))
            self.root.config(cursor="")
            self._status("生成失败")
            return
        self.root.config(cursor="")
        self.refresh()
        self._status("已加入 %d 条随机赛道" % len(tracks))
        messagebox.showinfo("已生成", "已加入 %d 条随机赛道到 F2 候选列表。"
                            % len(tracks))

    def run(self):
        self.root.mainloop()


def main():
    TrackManagerGUI().run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
