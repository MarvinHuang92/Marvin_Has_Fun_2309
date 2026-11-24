# -*- coding: utf-8 -*-
"""物理标定探针：打印车辆/传动参数、加速、制动、发动机制动、过弯表。

不跑游戏、不需要 pygame，用来核对 docs/车辆动力学模型.md 与 Readme 里的数字。

跑法::

    python scripts/probe_physics.py
"""
import copy
import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from minirace.config import DEFAULT_CONFIG  # noqa: E402
from minirace.controls import Command  # noqa: E402
from minirace.sim import Simulation  # noqa: E402

TWO_PI = 2.0 * math.pi


def new_sim(large_world=True):
    """用 6.0 km 的大场地，避免直线跑出去撞世界边界（与显示比例无关）。"""
    config = copy.deepcopy(DEFAULT_CONFIG)
    if large_world:
        config["world"] = {"width_m": 6000.0, "height_m": 6000.0}
    return Simulation(config)


def drive(sim, command, seconds):
    return sim.advance(command, seconds)


def drive_raw(sim, throttle, brake, steer, seconds):
    remaining = float(seconds)
    telemetry = sim.telemetry
    while remaining > 1e-9:
        step = min(sim.step_dt, remaining)
        telemetry = sim.step_raw(throttle, brake, steer, step)
        remaining -= step
    return telemetry


def set_speed(sim, speed):
    sim.vehicle.vx = float(speed)
    sim.vehicle.vy = 0.0
    sim.vehicle.yaw_rate = 0.0


def probe_parameters():
    sim = new_sim()
    p = sim.params
    print("== 车辆 ==")
    print("质量 %.0f kg，横摆转动惯量 %.0f kg·m²，轴距 %.2f m（a=%.2f / b=%.2f）"
          % (p.mass, p.inertia, p.wheelbase, p.a, p.b))
    print("静态轴荷：前 %.0f N / 后 %.0f N（前轴荷 %.0f%%）"
          % (p.static_front_load, p.static_rear_load, p.front_weight_fraction * 100.0))
    print("附着系数 %.2f -> 极限 %.2f g；侧偏刚度 %.0f/Fz，峰值侧偏 %.1f deg"
          % (p.friction, p.friction, p.cornering_stiffness,
             math.degrees(math.tan(math.pi / (2.0 * p.tire_shape))
                          / (p.cornering_stiffness / (p.friction * p.tire_shape)))))
    print("几何最小转弯半径 %.2f m（最大前轮转角 %.1f deg）"
          % (p.radius_min, p.max_steer_deg))
    print()
    print("== 传动 ==")
    print("挡位  总齿比   红线车速(km/h)   4200rpm 车速(km/h)")
    for gear in range(1, p.num_gears + 1):
        total = p.gear_ratio(gear) * p.final_drive
        v_red = p.redline_rpm / 60.0 * TWO_PI / total * p.wheel_radius * 3.6
        v_mid = 4200.0 / 60.0 * TWO_PI / total * p.wheel_radius * 3.6
        print(" %2d    %6.2f   %10.1f        %10.1f" % (gear, total, v_red, v_mid))
    peak_power = max(p.torque_at(rpm) * rpm * TWO_PI / 60.0
                     for rpm in range(int(p.idle_rpm), int(p.redline_rpm) + 1, 50))
    print("峰值功率约 %.0f kW（扭矩曲线线性插值，按 100%% 油门）" % (peak_power / 1000.0))
    print()


def probe_acceleration():
    print("== 全油门加速 ==")
    sim = new_sim()
    t = 0.0
    marks = {}
    targets = (50.0, 100.0, 130.0)
    log = []
    next_log = 0.0
    while t < 30.0:
        telem = sim.step(Command(throttle=True))
        t += sim.step_dt
        kmh = telem.speed_abs * 3.6
        for target in targets:
            if target not in marks and kmh >= target:
                marks[target] = t
        if t >= next_log:
            log.append((t, telem))
            next_log += 1.0
    print("t(s)   v(km/h)  rpm   gear  a_long(g)  wheelspin")
    for t, telem in log:
        print("%5.1f  %7.1f  %5.0f  %4d  %9.2f  %s" % (
            t, telem.speed_abs * 3.6, telem.rpm, telem.gear,
            telem.a_long / sim.params.gravity, telem.wheelspin))
    for target in targets:
        if target in marks:
            print("0 -> %5.0f km/h : %.2f s" % (target, marks[target]))
    top = max(x[1].speed_abs for x in log)
    print("极速 : %.1f km/h（6 挡红线，约 %.0f rpm）" % (top * 3.6, sim.telemetry.rpm))
    print()


def probe_braking():
    print("== 制动 ==")
    sim = new_sim()
    drive(sim, Command(throttle=True), 25.0)
    v0 = sim.telemetry.speed_abs
    d0 = sim.distance
    t = 0.0
    while t < 10.0:
        sim.step(Command(brake=True))
        t += sim.step_dt
        if sim.telemetry.speed_abs < 0.5:
            break
    print("极速刹停：%.1f km/h -> 0，用时 %.2f s，距离 %.1f m，平均 %.2f g"
          % (v0 * 3.6, t, sim.distance - d0,
             v0 / t / sim.params.gravity))
    print()


def probe_engine_braking():
    print("== 发动机制动 ==")
    for target_kmh in (60.0, 100.0):
        sim = new_sim()
        while sim.telemetry is None or sim.telemetry.speed_abs * 3.6 < target_kmh:
            sim.step(Command(throttle=True))
        v0 = sim.telemetry.speed_abs
        rpm0 = sim.telemetry.rpm
        gear = sim.telemetry.gear
        drive_raw(sim, 0.0, 0.0, 0.0, 1.0)
        decel = (v0 - sim.telemetry.speed_abs) / 1.0
        print("%.0f km/h（%d 挡 %.0f rpm）松油门 1 s：平均减速 %.2f m/s²，"
              "末转速 %.0f rpm" % (target_kmh, gear, rpm0, decel, sim.telemetry.rpm))
    print()


def probe_cornering():
    print("== 稳态过弯（恒定方向盘，松油门；1.2 s 后测量）==")
    print(" v(km/h) steer(deg) | a_lat(g)  R(m)  yaw(deg/s)  slip  beta(deg) 状态")
    for v_kmh in (30.0, 60.0, 90.0, 120.0):
        for steer_frac in (0.25, 0.5, 1.0):
            sim = new_sim()
            set_speed(sim, v_kmh / 3.6)
            telemetry = drive_raw(sim, 0.0, 0.0, steer_frac, 1.2)
            state = "SPIN" if telemetry.speed < 0.2 or abs(telemetry.yaw_rate) > 4.0 else "ok"
            print("%7.0f   %7.1f | %7.2f %6.1f %10.1f %6.2f %9.1f  %s" % (
                telemetry.speed_abs * 3.6, sim.params.max_steer_deg * steer_frac,
                abs(telemetry.a_lat) / sim.params.gravity, telemetry.radius,
                math.degrees(telemetry.yaw_rate), telemetry.slip_amount,
                telemetry.beta_deg, state))
    print()


def main():
    probe_parameters()
    probe_acceleration()
    probe_braking()
    probe_engine_braking()
    probe_cornering()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
