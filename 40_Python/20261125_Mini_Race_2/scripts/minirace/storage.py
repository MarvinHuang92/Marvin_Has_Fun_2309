# -*- coding: utf-8 -*-
"""运行数据落盘：把每一步物理观测量录成 CSV，供以后分析和 AI 训练用。

文件写到 ``data/run_YYYYmmdd_HHMMSS.csv``，列定义见 ``CSV_FIELDS``。
``data/`` 下的产物不入库（见 .gitignore）。
"""
import csv
import logging
import os
import time

LOG = logging.getLogger(__name__)

CSV_FIELDS = [
    "t", "x", "y", "heading",
    "vx", "vy", "speed_abs", "yaw_rate", "beta_deg",
    "rpm", "gear", "engine_torque",
    "a_long", "a_lat", "grip_usage",
    "slip_amount", "wheelspin", "lockup", "sliding",
    "steer_deg", "throttle", "brake",
]


def _fmt(value):
    if isinstance(value, float):
        return "%.4f" % value
    return value


class TelemetryRecorder(object):
    """逐物理步写 CSV。构造失败时 ``active`` 为 False，调用方继续跑。"""

    def __init__(self, data_dir):
        self.path = None
        self.rows = 0
        self._fh = None
        self._writer = None
        try:
            if not os.path.isdir(data_dir):
                os.makedirs(data_dir)
            stamp = time.strftime("%Y%m%d_%H%M%S")
            path = os.path.join(data_dir, "run_%s.csv" % stamp)
            index = 1
            while os.path.exists(path):
                path = os.path.join(data_dir, "run_%s_%02d.csv" % (stamp, index))
                index += 1
            self._fh = open(path, "w", newline="", encoding="utf-8")
            self._writer = csv.writer(self._fh)
            self._writer.writerow(CSV_FIELDS)
            self.path = path
        except OSError as exc:
            LOG.warning("遥测文件创建失败，本次不录制：%s", exc)

    @property
    def active(self):
        return self._writer is not None

    def write(self, sim):
        if self._writer is None or sim.telemetry is None:
            return
        t = sim.telemetry
        self._writer.writerow([
            _fmt(sim.time), _fmt(t.x), _fmt(t.y), _fmt(t.heading),
            _fmt(t.vx), _fmt(t.vy), _fmt(t.speed_abs), _fmt(t.yaw_rate),
            _fmt(t.beta_deg),
            _fmt(t.rpm), t.gear, _fmt(t.engine_torque),
            _fmt(t.a_long), _fmt(t.a_lat), _fmt(t.grip_usage),
            _fmt(t.slip_amount), int(bool(t.wheelspin)), int(bool(t.lockup)),
            int(bool(t.sliding)),
            _fmt(t.steer_deg), _fmt(t.throttle), _fmt(t.brake),
        ])
        self.rows += 1

    def close(self):
        if self._fh is not None:
            try:
                self._fh.close()
            except OSError:
                pass
            self._fh = None
            self._writer = None
            LOG.info("遥测已保存：%s（%d 行）", self.path, self.rows)
