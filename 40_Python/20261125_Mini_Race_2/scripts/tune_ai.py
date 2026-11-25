# -*- coding: utf-8 -*-
"""Mini Race 2 AI 调参控制台（tkinter）。

编辑 ``cfg/ai.json`` 中的 AI 驾驶员参数，并测试 AI 闭环 + 算力余量。
不需要 pygame 窗口；AI 物理/决策用 headless Simulation。

跑法::

    python scripts/tune_ai.py
    （或双击 04_TuneAI.bat）
"""
import copy
import json
import os
import sys
import time
import tkinter as tk
from tkinter import messagebox, ttk

PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(PROJECT_DIR, "scripts"))

from minirace.ai import (AI_CONFIG_DEFAULTS, AI_CONFIG_NAME, AIManager,
                        benchmark_ai, load_ai_config, save_ai_config)  # noqa: E402
from minirace.config import load_config  # noqa: E402

FIELDS = [
    ("enabled", "启用 AI", "bool", ""),
    ("count", "AI 数量", "int", "个"),
    ("decision_hz", "决策频率", "float", "Hz"),
    ("spawn_spacing_m", "发车间距", "float", "m"),
    ("lookahead_base_m", "基础前视距离", "float", "m"),
    ("lookahead_time_s", "速度前视时间", "float", "s"),
    ("steering_gain", "转向增益", "float", ""),
    ("steer_slew_rate", "方向盘速率限制", "float", "/s"),
    ("target_lat_accel", "目标横向加速度", "float", "m/s²"),
    ("brake_decel", "规划制动减速度", "float", "m/s²"),
    ("max_speed_mps", "最高目标速度", "float", "m/s"),
    ("throttle_gain", "油门增益", "float", ""),
    ("brake_gain", "刹车增益", "float", ""),
]


