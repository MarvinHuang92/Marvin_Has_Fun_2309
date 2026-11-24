# -*- coding: utf-8 -*-
"""诊断模式：逐步记录 telemetry + 自动标记异常事件 + 退出时输出摘要。

不 import pygame，可单独用于脚本/测试；GUI 里由 ``--diagnose`` 或 ``F9`` 控制开关。

异常事件（阈值见 ``cfg/sim.json`` 的 ``diagnostics`` 段）：

- ``NAN``：任何数值状态出现 NaN/Inf；
- ``SPEED_JUMP``：``|Δ|vx、vy|| / dt`` 超过 ``jump_accel_threshold``（m/s²）；
- ``HEADING_JUMP``：``|Δheading| / dt`` 超过 ``heading_rate_threshold``（rad/s）；
- ``GEAR_HUNT``：``gear_hunting_window`` 秒内换挡 >= ``gear_hunting_changes`` 次；
- ``WALL_HIT``：撞到赛道/世界边界（每个连续碰撞过程记一次）；
- ``GRIP_SATURATED``：轮胎连续打滑/侧滑（``sliding / wheelspin / lockup`` 或
  ``slip_amount`` 超过阈值）持续超过 ``grip_saturation_time`` 秒（每次记一次）；
- ``YAW_RUNAWAY``：没有转向输入（``|steer|`` 很小）时横摆角速度仍超过阈值并持续
  ``yaw_runaway_time`` 秒（自旋/螺旋的特征）。

输出：

- ``data/diag_YYYYmmdd_HHMMSS.csv``：每步 telemetry，最后一列 ``events`` 是当步事件
  （多个用 ``;`` 分隔，没有则为空）；
- ``data/diag_YYYYmmdd_HHMMSS_summary.txt``：运行摘要（事件统计 + 关键极值 + 最近事件）。
"""
import csv
import logging
import math
import os
import time

from minirace.vehicle import Telemetry

LOG = logging.getLogger(__name__)

EVENT_ORDER = ("NAN", "SPEED_JUMP", "HEADING_JUMP", "GEAR_HUNT",
               "WALL_HIT", "GRIP_SATURATED", "YAW_RUNAWAY")


def _fmt(value):
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, float):
        return "%.4f" % value
    return value


