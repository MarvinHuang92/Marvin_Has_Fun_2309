# -*- coding: utf-8 -*-
"""物理自检：不需要 pygame，纯 Python 断言。

跑法::

    python scripts/tests_physics.py

覆盖：怠速、加速/极速、自动换挡节奏、制动、发动机制动、打滑检测、
稳态过弯的附着上限、低速转向、倒挡、边界钳位、步长无关性、数值稳定性。
"""
import copy
import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from minirace.camera import Camera  # noqa: E402
from minirace.config import DEFAULT_CONFIG  # noqa: E402
from minirace.controls import Command  # noqa: E402
from minirace.sim import Simulation  # noqa: E402

# 自检用超大**世界（米）**，避免直线跑出去撞世界边界污染测量；
# 注意这与窗口像素/显示缩放无关。只有撞墙测试用默认世界尺寸。
LARGE_WORLD_M = 3600.0
_results = []


def check(name, ok, detail=""):
    _results.append((name, bool(ok), detail))
    print("[%s] %s%s" % ("PASS" if ok else "FAIL", name,
                         ("  <- " + detail) if detail else ""))


def make_sim(large_world=True):
    config = copy.deepcopy(DEFAULT_CONFIG)
    if large_world:
        config["world"] = {"width_m": LARGE_WORLD_M, "height_m": LARGE_WORLD_M}
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


# --------------------------------------------------------------------- 测试
def test_idle():
    sim = Simulation()
    drive(sim, Command(), 2.0)
    telem = sim.telemetry
    idle = sim.params.idle_rpm
    check("怠速：静止时转速保持在 idle，挡位 1，速度为 0",
          abs(telem.rpm - idle) < 60.0 and telem.gear == 1 and abs(telem.vx) < 1e-9,
          "rpm=%.0f（idle=%.0f），vx=%.3f" % (telem.rpm, idle, telem.vx))


def test_top_speed():
    sim = make_sim()
    drive(sim, Command(throttle=True), 30.0)
    telem = sim.telemetry
    kmh = telem.speed_abs * 3.6
    check("极速受 6 挡齿比/红线限制（约 180 km/h）",
          170.0 <= kmh <= 190.0 and telem.gear == 6 and telem.rpm > 6800.0,
          "%.1f km/h，gear=%d，rpm=%.0f" % (kmh, telem.gear, telem.rpm))


def test_acceleration():
    sim = make_sim()
    t = 0.0
    t100 = None
    while t < 20.0 and t100 is None:
        telem = sim.step(Command(throttle=True))
        t += sim.step_dt
        if telem.speed_abs * 3.6 >= 100.0:
            t100 = t
    check("0-100 km/h 约 6.3 秒（1450 kg 四驱）",
          t100 is not None and 5.8 <= t100 <= 6.8,
          "0-100 用时 %.2f s" % (t100 if t100 else -1))


def test_auto_shift():
    sim = make_sim()
    gear = sim.vehicle.gear
    times = []
    t = 0.0
    while t < 20.0:
        sim.step(Command(throttle=True))
        t += sim.step_dt
        if sim.vehicle.gear != gear:
            times.append((t, gear, sim.vehicle.gear))
            gear = sim.vehicle.gear
    gears = [g for _, _, g in times]
    intervals = [times[i + 1][0] - times[i][0] for i in range(len(times) - 1)]
    min_interval = min(intervals) if intervals else 0.0
    check("自动挡 1->6 逐挡升挡，且相邻换挡间隔不小于 shift_interval",
          gears == [2, 3, 4, 5, 6]
          and min_interval >= sim.params.shift_interval - 0.05,
          "换挡序列=%s，最小间隔 %.2f s（要求 >= %.2f）" % (
              gears, min_interval, sim.params.shift_interval))


