# -*- coding: utf-8 -*-
"""性能测试用例（headless，不需要 pygame）。

给调参控制台 ``scripts/tune_panel.py`` 用：给定一份 config dict，跑一组固定用例，
输出"性能报告"文本 + 结构化指标。

用例（每个都是可重复的一次性测试，用大场地避免撞墙）：

- 动力：0→50/100/130 km/h、极速、达到极速的时间、起步最大纵向加速度、打滑时长
- 制动：100→0、极速→0 的时间与距离
- 抓地：40~120 km/h 半舵转弯时能给出的最大横向加速度
- 转弯：几何最小转弯半径、低速实测、100 km/h 满舵半径
- 发动机制动：60 / 100 km/h 松油门 1 s 的平均减速度
- 传动：各挡总齿比与红线车速
"""
import copy
import math
import time

from minirace.config import DEFAULT_CONFIG
from minirace.controls import Command
from minirace.sim import Simulation
from minirace.vehicle import VehicleParams

TWO_PI = 2.0 * math.pi
# 性能测试用的大场地（米）：6 km，够做 45 s 直线加速 + 180 km/h 极速刹停。
# 注意这里用的是**世界米**，不是窗口像素——物理/测试与显示比例完全无关。
BIG_WORLD_M = 6000.0


def _big_config(config):
    cfg = copy.deepcopy(config or DEFAULT_CONFIG)
    world = cfg.setdefault("world", {})
    world["width_m"] = BIG_WORLD_M
    world["height_m"] = BIG_WORLD_M
    # 性能报告用大矩形场地，不走赛道（否则起跑/撞墙会污染 0-100、极速等标定）
    cfg["track"] = {"enabled": False}
    return cfg


def _sim(config):
    return Simulation(_big_config(config))


def _peak_power_kw(params):
    best = 0.0
    rpm = params.idle_rpm
    while rpm <= params.redline_rpm:
        power = params.torque_at(rpm) * rpm * TWO_PI / 60.0
        best = max(best, power)
        rpm += 25.0
    return best / 1000.0


def _check(key, value, unit, note=""):
    return (key, value, unit, note)


# --------------------------------------------------------------------- 用例
def measure_acceleration(config):
    """全油门从静止加速：各速度点用时、极速、最大纵向加速度、打滑时长。"""
    sim = _sim(config)
    params = sim.params
    marks = {}
    targets = (50.0, 100.0, 130.0)
    samples = []
    max_long = 0.0
    spin_time = 0.0
    t = 0.0
    while t < 45.0:
        telem = sim.step(Command(throttle=True))
        t += sim.step_dt
        kmh = telem.speed_abs * 3.6
        samples.append((t, kmh))
        max_long = max(max_long, telem.a_long)
        if telem.wheelspin:
            spin_time += sim.step_dt
        for target in targets:
            if target not in marks and kmh >= target:
                marks[target] = t
    top_kmh = max(sample[1] for sample in samples)
    top_time = 0.0
    for sample_t, kmh in samples:
        if kmh >= top_kmh * 0.995:
            top_time = sample_t
            break
    return {
        "marks": marks,
        "top_kmh": top_kmh,
        "top_time": top_time,
        "max_a_long": max_long,
        "spin_time": spin_time,
        "max_a_long_g": max_long / params.gravity,
    }


def _brake_case(config, target_kmh=None, accel_seconds=45.0):
    """先加速到目标速度（None = 极速），再全力刹车。"""
    sim = _sim(config)
    t = 0.0
    if target_kmh is not None:
        while t < 45.0:
            if (sim.telemetry is not None
                    and sim.telemetry.speed_abs * 3.6 >= target_kmh):
                break
            sim.step(Command(throttle=True))
            t += sim.step_dt
    else:
        while t < accel_seconds:
            sim.step(Command(throttle=True))
            t += sim.step_dt
    v0 = sim.telemetry.speed_abs
    distance0 = sim.distance
    brake_time = 0.0
    while brake_time < 20.0:
        sim.step(Command(brake=True))
        brake_time += sim.step_dt
        if sim.telemetry.speed_abs < 0.5:
            break
    return {
        "v0_kmh": v0 * 3.6,
        "time": brake_time,
        "distance": sim.distance - distance0,
        "avg_g": v0 / max(brake_time, 1e-6) / sim.params.gravity,
    }


