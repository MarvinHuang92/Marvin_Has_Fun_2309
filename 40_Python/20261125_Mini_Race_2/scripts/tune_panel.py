# -*- coding: utf-8 -*-
"""Mini Race 2 调参控制台（tkinter）。

- 左侧编辑 ``cfg/sim.json`` 里所有**与性能相关**的参数
  （vehicle / tires / drivetrain / engine / aero / brakes / controls）；
  window / render / scale / audio / version 不在这里改；世界尺寸可以改。
- 右侧显示性能报告（加速、制动、抓地、转弯半径、发动机制动、传动）。
- 「运行性能测试」用**当前面板参数**跑一组固定用例（不保存、不改动文件）。
- 「保存参数」写回 ``cfg/sim.json``；关闭窗口时弹窗问是否保存。
- 「保存报告」把最近一次报告写到 ``data/benchmark_*.txt``。

跑法::

    python scripts/tune_panel.py
    （或双击 02_Tune.bat）
"""
import copy
import json
import os
import sys
import time
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(PROJECT_DIR, "scripts"))

from minirace.benchmark import run_all          # noqa: E402
from minirace.config import config_path, load_config  # noqa: E402
from minirace.presets import (PRESET_SLOTS, apply as apply_preset, load_custom,
                              load_preset, save_custom, slot_by_key,
                              vehicles_dir)  # noqa: E402
from minirace.sim import Simulation            # noqa: E402
SECTION_TITLES = {
    "world": "世界尺寸",
    "vehicle": "整车与几何",
    "tires": "轮胎",
    "drivetrain": "传动 / 自动挡",
    "engine": "发动机",
    "aero": "空气阻力与滚阻",
    "brakes": "制动",
    "controls": "驾驶输入（手感）",
}

# (section, key, label, kind)  kind: float / int / list / curve
FIELD_SPECS = [
    ("world", "width_m", "世界宽度", "float", "m"),
    ("world", "height_m", "世界高度", "float", "m"),

    ("vehicle", "step_hz", "物理步长", "int", "Hz"),
    ("vehicle", "max_substeps", "单帧最多补算步数", "int", ""),
    ("vehicle", "mass", "整车质量", "float", "kg"),
    ("vehicle", "inertia", "横摆转动惯量", "float", "kg·m²"),
    ("vehicle", "wheelbase", "轴距", "float", "m"),
    ("vehicle", "front_weight_fraction", "静态前轴荷比例", "float", "0~1"),
    ("vehicle", "cg_height", "质心高度", "float", "m"),
    ("vehicle", "wheel_radius", "车轮半径", "float", "m"),
    ("vehicle", "max_steer_deg", "最大前轮转角", "float", "deg"),
    ("vehicle", "half_width", "车身半宽", "float", "m"),
    ("vehicle", "half_length", "车身半长", "float", "m"),
    ("vehicle", "shift_max_speed", "允许换 D/R 的最高速度", "float", "m/s"),
    ("vehicle", "stop_speed", "静止判定阈值", "float", "m/s"),

    ("tires", "friction", "附着系数", "float", ""),
    ("tires", "cornering_stiffness", "侧偏刚度系数", "float", "/Fz"),
    ("tires", "tire_shape", "魔术公式形状 C", "float", ""),
    ("tires", "front_stiffness_scale", "前轴侧偏刚度倍率", "float", ""),
    ("tires", "rear_stiffness_scale", "后轴侧偏刚度倍率", "float", ""),
    ("tires", "load_sensitivity", "载荷敏感性", "float", ""),
    ("tires", "front_friction_scale", "前轴附着倍率", "float", ""),
    ("tires", "rear_friction_scale", "后轴附着倍率", "float", ""),
    ("tires", "low_speed_fade", "低速轮胎力淡入速度", "float", "m/s"),
    ("tires", "scrub_speed", "低速蹭地阻尼生效速度", "float", "m/s"),
    ("tires", "scrub_yaw_damping", "低速横摆阻尼", "float", "1/s"),
    ("tires", "scrub_lateral_damping", "低速侧向阻尼", "float", "1/s"),

    ("drivetrain", "drive_split_front", "前轴驱动占比", "float", "0~1"),
    ("drivetrain", "final_drive", "主减速比", "float", ""),
    ("drivetrain", "gear_ratios", "前进挡齿比", "list", "逗号分隔"),
    ("drivetrain", "reverse_ratio", "倒挡齿比", "float", ""),
    ("drivetrain", "efficiency", "传动效率", "float", ""),
    ("drivetrain", "idle_rpm", "怠速转速", "float", "rpm"),
    ("drivetrain", "redline_rpm", "红线转速", "float", "rpm"),
    ("drivetrain", "launch_rpm", "起步打滑目标转速", "float", "rpm"),
    ("drivetrain", "shift_up_rpm", "升挡转速", "float", "rpm"),
    ("drivetrain", "shift_down_rpm", "降挡转速", "float", "rpm"),
    ("drivetrain", "kickdown_rpm", "Kickdown 转速", "float", "rpm"),
    ("drivetrain", "shift_time", "换挡断油时间", "float", "s"),
    ("drivetrain", "shift_interval", "换挡最小间隔", "float", "s"),

    ("engine", "torque_curve", "扭矩曲线 (rpm, N·m)", "curve", "每行一个点"),
    ("engine", "friction_base", "内摩擦基值", "float", "N·m"),
    ("engine", "friction_per_rpm", "内摩擦随转速", "float", "N·m/rpm"),

    ("aero", "drag_coefficient", "空气阻力系数", "float", "N/(m/s)²"),
    ("aero", "rolling_resistance", "滚动阻力系数", "float", ""),

    ("brakes", "decel_limit", "制动目标减速度", "float", "m/s²"),
    ("brakes", "front_bias", "前轴制动力占比", "float", ""),

    ("controls", "sensitivity_throttle", "油门灵敏度", "float", "1/s"),
    ("controls", "sensitivity_brake", "刹车灵敏度", "float", "1/s"),
    ("controls", "sensitivity_steer", "转向灵敏度", "float", "1/s"),
    ("controls", "spring_back", "松开回弹倍率", "float", ""),
    ("controls", "throttle_limit", "油门上限", "float", ""),
    ("controls", "brake_limit", "刹车上限", "float", ""),
    ("controls", "steer_dead_zone", "方向盘中心虚位", "float", ""),
]