def test_braking():
    sim = make_sim()
    drive(sim, Command(throttle=True), 20.0)
    v0 = sim.telemetry.speed_abs
    distance0 = sim.distance
    t = 0.0
    while t < 10.0:
        sim.step(Command(brake=True))
        t += sim.step_dt
        if sim.telemetry.speed_abs < 0.5:
            break
    distance = sim.distance - distance0
    check("从极速刹停：约 4.8 秒、125 m（受附着限制）",
          4.0 <= t <= 5.5 and 110.0 <= distance <= 140.0,
          "v0=%.1f km/h，%.2f s，%.1f m" % (v0 * 3.6, t, distance))


def test_engine_braking():
    sim = make_sim()
    drive(sim, Command(throttle=True), 8.0)
    v0 = sim.telemetry.speed_abs
    rpm0 = sim.telemetry.rpm
    speed_before = v0
    drive_raw(sim, 0.0, 0.0, 0.0, 1.5)
    decel = (speed_before - sim.telemetry.speed_abs) / 1.5
    check("松油门有发动机制动（无刹车也会持续减速）",
          0.4 <= decel <= 3.0 and sim.telemetry.speed_abs < speed_before,
          "%.0f km/h 松油门后平均减速 %.2f m/s²（rpm %.0f -> %.0f）" % (
              v0 * 3.6, decel, rpm0, sim.telemetry.rpm))


def test_wheelspin():
    sim = make_sim()
    drive(sim, Command(throttle=True), 1.0)
    telem = sim.telemetry
    spinning = telem.wheelspin and telem.slip_amount > 0.02
    check("起步大油门会出现驱动轮打滑（打滑声音的触发条件）",
          spinning,
          "t=1.0s 时 wheelspin=%s，slip=%.2f" % (telem.wheelspin, telem.slip_amount))


def test_grip_limit_cornering():
    sim = make_sim()
    drive(sim, Command(throttle=True), 3.0)
    # 40 km/h 以上、半舵、松油门：应该稳定在附着极限附近，不甩尾
    set_speed(sim, 16.7)
    max_lat = 0.0
    min_vx = 1e9
    for _ in range(int(1.5 / sim.step_dt)):
        telem = sim.step_raw(0.0, 0.0, 0.5)
        max_lat = max(max_lat, abs(telem.a_lat))
        min_vx = min(min_vx, telem.vx)
    limit = sim.params.friction * sim.params.gravity
    check("稳态过弯：横向加速度不超过附着上限，且不进入甩尾/倒车",
          max_lat <= limit * 1.02 and min_vx > 3.0,
          "max |a_lat| = %.2f g（上限 %.2f g），min vx = %.1f m/s" % (
              max_lat / sim.params.gravity, limit / sim.params.gravity, min_vx))


def test_grip_bound_random():
    import random
    random.seed(11)
    sim = make_sim()
    limit = sim.params.friction * sim.params.gravity
    max_force = 0.0
    max_grip = 0.0
    command = Command()
    for i in range(int(60.0 / sim.step_dt)):
        if i % 120 == 0:
            command = Command(
                throttle=random.random() < 0.7,
                brake=random.random() < 0.15,
                left=random.random() < 0.4,
                right=random.random() < 0.4,
            )
        telem = sim.step(command)
        max_force = max(max_force, math.hypot(telem.a_long, telem.a_lat))
        max_grip = max(max_grip, telem.grip_usage)
    check("随机驾驶 60 秒：轮胎合力不越过摩擦圆",
          max_force <= limit * 1.05 and max_grip <= 1.0 + 1e-6,
          "max hypot = %.2f g，max grip_usage = %.4f" % (
              max_force / sim.params.gravity, max_grip))


def test_low_speed_steering():
    sim = make_sim()
    heading0 = sim.vehicle.heading
    drive(sim, Command(throttle=True, left=True), 2.0)
    turn = abs(math.degrees(sim.vehicle.heading - heading0))
    check("低速起步打方向可以转向（不是 V0 的 0.5 s 完全打不动）",
          turn > 20.0,
          "2 秒转过 %.0f 度，末速 %.1f km/h" % (
              turn, sim.telemetry.speed_abs * 3.6))