def _corner_case(config, speed_kmh, steer, seconds=1.5):
    """恒定方向盘、松油门过弯，返回窗口内最大横向加速度与稳定状态。"""
    sim = _sim(config)
    sim.vehicle.vx = speed_kmh / 3.6
    sim.vehicle.vy = 0.0
    sim.vehicle.yaw_rate = 0.0
    max_lat = 0.0
    min_vx = 1e9
    t = 0.0
    while t < seconds:
        telem = sim.step_raw(0.0, 0.0, steer)
        t += sim.step_dt
        max_lat = max(max_lat, abs(telem.a_lat))
        min_vx = min(min_vx, telem.vx)
    return {
        "max_lat": max_lat,
        "max_lat_g": max_lat / sim.params.gravity,
        "end_speed_kmh": telem.speed_abs * 3.6,
        "radius": telem.radius,
        "stable": min_vx > 2.0 and abs(telem.yaw_rate) < 5.0,
    }


def measure_cornering(config):
    """扫描不同初速的半舵过弯，找最大横向加速度；再测低速/高速转弯半径。"""
    params = VehicleParams(config)
    best = None
    scan = []
    for speed_kmh in (40.0, 60.0, 80.0, 100.0, 120.0):
        case = _corner_case(config, speed_kmh, 0.5)
        scan.append((speed_kmh, case))
        if case["stable"] and (best is None or case["max_lat"] > best["max_lat"]):
            best = case
            best["speed_kmh"] = speed_kmh

    # 低速几何转弯半径（实测）
    slow = _corner_case(config, 11.0, 1.0, seconds=0.8)
    # 100 km/h 满舵半径
    fast = _corner_case(config, 100.0, 1.0, seconds=1.0)

    return {
        "scan": scan,
        "best": best,
        "theory_limit_g": params.friction,
        "radius_min_theory": params.radius_min,
        "radius_slow_measured": slow["radius"],
        "radius_100kmh": fast["radius"],
        "radius_100kmh_lat_g": fast["max_lat_g"],
    }


# CPU 负载用例的驾驶输入循环（油门, 刹车, 方向盘），覆盖加速/转向/制动/换挡
_MIXED_COMMANDS = (
    (0.9, 0.0, 0.25),
    (0.9, 0.0, -0.35),
    (0.5, 0.2, -0.80),
    (0.0, 0.0, 0.50),
    (0.3, 0.0, 0.00),
    (0.9, 0.3, 0.90),
)


def _mixed_step(sim, dt, t):
    throttle, brake, steer = _MIXED_COMMANDS[int(t / 0.5) % len(_MIXED_COMMANDS)]
    sim.step_raw(throttle, brake, steer, dt)


def measure_cpu_load(config, seconds=8.0, repeats=3):
    """测量纯物理计算的 CPU 开销，估算实时运行时的余量。

    做法：在 6.0 km 大场地上按当前 step_hz 模拟 ``seconds`` 秒的混合驾驶
    （油门/转向/刹车/换挡都会触发），用 ``time.process_time()`` 统计 CPU 时间，
    多跑几次取最优，避免系统调度噪声。

    报告内容：
    - 单步物理耗时（ms，CPU 时间）
    - 每秒能算多少物理步
    - 实时余量 = 可算步数 / step_hz（只算物理，不含渲染/音频）
    - 以当前 step_hz 实时运行时的单核 CPU 占用估算
    - 留给渲染/音频后（单核 50% 预算）还能支撑的物理步长
    """
    best_cpu = None
    best_wall = 0.0
    steps = 0
    dt = 0.0
    for repeat in range(repeats + 1):
        sim = _sim(config)
        dt = sim.step_dt
        total = int(round(seconds / dt))
        warmup = min(total, int(round(0.5 / dt)))
        t = 0.0
        for _ in range(warmup):
            _mixed_step(sim, dt, t)
            t += dt
        cpu0 = time.process_time()
        wall0 = time.perf_counter()
        for _ in range(total):
            _mixed_step(sim, dt, t)
            t += dt
        cpu = time.process_time() - cpu0
        wall = time.perf_counter() - wall0
        if repeat > 0 and (best_cpu is None or cpu < best_cpu):
            best_cpu = cpu
            best_wall = wall
            steps = total
    step_hz = 1.0 / dt if dt > 0 else 0.0
    per_step = best_cpu / steps if steps else 0.0
    steps_per_second = 1.0 / per_step if per_step > 0 else 0.0
    headroom = steps_per_second / step_hz if step_hz > 0 else 0.0
    cpu_percent = 100.0 * step_hz / steps_per_second if steps_per_second > 0 else 0.0
    return {
        "seconds": seconds,
        "steps": steps,
        "step_hz": step_hz,
        "step_hz_current": step_hz,
        "cpu_seconds": best_cpu,
        "wall_seconds": best_wall,
        "ms_per_step": per_step * 1000.0,
        "steps_per_second": steps_per_second,
        "headroom": headroom,
        "cpu_percent": cpu_percent,
        "budget_hz_50pct": steps_per_second * 0.5,
        "repeats": repeats,
    }