class TuneAI(object):
    def __init__(self, root):
        self.root = root
        self.root.title("Mini Race 2 · AI 调参控制台")
        self.root.geometry("1180x760")
        self.project_dir = PROJECT_DIR
        self.config_file = os.path.join(PROJECT_DIR, AI_CONFIG_NAME)
        self.vars = {}
        self.base_config = load_config(PROJECT_DIR)
        self.last_report = ""
        self._build_ui()
        self.reload()

    # ------------------------------------------------------------------ UI
    def _build_ui(self):
        header = ttk.Frame(self.root)
        header.pack(fill=tk.X, padx=10, pady=(8, 3))
        ttk.Label(header, text="AI 配置文件：%s" % self.config_file,
                  font=("Consolas", 10)).pack(side=tk.LEFT)
        ttk.Label(header,
                  text="AI 车辆各自独立 Simulation；AI 之间无碰撞，只碰环境边界",
                  foreground="#666").pack(side=tk.RIGHT)

        body = ttk.Panedwindow(self.root, orient=tk.HORIZONTAL)
        body.pack(fill=tk.BOTH, expand=True, padx=10, pady=4)

        left = ttk.LabelFrame(body, text="规则驾驶员参数")
        body.add(left, weight=2)
        self.var_enabled = tk.BooleanVar(value=True)
        ttk.Checkbutton(left, text="启用 AI（cfg/ai.json）",
                        variable=self.var_enabled).grid(
                            row=0, column=0, columnspan=3, sticky="w",
                            padx=8, pady=(8, 4))
        for row, (key, label, kind, unit) in enumerate(FIELDS[1:], start=1):
            ttk.Label(left, text=label, width=20).grid(
                row=row, column=0, sticky="w", padx=(8, 4), pady=3)
            var = tk.StringVar()
            self.vars[key] = var
            ttk.Entry(left, textvariable=var, width=16,
                      font=("Consolas", 10)).grid(
                          row=row, column=1, sticky="w", padx=4, pady=3)
            ttk.Label(left, text=unit, foreground="#777").grid(
                row=row, column=2, sticky="w", padx=(2, 8))

        ttk.Label(left, text="说明：", font=("Consolas", 10, "bold")).grid(
            row=len(FIELDS) + 1, column=0, sticky="w", padx=8, pady=(12, 2))
        ttk.Label(left, foreground="#555", wraplength=380, justify=tk.LEFT,
                  text=("引擎物理 240 Hz，AI 决策默认 60 Hz。\n"
                        "转向：纯追踪前视点；速度：按曲率限速并提前制动。\n"
                        "数量 > 1 时每辆车都独立决策/独立赛道碰撞。\n"
                        "修改后点“保存参数”，重启游戏生效。")).grid(
                            row=len(FIELDS) + 2, column=0, columnspan=3,
                            sticky="w", padx=8, pady=4)

        right = ttk.Frame(body)
        body.add(right, weight=3)
        top = ttk.Frame(right)
        top.pack(fill=tk.X)
        ttk.Label(top, text="AI 闭环 / 算力报告",
                  font=("Consolas", 10, "bold")).pack(side=tk.LEFT)
        self.report_info = ttk.Label(top, text="", foreground="#666")
        self.report_info.pack(side=tk.RIGHT)
        self.report_text = tk.Text(right, wrap="word", font=("Consolas", 10),
                                   state=tk.DISABLED, bg="#11141a",
                                   fg="#e8ecf2", insertbackground="#e8ecf2")
        scroll = ttk.Scrollbar(right, orient=tk.VERTICAL,
                               command=self.report_text.yview)
        self.report_text.configure(yscrollcommand=scroll.set)
        scroll.pack(side=tk.RIGHT, fill=tk.Y)
        self.report_text.pack(fill=tk.BOTH, expand=True, pady=(4, 0))

        bar = ttk.Frame(self.root)
        bar.pack(fill=tk.X, padx=10, pady=8)
        ttk.Button(bar, text="重新加载", command=self.reload).pack(side=tk.LEFT)
        ttk.Button(bar, text="运行 AI 算力测试",
                   command=self.run_benchmark).pack(side=tk.LEFT, padx=6)
        ttk.Button(bar, text="保存参数", command=self.save).pack(side=tk.LEFT)
        ttk.Button(bar, text="恢复默认",
                   command=self.restore_defaults).pack(side=tk.LEFT, padx=6)

    # ------------------------------------------------------------------ 数据
    def _set_report(self, text):
        self.last_report = text
        self.report_text.configure(state=tk.NORMAL)
        self.report_text.delete("1.0", tk.END)
        self.report_text.insert(tk.END, text)
        self.report_text.configure(state=tk.DISABLED)

    def _parse(self):
        cfg = {}
        cfg["enabled"] = bool(self.var_enabled.get())
        for key, _label, kind, _unit in FIELDS[1:]:
            raw = self.vars[key].get().strip()
            try:
                cfg[key] = int(raw) if kind == "int" else float(raw)
            except ValueError:
                raise ValueError("%s 不是有效数字：%r" % (key, raw))
        cfg["count"] = max(0, min(64, int(cfg["count"])))
        cfg["decision_hz"] = max(5.0, min(240.0, float(cfg["decision_hz"])))
        return cfg

    def reload(self):
        cfg = load_ai_config(PROJECT_DIR)
        self.var_enabled.set(bool(cfg.get("enabled", True)))
        for key, _label, _kind, _unit in FIELDS[1:]:
            self.vars[key].set(("%g" % cfg[key]) if isinstance(cfg[key], float)
                               else str(cfg[key]))
        self.report_info.configure(text="")
        self._set_report("尚未运行测试。\n\n"
                         "点“运行 AI 算力测试”会从上海赛道起点发车，\n"
                         "用当前面板参数跑一段 headless 闭环，并给出\n"
                         "60 fps 下每帧 AI 计算耗时和剩余算力。\n")

    def save(self):
        try:
            cfg = self._parse()
            path = save_ai_config(PROJECT_DIR, cfg)
        except (ValueError, IOError, OSError) as exc:
            messagebox.showerror("保存失败", str(exc))
            return
        self.report_info.configure(text="已保存：%s" % path)
        messagebox.showinfo("已保存", "AI 参数已写入：\n%s\n\n重启游戏后生效。" % path)

    def restore_defaults(self):
        if not messagebox.askyesno("恢复默认", "把左侧全部 AI 参数恢复默认值？"):
            return
        self.var_enabled.set(bool(AI_CONFIG_DEFAULTS["enabled"]))
        for key in self.vars:
            value = AI_CONFIG_DEFAULTS[key]
            self.vars[key].set("%g" % value if isinstance(value, float)
                               else str(value))

    # ------------------------------------------------------------------ 基准
    def _map_index(self, map_id="shanghai"):
        maps = list((self.base_config.get("maps", {}) or {}).get("list", []))
        for index, item in enumerate(maps):
            if item.get("id") == map_id:
                return index
        return min(2, max(0, len(maps) - 1))

    def run_benchmark(self):
        try:
            cfg = self._parse()
        except ValueError as exc:
            messagebox.showerror("参数错误", str(exc))
            return
        count = int(cfg.get("count", 1))
        if count <= 0 or not cfg.get("enabled", True):
            self._set_report("AI 已关闭或数量为 0，无法测试。\n"
                             "把“启用 AI”勾上，并设置数量 >= 1。\n")
            return
        self.root.configure(cursor="watch")
        self.root.update_idletasks()
        started = time.perf_counter()
        try:
            report = benchmark_ai(self.base_config, cfg, PROJECT_DIR,
                                  map_index=self._map_index("shanghai"),
                                  seconds=4.0, fps=60.0)
        except Exception as exc:
            self.root.configure(cursor="")
            messagebox.showerror("测试失败", "%s: %s" % (type(exc).__name__, exc))
            return
        self.root.configure(cursor="")
        elapsed = time.perf_counter() - started
        lines = []
        lines.append("AI 规则驾驶员闭环测试")
        lines.append("地图：上海国际赛车场   模拟 %.1f s   AI 数量：%d"
                     % (report["seconds"], report["ai_count"]))
        lines.append("决策频率：%.0f Hz   物理频率：%.0f Hz"
                     % (cfg["decision_hz"],
                        self.base_config.get("vehicle", {}).get("step_hz", 240)))
        lines.append("")
        lines.append("—— 闭环结果 ——")
        for index, distance in enumerate(report["distance_m"]):
            lines.append("AI %d：行驶 %8.1f m，平均 %5.1f m/s（%5.1f km/h）"
                         % (index + 1, distance,
                            report["avg_speed_mps"][index],
                            report["avg_speed_mps"][index] * 3.6))
        lines.append("")
        lines.append("—— 算力 ——")
        lines.append("实际墙钟耗时：%.3f s（含 Python 启动后的 AI 闭环）" % elapsed)
        lines.append("每帧 AI（物理 + 决策，60 fps 口径）：%.3f ms"
                     % report["ms_per_frame"])
        lines.append("60 fps 单帧预算：%.3f ms" % report["budget_ms"])
        lines.append("AI 单核占用：%.2f%%" % report["core_percent"])
        lines.append("剩余算力：%.3f ms/帧" % report["remaining_ms"])
        lines.append("按单核 50%% 预算：约可支持 %d 个同类 AI"
                     % report["count_at_50_percent"])
        lines.append("按单核 100%% 预算：约可支持 %d 个同类 AI"
                     % report["count_at_100_percent"])
        lines.append("")
        lines.append("注：以上只统计 AI 的物理 + 决策；不含玩家、渲染、音频。")
        self._set_report("\n".join(lines))
        self.report_info.configure(text="测试完成")


def main():
    root = tk.Tk()
    try:
        style = ttk.Style(root)
        if "vista" in style.theme_names():
            style.theme_use("vista")
    except tk.TclError:
        pass
    TuneAI(root)
    root.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
