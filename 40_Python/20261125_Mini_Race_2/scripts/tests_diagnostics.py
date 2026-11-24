# -*- coding: utf-8 -*-
"""诊断模式自检（不需要 pygame）：构造各类异常，确认事件被标记、CSV/摘要正常。

跑法::

    python scripts/tests_diagnostics.py
"""
import copy
import math
import os
import shutil
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from minirace.config import DEFAULT_CONFIG  # noqa: E402
from minirace.diagnostics import Diagnostics  # noqa: E402
from minirace.sim import Simulation  # noqa: E402

_results = []


def check(name, ok, detail=""):
    _results.append((name, bool(ok), detail))
    print("[%s] %s%s" % ("PASS" if ok else "FAIL", name,
                         ("  <- " + detail) if detail else ""))


def make_config(world=1000.0, step_hz=240, **diag):
    config = copy.deepcopy(DEFAULT_CONFIG)
    config["world"] = {"width_m": world, "height_m": world}
    config["vehicle"]["step_hz"] = step_hz
    config["diagnostics"].update(diag)
    return config


class Harness(object):
    """一次诊断会话：sim + diagnostics（写临时目录）。"""

    def __init__(self, config, project_dir):
        self.project_dir = project_dir
        self.sim = Simulation(config)
        self.diag = Diagnostics(project_dir, config)
        self.path = self.diag.start()

    def step(self, command=None):
        self.sim.step(command)
        self.diag.step(self.sim)

    def raw(self, throttle, brake, steer):
        self.sim.step_raw(throttle, brake, steer)
        self.diag.step(self.sim)

    def close(self):
        return self.diag.stop()


def read_summary(path):
    try:
        with open(path, encoding="utf-8") as fh:
            return fh.read()
    except OSError:
        return ""


def test_basic_record(tmp):
    harness = Harness(make_config(), tmp)
    for _ in range(120):
        harness.step(None)
    summary_path = harness.close()
    ok_files = (harness.path and os.path.exists(harness.path)
                and summary_path and os.path.exists(summary_path))
    header_ok = False
    rows = 0
    if harness.path and os.path.exists(harness.path):
        with open(harness.path, encoding="utf-8") as fh:
            header = fh.readline()
            header_ok = "events" in header and "wall_hit" in header
            rows = sum(1 for _ in fh)
    check("诊断模式：CSV/摘要生成，CSV 含 telemetry 列与 events 列",
          ok_files and header_ok and rows == 120,
          "csv=%s，rows=%d" % (os.path.basename(harness.path or ""), rows))
    summary = read_summary(summary_path) if summary_path else ""
    check("摘要包含事件统计与关键统计",
          "异常事件统计" in summary and "关键统计" in summary,
          "摘要 %d 字符" % len(summary))
    return True


def test_speed_jump(tmp):
    harness = Harness(make_config(), tmp)
    for _ in range(10):
        harness.step(None)
    harness.sim.vehicle.vx = 80.0  # 单步速度突变，触发 SPEED_JUMP
    harness.step(None)
    summary_path = harness.close()
    summary = read_summary(summary_path) if summary_path else ""
    check("速度单步跳变 -> SPEED_JUMP",
          "SPEED_JUMP" in summary and harness.diag.event_counts["SPEED_JUMP"] >= 1,
          "计数 %d" % harness.diag.event_counts["SPEED_JUMP"])


def test_heading_jump(tmp):
    harness = Harness(make_config(), tmp)
    for _ in range(10):
        harness.step(None)
    harness.sim.vehicle.heading += 0.8  # 单步航向突变
    harness.step(None)
    summary_path = harness.close()
    summary = read_summary(summary_path) if summary_path else ""
    check("航向单步跳变 -> HEADING_JUMP",
          "HEADING_JUMP" in summary and harness.diag.event_counts["HEADING_JUMP"] >= 1,
          "计数 %d" % harness.diag.event_counts["HEADING_JUMP"])