def test_standstill_steering():
    sim = make_sim()
    heading0 = sim.vehicle.heading
    drive(sim, Command(left=True), 1.0)
    check("静止打方向车头不转（低速轮胎力淡入）",
          abs(sim.vehicle.heading - heading0) < 1e-6 and abs(sim.vehicle.vx) < 1e-6,
          "heading 变化 %.9f rad" % (sim.vehicle.heading - heading0))


def test_geometric_radius():
    sim = make_sim()
    set_speed(sim, 3.0)
    telemetry = drive_raw(sim, 0.0, 0.0, 1.0, 0.6)
    radius = telemetry.radius
    expected = sim.params.radius_min
    check("低速满舵转弯半径接近几何最小半径（%.1f m）" % expected,
          expected * 0.7 <= radius <= expected * 1.4,
          "实测 %.2f m（v=%.1f m/s）" % (radius, telemetry.speed_abs))


def test_reverse():
    parked = make_sim()
    shifted = parked.toggle_reverse() is True and parked.vehicle.gear == -1
    telemetry = drive(parked, Command(throttle=True), 2.0)
    moving = make_sim()
    drive(moving, Command(throttle=True), 3.0)
    rejected = moving.toggle_reverse() is False
    check("停车可挂 R 挡、倒车速度变负；行驶中拒绝换 R",
          shifted and telemetry.vx < -1.0 and rejected,
          "倒车 v=%.1f km/h，gear=%d；行驶中换挡被拒=%s" % (
              telemetry.vx * 3.6, telemetry.gear, rejected))


def test_dt_independence():
    def scripted(dt):
        sim = make_sim()
        t = 0.0
        while t < 3.0:
            if t < 1.0:
                sim.step_raw(0.9, 0.0, 0.0, dt)
            else:
                sim.step_raw(0.9, 0.0, 0.6, dt)
            t += dt
        return sim

    fast = scripted(1.0 / 240.0)
    mid = scripted(1.0 / 120.0)
    slow = scripted(1.0 / 60.0)
    speed_spread = max(
        abs(fast.telemetry.speed_abs - mid.telemetry.speed_abs),
        abs(fast.telemetry.speed_abs - slow.telemetry.speed_abs))
    heading_spread = max(
        abs(math.degrees(fast.vehicle.heading - mid.vehicle.heading)),
        abs(math.degrees(fast.vehicle.heading - slow.vehicle.heading)))
    check("物理结果与步长基本无关（1/240 vs 1/120 vs 1/60）",
          speed_spread < 0.8 and heading_spread < 5.0,
          "速度差 %.2f m/s，航向差 %.2f 度" % (speed_spread, heading_spread))


def test_wall_clamp():
    sim = make_sim(large_world=False)
    sim.vehicle.x = sim.width - 5.0
    sim.vehicle.y = sim.height / 2.0
    sim.vehicle.heading = 0.0  # 朝 +x
    sim.vehicle.vx = 12.0
    drive(sim, Command(throttle=True), 2.0)
    check("撞世界边界后位置被钳住，速度/横摆清零",
          sim.vehicle.x <= sim.width - sim.params.half_width + 1e-6
          and abs(sim.vehicle.vx) < 1e-6,
          "x=%.2f（世界宽度 %.1f m，上限 %.2f）" % (
              sim.vehicle.x, sim.width, sim.width - sim.params.half_width))


def test_numerical_stability():
    import random
    random.seed(5)
    sim = make_sim()
    command = Command()
    bad = False
    for i in range(int(30.0 / sim.step_dt)):
        if i % 60 == 0:
            command = Command(
                throttle=random.random() < 0.6, brake=random.random() < 0.2,
                left=random.random() < 0.5, right=random.random() < 0.5)
        telem = sim.step(command)
        for value in (telem.vx, telem.vy, telem.yaw_rate, telem.rpm,
                      telem.a_long, telem.a_lat, telem.slip_amount):
            if math.isnan(value) or math.isinf(value):
                bad = True
    check("随机驾驶 30 秒无 NaN/Inf", not bad)