PRESET_CHOICES = ["1. 买菜车", "2. 性能车", "3. 超跑", "4. 自定义"]
CUSTOM_LABEL = PRESET_CHOICES[3]


def _fmt_value(kind, value):
    if kind == "int":
        return str(int(value))
    if kind == "list":
        return ", ".join("%g" % float(item) for item in value)
    if kind == "curve":
        return "\n".join("%g, %g" % (float(pair[0]), float(pair[1]))
                         for pair in value)
    return ("%.6g" % float(value))


def _parse_value(kind, raw):
    text = raw.strip()
    if kind == "int":
        return int(float(text))
    if kind == "list":
        text = text.replace("，", ",").replace(";", ",")
        items = [float(piece) for piece in text.split(",") if piece.strip()]
        if not items:
            raise ValueError("列表不能为空")
        return items
    return float(text)


def _parse_curve(raw):
    points = []
    for line_no, line in enumerate(raw.splitlines(), start=1):
        text = line.strip()
        if not text or text.startswith("#"):
            continue
        text = text.replace("，", ",").replace("：", ",").replace(":", ",")
        pieces = text.replace(",", " ").split()
        if len(pieces) < 2:
            raise ValueError("扭矩曲线第 %d 行格式应为 'rpm, N·m'" % line_no)
        points.append([float(pieces[0]), float(pieces[1])])
    if len(points) < 2:
        raise ValueError("扭矩曲线至少需要 2 个点")
    return points


def _system_scale():
    """Windows 系统缩放因子（96 DPI = 1.0）；其他平台返回 1.0。"""
    try:
        import ctypes
        dpi = ctypes.windll.user32.GetDpiForSystem()
        if dpi and dpi > 0:
            return dpi / 96.0
    except Exception:
        pass
    return 1.0