def measure_engine_braking(config, target_kmh):
    sim = _sim(config)
    t = 0.0
    while t < 45.0:
        sim.step(Command(throttle=True))
        t += sim.step_dt
        if sim.telemetry.speed_abs * 3.6 >= target_kmh:
            break
    v0 = sim.telemetry.speed_abs
    rpm0 = sim.telemetry.rpm
    gear = sim.telemetry.gear
    sim.step_raw(0.0, 0.0, 0.0, 0.0)  # 确保踏板归零
    start_distance = sim.distance
    t = 0.0
    while t < 1.0:
        sim.step_raw(0.0, 0.0, 0.0)
        t += sim.step_dt
    return {
        "speed_kmh": v0 * 3.6,
        "rpm": rpm0,
        "gear": gear,
        "decel": (v0 - sim.telemetry.speed_abs) / max(t, 1e-6),
        "distance": sim.distance - start_distance,
    }


# --------------------------------------------------------------------- 报告
class BenchmarkReport(object):
    def __init__(self, sections, metrics):
        self.sections = sections
        self.metrics = metrics

    def as_text(self):
        lines = ["Mini Race 2 性能报告"]
        lines.append("生成时间: %s" % time.strftime("%Y-%m-%d %H:%M:%S"))
        lines.append("说明: 全部用例在 6.0 km 虚拟大场地上 headless 运行，"
                     "不涉及赛道/墙壁；驱动力来自物理模型本身。")
        for title, rows in self.sections:
            lines.append("")
            lines.append("== %s ==" % title)
            for label, value, unit, note in rows:
                text = "%s : %s%s" % (label, value, unit)
                if note:
                    text += "   (%s)" % note
                lines.append(text)
        lines.append("")
        return "\n".join(lines)


def _fmt(value, digits):
    if isinstance(value, int):
        return str(value)
    return ("%%.%df" % digits) % value