def test_gear_hunting(tmp):
    harness = Harness(make_config(), tmp)
    harness.sim.vehicle.shift_cooldown = 1e9  # 关掉自动换挡，手动制造抖动
    for index in range(80):
        if index % 2 == 0:
            harness.sim.vehicle.gear = 2 if harness.sim.vehicle.gear != 2 else 3
        harness.step(None)
    summary_path = harness.close()
    summary = read_summary(summary_path) if summary_path else ""
    check("换挡抖动 -> GEAR_HUNT",
          "GEAR_HUNT" in summary and harness.diag.event_counts["GEAR_HUNT"] >= 1,
          "计数 %d，换挡 %d 次" % (
              harness.diag.event_counts["GEAR_HUNT"],
              harness.diag.gear_change_count))


def test_wall_hit(tmp):
    harness = Harness(make_config(world=129.6), tmp)
    harness.sim.vehicle.x = 129.6 - 4.0
    harness.sim.vehicle.y = 60.0
    harness.sim.vehicle.heading = 0.0  # 朝 +x
    harness.sim.vehicle.vx = 20.0
    for _ in range(60):
        harness.raw(0.9, 0.0, 0.0)
    summary_path = harness.close()
    summary = read_summary(summary_path) if summary_path else ""
    check("撞世界边界 -> WALL_HIT（连续过程计一次）",
          "WALL_HIT" in summary and harness.diag.event_counts["WALL_HIT"] >= 1,
          "次数 %d，连续 %d" % (harness.diag.event_counts["WALL_HIT"],
                              harness.diag._wall_episodes))


def test_grip_saturation(tmp):
    harness = Harness(make_config(), tmp)
    harness.sim.vehicle.vx = 20.0
    for _ in range(int(2.0 / harness.sim.step_dt)):
        harness.raw(0.0, 0.0, 1.0)
    summary_path = harness.close()
    summary = read_summary(summary_path) if summary_path else ""
    check("长时间抓地饱和 -> GRIP_SATURATED",
          "GRIP_SATURATED" in summary
          and harness.diag.event_counts["GRIP_SATURATED"] >= 1,
          "次数 %d" % harness.diag.event_counts["GRIP_SATURATED"])


def test_nan(tmp):
    harness = Harness(make_config(), tmp)
    for _ in range(10):
        harness.step(None)
    harness.sim.telemetry.vx = float("nan")
    harness.diag.step(harness.sim)
    summary_path = harness.close()
    summary = read_summary(summary_path) if summary_path else ""
    check("NaN/Inf -> NAN 事件",
          "NAN" in summary and harness.diag.event_counts["NAN"] >= 1,
          "计数 %d" % harness.diag.event_counts["NAN"])


def test_yaw_runaway(tmp):
    harness = Harness(make_config(), tmp)
    # 无转向输入但强制横摆角速度持续过大（模拟自旋/螺旋）
    for _ in range(int(0.8 / harness.sim.step_dt)):
        harness.sim.step(None)
        harness.sim.telemetry.yaw_rate = 3.0
        harness.sim.telemetry.steer = 0.0
        harness.diag.step(harness.sim)
    summary_path = harness.close()
    summary = read_summary(summary_path) if summary_path else ""
    check("无转向输入持续大横摆 -> YAW_RUNAWAY",
          "YAW_RUNAWAY" in summary and harness.diag.event_counts["YAW_RUNAWAY"] >= 1,
          "次数 %d" % harness.diag.event_counts["YAW_RUNAWAY"])


def main():
    tmp = tempfile.mkdtemp(prefix="mini_race_diag_")
    try:
        test_basic_record(tmp)
        test_speed_jump(tmp)
        test_heading_jump(tmp)
        test_gear_hunting(tmp)
        test_wall_hit(tmp)
        test_grip_saturation(tmp)
        test_nan(tmp)
        test_yaw_runaway(tmp)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    failed = [name for name, ok, _ in _results if not ok]
    print()
    print("%d/%d 项通过" % (len(_results) - len(failed), len(_results)))
    if failed:
        print("失败：")
        for name in failed:
            print("  - " + name)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