class Diagnostics(object):
    def __init__(self, project_dir, config):
        cfg = (config or {}).get("diagnostics", {}) or {}
        self.project_dir = str(project_dir)
        self.data_dir = os.path.join(self.project_dir, "data")
        self.jump_accel_threshold = float(cfg.get("jump_accel_threshold", 50.0))
        self.heading_rate_threshold = float(cfg.get("heading_rate_threshold", 20.0))
        self.gear_hunting_window = float(cfg.get("gear_hunting_window", 2.0))
        self.gear_hunting_changes = int(cfg.get("gear_hunting_changes", 4))
        self.slip_threshold = float(cfg.get("slip_threshold", 0.5))
        self.grip_saturation_time = float(cfg.get("grip_saturation_time", 1.0))
        self.yaw_runaway_threshold = float(cfg.get("yaw_runaway_threshold", 2.0))
        self.yaw_runaway_steer = float(cfg.get("yaw_runaway_steer", 0.15))
        self.yaw_runaway_time = float(cfg.get("yaw_runaway_time", 0.5))
        self.max_recent_events = int(cfg.get("max_recent_events", 20))

        self.active = False
        self.path = None
        self.summary_path = None
        self._fh = None
        self._writer = None
        self._reset_stats()

    # ------------------------------------------------------------------ 状态
    def _reset_stats(self):
        self.steps = 0
        self._dt = 0.0
        self._t0 = None
        self._t_end = None
        self.events = []            # [(t, name, detail)]
        self.event_counts = dict((name, 0) for name in EVENT_ORDER)
        self._prev = None
        self._prev_t = None
        self._last_jump_time = dict()
        self._gear_changes = []
        self._last_hunt_time = -1e9
        self._wall_episodes = 0
        self._wall_steps = 0
        self._was_wall = False
        self._grip_episode_time = 0.0
        self._grip_episodes = 0
        self._in_grip_episode = False
        self._yaw_runaway_time = 0.0
        self._yaw_runaway_episodes = 0
        self._in_yaw_runaway = False
        self.max_speed = 0.0
        self.max_a_long = 0.0
        self.max_a_lat = 0.0
        self.max_rpm = 0.0
        self.max_grip = 0.0
        self.gear_change_count = 0
        self.slip_steps = 0
        self.wheelspin_steps = 0
        self.lockup_steps = 0

    def start(self):
        """开始记录；返回 csv 路径（失败时返回 None）。"""
        if self.active:
            return self.path
        try:
            if not os.path.isdir(self.data_dir):
                os.makedirs(self.data_dir)
            stamp = time.strftime("%Y%m%d_%H%M%S")
            base = os.path.join(self.data_dir, "diag_%s" % stamp)
            path = base + ".csv"
            index = 1
            while os.path.exists(path):
                path = "%s_%02d.csv" % (base, index)
                index += 1
            self._fh = open(path, "w", newline="", encoding="utf-8")
            self._writer = csv.writer(self._fh)
            self._writer.writerow(["t"] + list(Telemetry.__slots__) + ["events"])
            self.path = path
            self.summary_path = os.path.splitext(path)[0] + "_summary.txt"
            self._reset_stats()
            self.active = True
            LOG.info("诊断模式开始：%s", path)
            return path
        except OSError as exc:
            LOG.warning("诊断模式启动失败：%s", exc)
            self.active = False
            return None

    def stop(self):
        """停止记录并写摘要；返回摘要路径（失败/未开启返回 None）。"""
        if not self.active:
            return None
        self.active = False
        if self._fh is not None:
            try:
                self._fh.close()
            except OSError:
                pass
            self._fh = None
            self._writer = None
        summary = self.build_summary()
        try:
            with open(self.summary_path, "w", encoding="utf-8") as fh:
                fh.write(summary)
            LOG.info("诊断摘要已保存：%s", self.summary_path)
        except OSError as exc:
            LOG.warning("诊断摘要写入失败：%s", exc)
            self.summary_path = None
        LOG.info("诊断模式结束：%d 步，事件 %d 个", self.steps, len(self.events))
        return self.summary_path

    def toggle(self):
        """切换开关，返回 (active, path)。"""
        if self.active:
            return False, self.stop()
        return True, self.start()

    # ------------------------------------------------------------------ 记录
    def step(self, sim):
        if not self.active or sim.telemetry is None:
            return
        telem = sim.telemetry
        t = sim.time
        dt = sim.step_dt
        events = []

        has_nan = self._has_nan(telem)
        if has_nan:
            events.append("NAN")
            self._add_event(t, "NAN", "出现 NaN/Inf")

        if self._t0 is None:
            self._t0 = t
            self._dt = dt
        self._t_end = t

        prev = self._prev
        if prev is not None and not has_nan and not self._has_nan(prev):
            if not telem.wall_hit and not telem.brake_clamped:
                elapsed = max(t - self._prev_t, 1e-9)
                dv = math.hypot(telem.vx - prev.vx, telem.vy - prev.vy) / elapsed
                if dv > self.jump_accel_threshold:
                    events.append("SPEED_JUMP")
                    self._add_event(t, "SPEED_JUMP",
                                    "Δv/dt = %.1f m/s²" % dv)
                dheading = abs(telem.heading - prev.heading) / elapsed
                if dheading > self.heading_rate_threshold:
                    events.append("HEADING_JUMP")
                    self._add_event(t, "HEADING_JUMP",
                                    "Δheading/dt = %.1f rad/s" % dheading)

        # 换挡抖动
        if prev is not None and telem.gear != prev.gear:
            self.gear_change_count += 1
            self._gear_changes.append(t)
            cutoff = t - self.gear_hunting_window
            self._gear_changes = [x for x in self._gear_changes if x >= cutoff]
            if (len(self._gear_changes) >= self.gear_hunting_changes
                    and t - self._last_hunt_time >= self.gear_hunting_window):
                events.append("GEAR_HUNT")
                self._last_hunt_time = t
                self._add_event(t, "GEAR_HUNT",
                                "%d 次换挡/%.1fs（当前挡位 %d）" % (
                                    len(self._gear_changes),
                                    self.gear_hunting_window, telem.gear))

        # 撞世界边界（每次连续碰撞只记一次）
        if telem.wall_hit:
            self._wall_steps += 1
            if not self._was_wall:
                self._wall_episodes += 1
                events.append("WALL_HIT")
                self._add_event(t, "WALL_HIT",
                                "(%.1f, %.1f) m" % (telem.x, telem.y))
            self._was_wall = True
        else:
            self._was_wall = False

        # 长时间抓地饱和/打滑（轮胎已到极限：侧滑、空转或抱死）
        self.max_grip = max(self.max_grip, telem.grip_usage)
        saturated = (telem.sliding or telem.wheelspin or telem.lockup
                     or telem.slip_amount >= self.slip_threshold)
        if saturated:
            self._grip_episode_time += dt
            if (not self._in_grip_episode
                    and self._grip_episode_time >= self.grip_saturation_time):
                events.append("GRIP_SATURATED")
                self._in_grip_episode = True
                self._grip_episodes += 1
                self._add_event(t, "GRIP_SATURATED",
                                "slip=%.2f，持续 %.2f s" % (
                                    telem.slip_amount, self._grip_episode_time))
        else:
            self._grip_episode_time = 0.0
            self._in_grip_episode = False

        # 无转向输入但横摆角速度过大（自旋/螺旋）
        if (abs(telem.yaw_rate) >= self.yaw_runaway_threshold
                and abs(telem.steer) <= self.yaw_runaway_steer):
            self._yaw_runaway_time += dt
            if (not self._in_yaw_runaway
                    and self._yaw_runaway_time >= self.yaw_runaway_time):
                events.append("YAW_RUNAWAY")
                self._in_yaw_runaway = True
                self._yaw_runaway_episodes += 1
                self._add_event(t, "YAW_RUNAWAY",
                                "|yaw|=%.2f rad/s，steer=%.2f，持续 %.2f s" % (
                                    abs(telem.yaw_rate), telem.steer,
                                    self._yaw_runaway_time))
        else:
            self._yaw_runaway_time = 0.0
            self._in_yaw_runaway = False

        # 统计
        self.max_speed = max(self.max_speed, telem.speed_abs)
        self.max_a_long = max(self.max_a_long, abs(telem.a_long))
        self.max_a_lat = max(self.max_a_lat, abs(telem.a_lat))
        self.max_rpm = max(self.max_rpm, telem.rpm)
        if telem.wheelspin:
            self.wheelspin_steps += 1
        if telem.lockup:
            self.lockup_steps += 1
        if telem.sliding or telem.wheelspin or telem.lockup:
            self.slip_steps += 1

        # 写 CSV
        if self._writer is not None:
            try:
                row = [("%.5f" % t)]
                for name in Telemetry.__slots__:
                    row.append(_fmt(getattr(telem, name)))
                row.append(";".join(events))
                self._writer.writerow(row)
            except (OSError, ValueError) as exc:
                LOG.warning("诊断 CSV 写入失败：%s", exc)
                self.active = False

        self.steps += 1
        self._prev = telem
        self._prev_t = t

    # ------------------------------------------------------------------ 内部
    @staticmethod
    def _has_nan(telem):
        for name in Telemetry.__slots__:
            value = getattr(telem, name)
            if isinstance(value, float) and not math.isfinite(value):
                return True
        return False

    def _add_event(self, t, name, detail):
        self.event_counts[name] = self.event_counts.get(name, 0) + 1
        self.events.append((t, name, detail))

    # ------------------------------------------------------------------ 摘要
    def build_summary(self):
        lines = []
        lines.append("Mini Race 2 诊断摘要")
        lines.append("=" * 60)
        lines.append("CSV 文件     : %s" % self.path)
        duration = self.steps * self._dt if self._dt > 0 else 0.0
        hz = (1.0 / self._dt) if self._dt > 0 else 0.0
        lines.append("记录步数     : %d（%.2f s @ %.0f Hz）" % (
            self.steps, duration, hz))
        lines.append("")
        lines.append("== 异常事件统计 ==")
        for name in EVENT_ORDER:
            count = self.event_counts.get(name, 0)
            lines.append("  %-14s : %d" % (name, count))
        lines.append("  WALL_HIT 连续次数：%d（总 %d 步）" % (
            self._wall_episodes, self._wall_steps))
        lines.append("  GRIP_SATURATED 次数：%d" % self._grip_episodes)
        lines.append("  YAW_RUNAWAY 次数    ：%d" % self._yaw_runaway_episodes)
        lines.append("")
        lines.append("== 关键统计 ==")
        lines.append("  最高车速      : %.1f km/h" % (self.max_speed * 3.6))
        lines.append("  最大纵向加速度: %.2f g" % (self.max_a_long / 9.81))
        lines.append("  最大横向加速度: %.2f g" % (self.max_a_lat / 9.81))
        lines.append("  最高转速      : %.0f rpm" % self.max_rpm)
        lines.append("  最大附着利用率: %.3f" % self.max_grip)
        lines.append("  换挡次数      : %d" % self.gear_change_count)
        lines.append("  打滑/滑动步数 : %d（wheelspin %d，lockup %d）" % (
            self.slip_steps, self.wheelspin_steps, self.lockup_steps))
        lines.append("")
        lines.append("== 最近事件（最多 %d 条）==" % self.max_recent_events)
        recent = self.events[-self.max_recent_events:]
        if not recent:
            lines.append("  （无）")
        for t, name, detail in recent:
            lines.append("  %8.3f s  %-14s %s" % (t, name, detail))
        lines.append("")
        lines.append("提示：CSV 每行是 1 个物理步，最后一列 events 可直接筛选异常。")
        return "\n".join(lines) + "\n"