def run_all(config, include_scan=True):
    """跑全部用例，返回 BenchmarkReport。耗时通常 1~3 秒。"""
    report_start = time.perf_counter()
    params = VehicleParams(config)
    sections = []
    metrics = {}

    # 关键参数
    sections.append(("关键参数", [
        _check("整车质量", _fmt(params.mass, 0), " kg"),
        _check("横摆转动惯量", _fmt(params.inertia, 0), " kg·m²"),
        _check("轴距 / 轴荷", "%.2f m / 前 %.0f%%" % (
            params.wheelbase, params.front_weight_fraction * 100.0), ""),
        _check("附着系数", "%.2f" % params.friction, " (理论极限 %.2f g)"
               % params.friction),
        _check("峰值功率", "%.0f" % _peak_power_kw(params), " kW（扭矩曲线）"),
        _check("物理步长", "%.0f" % params.step_hz, " Hz"),
        _check("主减速比 / 挡数", "%.2f / %dAT" % (
            params.final_drive, params.num_gears), ""),
    ]))

    # 动力
    accel = measure_acceleration(config)
    metrics["accel"] = accel
    rows = []
    for target in (50.0, 100.0, 130.0):
        if target in accel["marks"]:
            rows.append(_check("0 - %.0f km/h" % target,
                               "%.2f" % accel["marks"][target], " s"))
        else:
            rows.append(_check("0 - %.0f km/h" % target, "未达到", ""))
    rows.append(_check("极速", "%.1f" % accel["top_kmh"], " km/h",
                       "达到 %.1f s" % accel["top_time"]))
    rows.append(_check("起步最大纵向加速度", "%.2f" % accel["max_a_long_g"], " g",
                       "打滑累计 %.2f s" % accel["spin_time"]))
    sections.append(("动力", rows))

    # 制动
    brake_100 = _brake_case(config, target_kmh=100.0)
    brake_top = _brake_case(config, target_kmh=None)
    metrics["brake_100"] = brake_100
    metrics["brake_top"] = brake_top
    sections.append(("制动", [
        _check("100 -> 0 km/h", "%.1f" % brake_100["distance"], " m",
               "%.2f s，平均 %.2f g" % (brake_100["time"], brake_100["avg_g"])),
        _check("极速 -> 0 km/h", "%.1f" % brake_top["distance"], " m",
               "%.2f s，平均 %.2f g" % (brake_top["time"], brake_top["avg_g"])),
    ]))

    # 抓地 / 转弯
    corner = measure_cornering(config)
    metrics["corner"] = corner
    best = corner["best"]
    rows = []
    if best is not None:
        rows.append(_check("最大横向加速度", "%.2f" % best["max_lat_g"], " g",
                           "半舵，初速 %.0f km/h" % best["speed_kmh"]))
    else:
        rows.append(_check("最大横向加速度", "无稳定结果", ""))
    rows.append(_check("理论附着极限", "%.2f" % corner["theory_limit_g"], " g",
                       "摩擦系数 × g"))
    rows.append(_check("几何最小转弯半径", "%.2f" % corner["radius_min_theory"], " m",
                       "轴距/最大前轮转角"))
    rows.append(_check("低速实测转弯半径", "%.2f" % corner["radius_slow_measured"], " m",
                       "11 km/h 满舵"))
    rows.append(_check("100 km/h 满舵半径", "%.1f" % corner["radius_100kmh"], " m",
                       "横向 %.2f g" % corner["radius_100kmh_lat_g"]))
    sections.append(("抓地 / 转弯", rows))
    if include_scan:
        scan_rows = []
        for speed_kmh, case in corner["scan"]:
            scan_rows.append(_check(
                "初速 %.0f km/h 半舵" % speed_kmh,
                "%.2f" % case["max_lat_g"], " g",
                "R %.1f m，末速 %.0f km/h%s" % (
                    case["radius"], case["end_speed_kmh"],
                    "" if case["stable"] else "，失稳")))
        sections.append(("过弯扫描", scan_rows))

    # 发动机制动
    eb60 = measure_engine_braking(config, 60.0)
    eb100 = measure_engine_braking(config, 100.0)
    metrics["engine_brake"] = {"60": eb60, "100": eb100}
    sections.append(("发动机制动", [
        _check("60 km/h 松油门", "%.2f" % eb60["decel"], " m/s²",
               "%d 挡 %.0f rpm，1 s 滑行 %.1f m" % (
                   eb60["gear"], eb60["rpm"], eb60["distance"])),
        _check("100 km/h 松油门", "%.2f" % eb100["decel"], " m/s²",
               "%d 挡 %.0f rpm，1 s 滑行 %.1f m" % (
                   eb100["gear"], eb100["rpm"], eb100["distance"])),
    ]))

    # 传动
    rows = []
    for gear in range(1, params.num_gears + 1):
        total = params.gear_ratio(gear) * params.final_drive
        v_red = params.redline_rpm / 60.0 * TWO_PI / total * params.wheel_radius * 3.6
        rows.append(_check("挡位 %d" % gear, "总齿比 %.2f" % total, "",
                           "红线车速 %.1f km/h" % v_red))
    rows.append(_check("倒挡", "齿比 %.2f" % (params.reverse_ratio * params.final_drive), "",
                       "红线车速 %.1f km/h" % (
                           params.redline_rpm / 60.0 * TWO_PI
                           / (params.reverse_ratio * params.final_drive)
                           * params.wheel_radius * 3.6)))
    sections.append(("传动", rows))

    # CPU 负载（物理计算自身占多少 CPU；动力学变复杂后看这个判断 240Hz 还够不够）
    cpu = measure_cpu_load(config)
    metrics["cpu"] = cpu
    report_seconds = time.perf_counter() - report_start
    sections.append(("CPU 负载（物理计算）", [
        _check("物理负载用例", "%.1f s 模拟 / %d 步" % (cpu["seconds"], cpu["steps"]),
               "", "混合油门/转向/刹车/换挡"),
        _check("单步物理耗时", "%.4f" % cpu["ms_per_step"], " ms",
               "CPU 时间，%d 次取最优" % cpu["repeats"]),
        _check("每秒可算物理步", "%.0f" % cpu["steps_per_second"], " 步/s", "单核"),
        _check("实时余量", "%.1f" % cpu["headroom"], "x",
               "= 可算步数 / %.0f Hz" % cpu["step_hz"]),
        _check("%.0f Hz 实时 CPU 占用" % cpu["step_hz"], "%.2f" % cpu["cpu_percent"],
               "% 单核", "仅物理，不含渲染/音频"),
        _check("单核 50% 预算可支撑步长", "%.0f" % cpu["budget_hz_50pct"], " Hz",
               "剩下的留给渲染/音频/系统"),
        _check("整份报告生成耗时", "%.2f" % report_seconds, " s", "wall clock"),
    ]))

    return BenchmarkReport(sections, metrics)