def test_steering_limit_sanity():
    sim = make_sim()
    radius_min = sim.params.radius_min
    check("几何最小转弯半径在真车量级（3.5~6 m）",
          3.5 <= radius_min <= 6.0,
          "%.2f m（轴距 %.2f m，最大前轮转角 %.1f deg）" % (
              radius_min, sim.params.wheelbase, sim.params.max_steer_deg))


def test_world_size_comes_from_world_config():
    config = copy.deepcopy(DEFAULT_CONFIG)
    config["world"] = {"width_m": 500.0, "height_m": 320.0}
    config["window"]["width"] = 800
    config["window"]["height"] = 600
    config["render"]["pixels_per_meter"] = 3.0
    sim = Simulation(config)
    check("世界尺寸来自 world.width_m/height_m，与窗口像素无关",
          abs(sim.width - 500.0) < 1e-9 and abs(sim.height - 320.0) < 1e-9,
          "world=%.1f×%.1f m，窗口=800×600 px，缩放=3 px/m" % (
              sim.width, sim.height))


def test_pixels_do_not_affect_physics():
    def run(display_style):
        config = copy.deepcopy(DEFAULT_CONFIG)
        config["world"] = {"width_m": 800.0, "height_m": 800.0}
        config["window"]["width"] = display_style[0]
        config["window"]["height"] = display_style[1]
        config["render"]["pixels_per_meter"] = display_style[2]
        config["render"]["follow_car"] = display_style[3]
        sim = Simulation(config)
        t = 0.0
        while t < 2.0:
            sim.step_raw(0.9, 0.0, 0.5)
            t += sim.step_dt
        return (sim.vehicle.x, sim.vehicle.y, sim.vehicle.heading,
                sim.telemetry.vx, sim.telemetry.vy)

    small = run((800, 600, 4.0, False))
    large = run((1920, 1080, 40.0, True))
    diffs = [abs(a - b) for a, b in zip(small, large)]
    check("窗口大小/像素缩放/相机跟随都不影响物理结果",
          max(diffs) < 1e-9,
          "最大差异 %.3g（位置 m / 航向 rad / 速度 m/s）" % max(diffs))


def test_camera_mapping():
    camera = Camera(1440, 900, 129.6, 81.0, 1440.0 / 129.6, follow=True)
    camera.update(64.8, 40.5)
    sx, sy = camera.world_to_screen(64.8, 40.5)
    view_ok = (abs(camera.view_width_m - 129.6) < 1e-6
               and abs(camera.view_height_m - 81.0) < 1e-6)
    center_ok = abs(sx - 720.0) < 1e-6 and abs(sy - 450.0) < 1e-6

    follow = Camera(1440, 900, 400.0, 300.0, 1440.0 / 129.6, follow=True)
    follow.update(0.0, 0.0)
    clamped_ok = (abs(follow.center_x - 64.8) < 0.2
                  and abs(follow.center_y - 40.5) < 0.2)
    follow.update(200.0, 150.0)
    sx2, sy2 = follow.world_to_screen(200.0, 150.0)
    follow_ok = abs(sx2 - 720.0) < 1e-6 and abs(sy2 - 450.0) < 1e-6
    wx, wy = follow.screen_to_world(720.0, 450.0)
    roundtrip_ok = abs(wx - 200.0) < 1e-6 and abs(wy - 150.0) < 1e-6

    fixed = Camera(1440, 900, 400.0, 300.0, 1440.0 / 129.6, follow=False)
    fixed.update(400.0, 300.0)
    fixed_ok = abs(fixed.center_x - 200.0) < 1e-9 and abs(fixed.center_y - 150.0) < 1e-9
    check("相机换算正确：视野/居中/跟随夹取/固定相机/反算",
          view_ok and center_ok and clamped_ok and follow_ok and roundtrip_ok and fixed_ok,
          "视野 %.1f×%.1f m、中心映射 (%0.1f,%0.1f)、跟随夹取与反算通过" % (
              camera.view_width_m, camera.view_height_m, sx, sy))