class TunerApp(object):
    def __init__(self, root, project_dir=PROJECT_DIR):
        self.root = root
        self.project_dir = project_dir
        self.config_file = config_path(project_dir)
        self.base_config = load_config(project_dir)
        self.ui_scale = _system_scale()
        try:
            # 让 tk 的字体按系统 DPI 缩放（点值 -> 像素）
            self.root.tk.call("tk", "scaling", self.ui_scale * 96.0 / 72.0)
        except tk.TclError:
            pass
        self.vars = {}
        self.curve_widgets = {}
        self.dirty = False
        self.preset_key = str(self.base_config.get("vehicle_preset", "grocery"))
        if slot_by_key(self.preset_key) is None:
            self.preset_key = "custom"
        self.last_report = None
        self.last_report_time = None
        self._loading = False

        self.root.title("Mini Race 2 调参控制台")
        self.root.minsize(int(1120 * self.ui_scale), int(700 * self.ui_scale))
        self._build_ui()
        self._load_values()
        self._fit_window()
        self._show_report("点击「运行性能测试」生成报告。\n\n"
                          "左侧改完参数后点「运行性能测试」即可看到新的加速/制动/"
                          "抓地/转弯半径等结果；满意后点「保存参数」写回 cfg/sim.json。")
        self.root.after(250, self.run_benchmark)
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)

    def _fit_window(self):
        """把窗口放到屏幕内并居中（按系统缩放，小屏也放得下）。"""
        screen_w = self.root.winfo_screenwidth()
        screen_h = self.root.winfo_screenheight()
        scale = self.ui_scale
        width = min(int(1460 * scale), screen_w - 80)
        height = min(int(920 * scale), screen_h - 120)
        x = max(10, (screen_w - width) // 2)
        y = max(10, (screen_h - height) // 2 - 30)
        self.root.geometry("%dx%d+%d+%d" % (width, height, x, y))

    # ------------------------------------------------------------------ UI
    def _build_ui(self):
        header = ttk.Frame(self.root)
        header.pack(fill=tk.X, padx=10, pady=(8, 2))
        ttk.Label(header, text="配置文件：%s" % self.config_file,
                  font=("Consolas", 10)).pack(side=tk.LEFT)
        self.dirty_label = ttk.Label(header, text="", foreground="#b06000")
        self.dirty_label.pack(side=tk.LEFT, padx=12)
        ttk.Label(header, foreground="#666",
                  text="（只显示性能/世界参数；window/render/scale/audio/version 不在此编辑）"
                  ).pack(side=tk.RIGHT)

        preset_bar = ttk.Frame(self.root)
        preset_bar.pack(fill=tk.X, padx=10, pady=(2, 4))
        ttk.Label(preset_bar, text="车辆预设：",
                  font=("Consolas", 10, "bold")).pack(side=tk.LEFT)
        self.preset_var = tk.StringVar(value=self._preset_label())
        self.preset_combo = ttk.Combobox(preset_bar, textvariable=self.preset_var,
                                         state="readonly", width=16,
                                         values=PRESET_CHOICES)
        self.preset_combo.pack(side=tk.LEFT, padx=(4, 8))
        self.preset_combo.bind("<<ComboboxSelected>>", self._on_preset_selected)
        ttk.Button(preset_bar, text="保存自定义…",
                   command=self.save_custom_dialog).pack(side=tk.LEFT, padx=3)
        ttk.Button(preset_bar, text="加载自定义…",
                   command=self.load_custom_dialog).pack(side=tk.LEFT, padx=3)
        ttk.Label(preset_bar, foreground="#666",
                  text="预设 1-3 不可在 GUI 修改；手动改任一性能参数会自动切到 4 自定义"
                  ).pack(side=tk.RIGHT)

        paned = ttk.Panedwindow(self.root, orient=tk.HORIZONTAL)
        paned.pack(fill=tk.BOTH, expand=True, padx=10, pady=4)

        # ---- 左：参数编辑（可滚动）
        left = ttk.Frame(paned)
        paned.add(left, weight=3)
        self.canvas = tk.Canvas(left, highlightthickness=0)
        scrollbar = ttk.Scrollbar(left, orient=tk.VERTICAL, command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        inner = ttk.Frame(self.canvas)
        inner.bind("<Configure>",
                   lambda event: self.canvas.configure(
                       scrollregion=self.canvas.bbox("all")))
        window_id = self.canvas.create_window((0, 0), window=inner, anchor="nw")
        self.canvas.bind("<Configure>",
                         lambda event: self.canvas.itemconfigure(
                             window_id, width=event.width))
        for widget in (self.canvas, inner):
            widget.bind("<MouseWheel>", self._on_mousewheel)

        by_section = {}
        for section, key, label, kind, unit in FIELD_SPECS:
            by_section.setdefault(section, []).append((key, label, kind, unit))
        for section, items in by_section.items():
            frame = ttk.LabelFrame(inner, text=SECTION_TITLES.get(section, section))
            frame.pack(fill=tk.X, padx=4, pady=4)
            for row, (key, label, kind, unit) in enumerate(items):
                ttk.Label(frame, text=label, width=24).grid(
                    row=row, column=0, sticky="w", padx=(6, 4), pady=2)
                if kind == "curve":
                    text = tk.Text(frame, width=30, height=9, font=("Consolas", 9))
                    text.grid(row=row, column=1, sticky="we", padx=4, pady=2)
                    text.bind("<KeyRelease>", lambda event: self._mark_dirty())
                    self.curve_widgets[(section, key)] = text
                else:
                    var = tk.StringVar()
                    var.trace_add("write", self._on_var_changed)
                    self.vars[(section, key)] = var
                    width = 34 if kind == "list" else 16
                    entry = ttk.Entry(frame, textvariable=var, width=width,
                                      font=("Consolas", 10))
                    entry.grid(row=row, column=1, sticky="w", padx=4, pady=2)
                ttk.Label(frame, text=unit, foreground="#777").grid(
                    row=row, column=2, sticky="w", padx=(2, 8))
            frame.bind("<MouseWheel>", self._on_mousewheel)

        # ---- 右：性能报告
        right = ttk.Frame(paned)
        paned.add(right, weight=4)
        top = ttk.Frame(right)
        top.pack(fill=tk.X)
        ttk.Label(top, text="性能报告（使用左侧当前参数，不保存）",
                  font=("Consolas", 10, "bold")).pack(side=tk.LEFT)
        self.report_info = ttk.Label(top, text="", foreground="#666")
        self.report_info.pack(side=tk.RIGHT)
        self.report_text = tk.Text(right, wrap="word", font=("Consolas", 10),
                                   state=tk.DISABLED, bg="#11141a", fg="#e8ecf2",
                                   insertbackground="#e8ecf2")
        report_scroll = ttk.Scrollbar(right, orient=tk.VERTICAL,
                                      command=self.report_text.yview)
        self.report_text.configure(yscrollcommand=report_scroll.set)
        report_scroll.pack(side=tk.RIGHT, fill=tk.Y)
        self.report_text.pack(fill=tk.BOTH, expand=True, pady=(4, 0))

        # ---- 底部按钮
        bar = ttk.Frame(self.root)
        bar.pack(fill=tk.X, padx=10, pady=8)
        ttk.Button(bar, text="重新加载 cfg",
                   command=self.reload_config).pack(side=tk.LEFT)
        ttk.Button(bar, text="运行性能测试",
                   command=self.run_benchmark).pack(side=tk.LEFT, padx=6)
        ttk.Button(bar, text="保存参数",
                   command=self.save_config).pack(side=tk.LEFT)
        ttk.Button(bar, text="保存报告",
                   command=self.save_report).pack(side=tk.LEFT, padx=6)
        ttk.Button(bar, text="退出",
                   command=self.on_close).pack(side=tk.LEFT)
        self.status_var = tk.StringVar(value="就绪：改参数 -> 运行性能测试 -> 满意后保存")
        ttk.Label(bar, textvariable=self.status_var,
                  foreground="#555").pack(side=tk.RIGHT)

    def _on_mousewheel(self, event):
        delta = -1 if event.delta > 0 else 1
        self.canvas.yview_scroll(delta * 3, "units")

    def _on_var_changed(self, *_args):
        if not self._loading:
            self._mark_dirty()

    def _preset_label(self):
        found = slot_by_key(self.preset_key)
        if found is None:
            return CUSTOM_LABEL
        return "%d. %s" % (found[0], found[1])

    def _set_preset_custom(self):
        self.preset_key = "custom"
        if hasattr(self, "preset_var"):
            self.preset_var.set(CUSTOM_LABEL)

    def _on_preset_selected(self, _event=None):
        value = self.preset_var.get()
        if value == CUSTOM_LABEL:
            self.preset_key = "custom"
            return
        try:
            slot = int(value.split(".")[0])
        except (ValueError, IndexError):
            self.preset_var.set(self._preset_label())
            return
        if self.dirty and not messagebox.askyesno(
                "切换预设", "会丢弃当前未保存的修改，继续？", parent=self.root):
            self.preset_var.set(self._preset_label())
            return
        try:
            values = load_preset(self.project_dir, slot)
        except (IOError, OSError, ValueError) as exc:
            messagebox.showerror("加载预设失败", str(exc), parent=self.root)
            self.preset_var.set(self._preset_label())
            return
        slot_info = None
        for number, name, key, _filename in PRESET_SLOTS:
            if number == slot:
                slot_info = (number, name, key)
                break
        if slot_info is None:
            return
        self.base_config = apply_preset(self.base_config, values)
        self._loading = True
        try:
            self._load_values()
        finally:
            self._loading = False
        self.preset_key = slot_info[2]
        self.preset_var.set(self._preset_label())
        self.dirty = True
        self.dirty_label.configure(text="● 已载入预设，点「保存参数」生效")
        self.status_var.set("已载入预设 %d. %s（保存后写入 cfg/sim.json）"
                            % (slot_info[0], slot_info[1]))

    def save_custom_dialog(self):
        try:
            config = self._collect_config()
            self._validate(config)
        except ValueError as exc:
            messagebox.showerror("参数错误", str(exc), parent=self.root)
            return
        folder = vehicles_dir(self.project_dir)
        try:
            if not os.path.isdir(folder):
                os.makedirs(folder)
        except OSError:
            folder = self.project_dir
        path = filedialog.asksaveasfilename(
            parent=self.root, title="保存自定义车辆参数",
            initialdir=folder, initialfile="custom_vehicle.json",
            defaultextension=".json",
            filetypes=[("车辆参数 JSON", "*.json"), ("所有文件", "*.*")])
        if not path:
            return
        try:
            save_custom(path, config)
        except (IOError, OSError, ValueError) as exc:
            messagebox.showerror("保存失败", str(exc), parent=self.root)
            return
        self._set_preset_custom()
        self.status_var.set("自定义参数已保存：%s" % path)

    def load_custom_dialog(self):
        folder = vehicles_dir(self.project_dir)
        path = filedialog.askopenfilename(
            parent=self.root, title="加载自定义车辆参数",
            initialdir=folder if os.path.isdir(folder) else self.project_dir,
            filetypes=[("车辆参数 JSON", "*.json"), ("所有文件", "*.*")])
        if not path:
            return
        if self.dirty and not messagebox.askyesno(
                "加载自定义", "会丢弃当前未保存的修改，继续？", parent=self.root):
            return
        try:
            values = load_custom(path)
        except (IOError, OSError, ValueError) as exc:
            messagebox.showerror("加载失败", str(exc), parent=self.root)
            return
        self.base_config = apply_preset(self.base_config, values)
        self._loading = True
        try:
            self._load_values()
        finally:
            self._loading = False
        self._set_preset_custom()
        self.dirty = True
        self.dirty_label.configure(text="● 已加载自定义，点「保存参数」生效")
        self.status_var.set("已加载自定义参数：%s" % path)

    def _mark_dirty(self):
        if not self._loading and self.preset_key != "custom":
            self._set_preset_custom()
        self.dirty = True
        self.dirty_label.configure(text="● 有未保存修改（4 自定义）")

    def _set_clean(self):
        self.dirty = False
        self.dirty_label.configure(text="")

    # ------------------------------------------------------------------ 数据
    def _load_values(self):
        self._loading = True
        try:
            for (section, key), var in self.vars.items():
                kind = self._kind_of(section, key)
                value = self.base_config.get(section, {}).get(key)
                var.set(_fmt_value(kind, value))
            for (section, key), widget in self.curve_widgets.items():
                value = self.base_config.get(section, {}).get(key)
                widget.delete("1.0", tk.END)
                widget.insert("1.0", _fmt_value("curve", value))
        finally:
            self._loading = False
        self._set_clean()

    @staticmethod
    def _kind_of(section, key):
        for sec, spec_key, _label, kind, _unit in FIELD_SPECS:
            if sec == section and spec_key == key:
                return kind
        return "float"

    def _collect_config(self):
        """把面板上的值收集成完整 config（保留 window/render/... 不变）。"""
        config = copy.deepcopy(self.base_config)
        for section, key, label, kind, _unit in FIELD_SPECS:
            if kind == "curve":
                raw = self.curve_widgets[(section, key)].get("1.0", tk.END)
                value = _parse_curve(raw)
            else:
                raw = self.vars[(section, key)].get()
                try:
                    value = _parse_value(kind, raw)
                except ValueError:
                    raise ValueError("%s：无法解析“%s”" % (label, raw))
            config.setdefault(section, {})[key] = value
        config["vehicle_preset"] = self.preset_key
        return config

    def _validate(self, config):
        Simulation(config)  # 抛 ValueError 说明参数不自洽（含世界尺寸）

    # ------------------------------------------------------------------ 动作
    def run_benchmark(self):
        try:
            config = self._collect_config()
            self._validate(config)
        except ValueError as exc:
            messagebox.showerror("参数错误", str(exc), parent=self.root)
            return
        self.status_var.set("正在运行性能测试…")
        self.report_info.configure(text="")
        self.root.config(cursor="watch")
        self.root.update_idletasks()
        start = time.time()
        try:
            report = run_all(config)
        except Exception as exc:  # 防止某个极端参数把控制台弄崩
            self.root.config(cursor="")
            messagebox.showerror("测试失败", repr(exc), parent=self.root)
            self.status_var.set("测试失败")
            return
        elapsed = time.time() - start
        self.root.config(cursor="")
        self.last_report = report
        self.last_report_time = time.strftime("%Y%m%d_%H%M%S")
        self._show_report(report.as_text())
        self.report_info.configure(text="耗时 %.2f s" % elapsed)
        self.status_var.set("测试完成：%d 个用例，耗时 %.2f s" % (
            len(report.sections), elapsed))

    def _show_report(self, text):
        self.report_text.configure(state=tk.NORMAL)
        self.report_text.delete("1.0", tk.END)
        self.report_text.insert("1.0", text)
        self.report_text.configure(state=tk.DISABLED)

    def save_config(self):
        try:
            config = self._collect_config()
            self._validate(config)
        except ValueError as exc:
            messagebox.showerror("参数错误", str(exc), parent=self.root)
            return False
        try:
            text = json.dumps(config, ensure_ascii=False, indent=2) + "\n"
            with open(self.config_file, "w", encoding="utf-8") as fh:
                fh.write(text)
        except OSError as exc:
            messagebox.showerror("保存失败", str(exc), parent=self.root)
            return False
        self.base_config = config
        self._set_clean()
        self.status_var.set("已保存：%s" % self.config_file)
        return True

    def reload_config(self):
        if self.dirty:
            if not messagebox.askyesno(
                    "重新加载", "会丢弃当前未保存的修改，继续？", parent=self.root):
                return
        self.base_config = load_config(self.project_dir)
        self.preset_key = str(self.base_config.get("vehicle_preset", "grocery"))
        if slot_by_key(self.preset_key) is None:
            self.preset_key = "custom"
        if hasattr(self, "preset_var"):
            self.preset_var.set(self._preset_label())
        self._loading = True
        try:
            self._load_values()
        finally:
            self._loading = False
        self._set_clean()
        self.status_var.set("已从 cfg/sim.json 重新加载")

    def save_report(self):
        if self.last_report is None:
            messagebox.showinfo("保存报告", "还没有报告，请先运行性能测试。",
                                parent=self.root)
            return
        folder = os.path.join(self.project_dir, "data")
        try:
            if not os.path.isdir(folder):
                os.makedirs(folder)
            name = "benchmark_%s.txt" % (self.last_report_time or
                                         time.strftime("%Y%m%d_%H%M%S"))
            path = os.path.join(folder, name)
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(self.last_report.as_text())
        except OSError as exc:
            messagebox.showerror("保存失败", str(exc), parent=self.root)
            return
        self.status_var.set("报告已保存：%s" % path)

    def on_close(self):
        answer = messagebox.askyesnocancel(
            "退出",
            "是否保存对 cfg/sim.json 的修改？\n\n"
            "是 = 保存并退出\n否 = 直接退出\n取消 = 回到控制台",
            parent=self.root)
        if answer is None:
            return
        if answer:
            if self.save_config():
                self.root.destroy()
            return
        self.root.destroy()


def _enable_dpi():
    """让 tkinter 使用物理像素，避免 150% 缩放时窗口被放大到屏幕外。"""
    try:
        import ctypes
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        try:
            import ctypes
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass


def main():
    _enable_dpi()
    root = tk.Tk()
    try:
        ttk.Style().theme_use("vista")
    except tk.TclError:
        pass
    TunerApp(root)
    root.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