def test_reverse_yaw_damping():
    """倒车时后轴侧向力必须提供偏航阻尼（V2.4 的 bug 会让 yaw 指数增长）。"""
    sim = make_sim()
    sim.toggle_reverse()
    sim.vehicle.vx = -6.0
    sim.vehicle.vy = 0.0
    sim.vehicle.yaw_rate = 0.8
    for _ in range(int(1.0 / sim.step_dt)):
        telem = sim.step_raw(0.0, 0.0, 0.0)
    check("倒车时偏航扰动会衰减（后轴阻尼正常）",
          abs(telem.yaw_rate) < 0.1,
          "yaw 0.80 -> %.3f rad/s（1 s 后）" % telem.yaw_rate)


def test_reverse_steer_release_stable():
    """倒挡带方向给油后松手：不应继续螺旋加速。"""
    sim = make_sim()
    sim.toggle_reverse()
    telem = drive_raw(sim, 0.4, 0.0, 0.8, 2.0)
    yaw_at_release = abs(telem.yaw_rate)
    max_after = 0.0
    for _ in range(int(1.5 / sim.step_dt)):
        telem = sim.step_raw(0.0, 0.0, 0.0)
        max_after = max(max_after, abs(telem.yaw_rate))
    check("倒挡转向+给油后松手：不会越转越快",
          max_after <= yaw_at_release * 1.25 + 0.05
          and abs(telem.yaw_rate) < 0.1,
          "松手时 yaw=%.2f deg/s，松手后峰值 %.2f deg/s，1.5 s 后 %.2f deg/s" % (
              math.degrees(yaw_at_release), math.degrees(max_after),
              math.degrees(abs(telem.yaw_rate))))


def test_brake_steer_stops():
    """前进中满舵+刹车，最后两个键都不松：车必须停下来，不能原地自转（V2.6 修复）。"""
    sim = make_sim()
    telemetry = None
    t = 0.0
    while t < 15.0:
        telemetry = sim.step(Command(throttle=True))
        t += sim.step_dt
        if telemetry.speed_abs * 3.6 >= 60.0:
            break
    max_yaw = 0.0
    min_vx = 1e9
    for _ in range(int(4.0 / sim.step_dt)):
        telemetry = sim.step_raw(0.0, 0.8, 1.0)
        max_yaw = max(max_yaw, abs(telemetry.yaw_rate))
        min_vx = min(min_vx, telemetry.vx)
    check("满舵+刹车一直不松：车最终停住、不原地打转、也不沿车头反方向后溜",
          telemetry.speed_abs < 0.05
          and abs(telemetry.yaw_rate) < 0.05
          and max_yaw < math.radians(360.0)
          and min_vx >= -1e-6,
          "4 s 后 speed=%.3f m/s，yaw=%.3f rad/s，过程最大 yaw=%.1f deg/s，min vx=%.6f" % (
              telemetry.speed_abs, telemetry.yaw_rate,
              math.degrees(max_yaw), min_vx))


# --------------------------------------------------------------------- 汇总
def main():
    tests = [
        test_idle,
        test_top_speed,
        test_acceleration,
        test_auto_shift,
        test_braking,
        test_engine_braking,
        test_wheelspin,
        test_grip_limit_cornering,
        test_grip_bound_random,
        test_low_speed_steering,
        test_standstill_steering,
        test_geometric_radius,
        test_reverse,
        test_dt_independence,
        test_wall_clamp,
        test_numerical_stability,
        test_steering_limit_sanity,
        test_world_size_comes_from_world_config,
        test_pixels_do_not_affect_physics,
        test_camera_mapping,
        test_reverse_yaw_damping,
        test_reverse_steer_release_stable,
        test_brake_steer_stops,
    ]
    for test in tests:
        test()
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
