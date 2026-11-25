# -*- coding: utf-8 -*-
"""赛道 / 旋转相机自检（不需要 pygame，纯数学 + cfg/tracks/track.json）。

跑法::

    python scripts/tests_track.py

验证：
- cfg/tracks/track.json 的尺寸/比例尺/起点/圈长；
- 车固定在屏幕正中、画面按实际速度方向朝上（前进/倒车都成立）；
- 低速冻结、角度连续不翻转；
- 撞墙沿墙滑动（去掉法向速度、保留切向速度），不瞬间停车。
"""
import copy
import json
import math
import os
import sys

SCRIPTS = os.path.dirname(os.path.abspath(__file__))
PROJECT = os.path.dirname(SCRIPTS)
sys.path.insert(0, SCRIPTS)

from minirace.benchmark import _brake_case
from minirace.camera import ChaseCamera
from minirace.config import DEFAULT_CONFIG
from minirace.laptiming import LapTimer, format_time
from minirace.sim import Simulation
from minirace.track import Track
from minirace.warnings import WrongWayMonitor
from minirace.zoom import adjust_level, zoom_factor, zoom_label
from minirace.presets import (apply as apply_preset, extract, load_custom,
                             load_preset, save_custom)

_results = []


def check(name, ok, detail=""):
    _results.append((name, bool(ok), detail))
    print("[%s] %s%s" % ("PASS" if ok else "FAIL", name,
                         ("  <- " + detail) if detail else ""))


def _load_track():
    with open(os.path.join(PROJECT, "cfg", "tracks", "track.json"), "r", encoding="utf-8") as handle:
        return json.load(handle)


def _track_sim():
    config = copy.deepcopy(DEFAULT_CONFIG)
    config["track"] = {"enabled": True, "file": "cfg/tracks/track.json",
                       "wall_slide_drag": 0.3, "wall_margin": 0.02,
                       "camera": {"pixels_per_meter": 6.0}}
    return Simulation(config, project_dir=PROJECT)


def test_track_geometry():
    data = _load_track()
    points = data["centerline"]
    xs = [point[0] for point in points]
    ys = [point[1] for point in points]
    length = 0.0
    for index in range(len(points)):
        x0, y0 = points[index]
        x1, y1 = points[(index + 1) % len(points)]
        length += math.hypot(x1 - x0, y1 - y0)
    check("赛道宽度 = 15 m", abs(data["width_m"] - 15.0) < 1e-6,
          "width=%.2f" % data["width_m"])
    check("中心线点足够密（4 m 间距）", len(points) > 1000,
          "%d 点，圈长 %.0f m" % (len(points), length))
    check("圈长按真实 5451 m 定标",
          abs(data["reference"].get("target_lap_length_m", 0.0) - 5451.0) < 0.1
          and abs(length - 5451.0) < 1.0,
          "px=%.0f, scale=%.4f m/px, lap=%.1f m" % (
              data["reference"]["t13_t14_straight_px"],
              data["reference"]["scale_m_per_px"], length))
    check("保留 T13-T14 1135 m 题目约束记录（示意图比例约 1180 m）",
          abs(data["reference"].get("requested_t13_t14_m", 0.0) - 1135.0) < 0.1,
          "as-built %.0f m" % data["reference"].get("t13_t14_straight_m", 0.0))
    check("起点记录为从 T1 端往回 1/3",
          abs(data["reference"].get("start_fraction_from_t1", 0.0) - 0.33) < 1e-6,
          "fraction_from_t1=%.2f" % data["reference"].get(
              "start_fraction_from_t1", 0.0))
    check("圈长在真实上海赛道量级（5.0~5.6 km）",
          5000.0 < length < 5600.0, "%.0f m" % length)
    check("世界包围盒远大于窗口",
          (max(xs) - min(xs)) > 1000.0 and (max(ys) - min(ys)) > 600.0,
          "%.0f × %.0f m" % (max(xs) - min(xs), max(ys) - min(ys)))

    # 起点在中心线原点，朝向沿赛道切线
    start = data["start"]
    centerline = points
    closest = min(centerline, key=lambda point: math.hypot(point[0] - start["x"],
                                                          point[1] - start["y"]))
    check("起点在中心线上", math.hypot(closest[0] - start["x"],
                                       closest[1] - start["y"]) < 0.2,
          "最近点 (%.2f, %.2f)" % (closest[0], closest[1]))
    given = start["heading_rad"]
    # 找到起点索引，用前后点求切线
    index = centerline.index([round(start["x"], 3), round(start["y"], 3)]) \
        if [round(start["x"], 3), round(start["y"], 3)] in centerline else 0
    before = centerline[(index - 1) % len(centerline)]
    after = centerline[(index + 1) % len(centerline)]
    tangent = math.atan2(after[1] - before[1], after[0] - before[0])
    delta = abs((given - tangent + math.pi) % (2.0 * math.pi) - math.pi)
    check("起点朝向 = 赛道切线方向", delta < math.radians(2.0),
          "给定 %.1f°，切线 %.1f°" % (math.degrees(given), math.degrees(tangent)))


def test_maps_config():
    with open(os.path.join(PROJECT, "cfg", "sim.json"), "r", encoding="utf-8") as handle:
        config = json.load(handle)
    maps = config.get("maps", {})
    ids = [item.get("id") for item in maps.get("list", [])]
    numbers = [item.get("number") for item in maps.get("list", [])]
    check("地图顺序：圆形(0) / 椭圆(1) / 上海(2) / 宝山(3) / 自动(4-6)",
          ids == ["circle", "oval", "shanghai", "baoshan",
                  "auto_1", "auto_2", "auto_3"]
          and numbers == [0, 1, 2, 3, 4, 5, 6],
          "ids=%s numbers=%s" % (ids, numbers))
    for item in maps.get("list", []):
        path = os.path.join(PROJECT, item.get("file", ""))
        check("地图文件存在：%s" % item.get("id"), os.path.isfile(path),
              item.get("file", ""))
    with open(os.path.join(PROJECT, "cfg", "tracks", "track_oval.json"), "r",
              encoding="utf-8") as handle:
        oval = json.load(handle)
    check("椭圆赛道全长约 4434.7 m",
          abs(oval["reference"]["lap_length_m"] - 4434.7) < 0.2,
          "lap=%.1f m" % oval["reference"]["lap_length_m"])
    check("椭圆赛道：直道 1000 m、外径 800 m、宽 25 m",
          abs(oval["reference"]["straight_length_m"] - 1000.0) < 1e-6
          and abs(oval["reference"]["outer_diameter_m"] - 800.0) < 1e-6
          and abs(oval["width_m"] - 25.0) < 1e-6,
          "lap=%.1f" % oval["reference"]["lap_length_m"])
    with open(os.path.join(PROJECT, "cfg", "tracks", "track.json"), "r",
              encoding="utf-8") as handle:
        shanghai = json.load(handle)
    check("上海全长约 5451 m",
          abs(shanghai["reference"]["lap_length_m"] - 5451.0) < 1.0,
          "lap=%.1f m" % shanghai["reference"]["lap_length_m"])
    check("椭圆赛道：两个弯 T1/T2，起点在 T1 前 1/3",
          len(oval["corners"]) == 2
          and abs(oval["reference"].get("start_fraction_before_t1", 0.0)
                  - 1.0 / 3.0) < 1e-6,
          "corners=%d" % len(oval["corners"]))
    with open(os.path.join(PROJECT, "cfg", "tracks", "track_circle.json"), "r",
              encoding="utf-8") as handle:
        circle = json.load(handle)
    check("圆形试车场：Ø400 m 空地 / Ø360 m 虚线",
          circle["kind"] == "circle"
          and abs(circle["outer_radius_m"] * 2.0 - 400.0) < 1e-6
          and abs(circle["guide_radius_m"] * 2.0 - 360.0) < 1e-6,
          "outer=%.0f, guide=%.0f" % (
              circle["outer_radius_m"] * 2.0, circle["guide_radius_m"] * 2.0))
    check("圆形试车场：起点在圆心正上方、F5 回起点",
          abs(circle["start"]["x"]) < 1e-9
          and abs(circle["start"]["y"] - 180.0) < 1e-6
          and bool(circle["reference"].get("reset_to_start")),
          "start=(%.1f, %.1f), heading=%.1f°" % (
              circle["start"]["x"], circle["start"]["y"],
              math.degrees(circle["start"]["heading_rad"])))


def test_corner_elements():
    config = copy.deepcopy(DEFAULT_CONFIG)
    config["track"] = {"enabled": True, "file": "cfg/tracks/track.json"}
    track = Track(PROJECT, config)
    elements = track.elements
    check("上海弯/直道元素交替且完整覆盖",
          len(elements) == 32
          and all(elements[i]["type"] != elements[i + 1]["type"]
                  for i in range(0, len(elements), 2)),
          "%d 个元素" % len(elements))
    count = len(track.points)
    counts = [0] * count

    def contains(start, end, index):
        return (start <= index <= end) if start <= end else (index >= start or index <= end)

    for element in elements:
        for index in range(count):
            if contains(element["start"], element["end"], index):
                counts[index] += 1
    check("弯/直道元素无重叠/无遗漏", min(counts) == 1 and max(counts) == 1,
          "覆盖 %d 个点" % sum(counts))

    element = next(item for item in elements if item["label"] == "T2")
    middle = (element["start"] + element["end"]) // 2
    point = track.points[middle]
    window = track.element_window_at(point[0], point[1])
    check("弯中窗口：T1 - T2 - T3，中间为 T2",
          window is not None and window[0] == ["T1", "-", "T2", "-", "T3"]
          and window[2] == 2,
          repr(window[0] if window else None))
    straight = next(item for item in elements
                    if item["type"] == "straight"
                    and item["start"] == element["end"] + 1)
    track._last_index = 0
    point = track.points[(straight["start"] + straight["end"]) // 2]
    window = track.element_window_at(point[0], point[1])
    check("直道窗口：- T2 - T3 -（中间为直道）",
          window is not None and window[0] == ["-", "T2", "-", "T3", "-"],
          repr(window[0] if window else None))

    oval_config = copy.deepcopy(DEFAULT_CONFIG)
    oval_config["track"] = {"enabled": True, "file": "cfg/tracks/track_oval.json"}
    oval = Track(PROJECT, oval_config)
    check("椭圆赛道只有 T1/T2 两个弯", len(oval.elements) == 4,
          "%d 个元素" % len(oval.elements))
    element = next(item for item in oval.elements if item["label"] == "T1")
    point = oval.points[(element["start"] + element["end"]) // 2]
    window = oval.element_window_at(point[0], point[1])
    check("椭圆 T1 窗口：T2 - T1 - T2",
          window is not None and window[0] == ["T2", "-", "T1", "-", "T2"],
          repr(window[0] if window else None))


def test_circle_wall():
    config = copy.deepcopy(DEFAULT_CONFIG)
    config["track"] = {"enabled": True, "file": "cfg/tracks/track_circle.json",
                       "wall_slide_drag": 0.3, "wall_margin": 0.02}
    sim = Simulation(config, project_dir=PROJECT)
    track = sim.track
    check("圆形试车场能加载", track is not None and track.kind == "circle",
          "kind=%s" % (track.kind if track else None))
    # 在顶部外侧（半径 199 m）以 45° 撞外侧墙：应推回并保留切向速度
    sim.vehicle.x = 0.0
    sim.vehicle.y = 199.0
    heading = math.radians(135.0)
    sim.vehicle.heading = heading
    sim.vehicle.vx = 10.0
    sim.vehicle.vy = 0.0
    telemetry = sim.step_raw(0.0, 0.0, 0.0)
    radius = math.hypot(sim.vehicle.x, sim.vehicle.y)
    cos_h = math.cos(heading)
    sin_h = math.sin(heading)
    world_vx = sim.vehicle.vx * cos_h - sim.vehicle.vy * sin_h
    world_vy = sim.vehicle.vx * sin_h + sim.vehicle.vy * cos_h
    radial = math.hypot(sim.vehicle.x, sim.vehicle.y)
    ux = sim.vehicle.x / radial if radial > 1e-9 else 0.0
    uy = sim.vehicle.y / radial if radial > 1e-9 else 0.0
    outward = world_vx * ux + world_vy * uy
    check("圆形试车场撞外墙被推回", telemetry.wall_hit and radius <= 200.0,
          "半径 %.2f m，wall_hit=%s" % (radius, telemetry.wall_hit))
    check("圆形试车场撞墙保留切向速度（沿墙滑动）",
          math.hypot(world_vx, world_vy) > 4.0 and outward <= 0.1,
          "撞后速度 %.2f m/s，法向 %.2f" % (math.hypot(world_vx, world_vy),
                                             outward))


def test_lap_timer():
    config = copy.deepcopy(DEFAULT_CONFIG)
    config["track"] = {"enabled": True, "file": "cfg/tracks/track.json"}
    track = Track(PROJECT, config)
    timer = LapTimer(track)
    points = track.points
    count = len(points)
    check("上海赛道计圈开启，起始 LAP 1 / 0.000", timer.enabled and timer.lap == 1
          and timer.current_time(0.0) == 0.0,
          "enabled=%s lap=%d" % (timer.enabled, timer.lap))
    time_s = 0.0
    step = 0.12
    for index in range(1, count + 2):
        time_s += step
        timer.update(time_s, points[index % count][0], points[index % count][1])
    check("完成一圈后 LAP+1 且记录最快圈",
          timer.lap == 2 and timer.best is not None,
          "lap=%d, best=%.3f s" % (timer.lap, timer.best or 0.0))
    first_best = timer.best
    step = 0.06
    for index in range(1, count + 2):
        time_s += step
        timer.update(time_s, points[(count + index) % count][0],
                     points[(count + index) % count][1])
    check("第二圈更快时最快圈被刷新",
          timer.lap == 3 and timer.best < first_best,
          "best %.3f -> %.3f s" % (first_best, timer.best))
    check("圈速格式化 mm:ss.mmm / 空成绩占位",
          format_time(83.456) == "01:23.456" and format_time(None) == "--:--:--",
          "%s / %s" % (format_time(83.456), format_time(None)))

    circle_config = copy.deepcopy(DEFAULT_CONFIG)
    circle_config["track"] = {"enabled": True, "file": "cfg/tracks/track_circle.json"}
    circle_timer = LapTimer(Track(PROJECT, circle_config))
    check("圆形试车场不计圈", not circle_timer.enabled, "enabled=False")


def _place_point(track, timer, along, perp, time_s):
    x = timer._start_x + timer._tangent[0] * along + timer._normal[0] * perp
    y = timer._start_y + timer._tangent[1] * along + timer._normal[1] * perp
    return timer.update(time_s, x, y)


def test_lap_timer_home_and_cooldown():
    config = copy.deepcopy(DEFAULT_CONFIG)
    config["track"] = {"enabled": True, "file": "cfg/tracks/track.json"}
    timer = LapTimer(Track(PROJECT, config))
    _place_point(None, timer, 30.0, 0.0, 0.0)      # 武装
    _place_point(None, timer, -1.0, 0.0, 9.9)
    _place_point(None, timer, 0.2, 0.0, 10.0)      # 正常过线 -> LAP 2
    check("正常过线：LAP+1 并记圈", timer.lap == 2 and timer.best is not None,
          "lap=%d best=%.1f" % (timer.lap, timer.best or 0.0))
    _place_point(None, timer, 30.0, 0.0, 10.5)     # 重新武装
    _place_point(None, timer, -1.0, 0.0, 11.0)
    _place_point(None, timer, 0.2, 0.0, 11.1)      # 5 s 内倒车再撞线 -> 忽略
    check("过线 5 秒内反向/重复撞线不改变圈数和计时起点",
          timer.lap == 2 and abs(timer._lap_start - 10.0) < 1e-9,
          "lap=%d lap_start=%.1f" % (timer.lap, timer._lap_start))
    _place_point(None, timer, 30.0, 0.0, 15.0)     # 武装
    _place_point(None, timer, -1.0, 0.0, 15.5)
    _place_point(None, timer, 0.2, 0.0, 15.6)      # 超过 5 s -> 正常计圈
    check("冷却结束后再次撞线正常计圈", timer.lap == 3,
          "lap=%d" % timer.lap)
    _place_point(None, timer, 30.0, 0.0, 16.0)
    best_before = timer.best
    timer.home_reset(20.0)
    check("HOME：圈数+1、当前圈时间清零、旧圈用时丢弃",
          timer.lap == 4 and timer.current_time(20.0) == 0.0
          and timer.best == best_before,
          "lap=%d best=%.1f" % (timer.lap, timer.best or 0.0))
    _place_point(None, timer, 30.0, 0.0, 21.0)     # HOME 后仍需重新武装
    _place_point(None, timer, -1.0, 0.0, 40.0)
    _place_point(None, timer, 0.2, 0.0, 40.1)
    check("HOME 后正常过线重新计圈", timer.lap == 5,
          "lap=%d" % timer.lap)


def test_wrong_way_monitor():
    monitor = WrongWayMonitor()
    error = math.radians(130.0)
    active = visible = False
    beeps = 0
    for _ in range(14):
        active, visible, beep = monitor.update(error, 0.1)
        beeps += int(beep)
    check("逆行 1.5 秒内不提示", not active, "active=%s" % active)
    active, visible, beep = monitor.update(error, 0.1)
    beeps += int(beep)
    check("逆行 1.5 秒后进入显示并响一声",
          active and visible and beep and beeps == 1,
          "active=%s visible=%s beeps=%d" % (active, visible, beeps))
    for _ in range(10):
        monitor.update(error, 0.1)
    check("提示显示 1 秒后熄灭 1 秒", not monitor.visible,
          "visible=%s" % monitor.visible)
    for _ in range(10):
        monitor.update(error, 0.1)
    check("随后再次显示", monitor.visible, "visible=%s" % monitor.visible)
    active, visible, beep = monitor.update(math.radians(60.0), 0.1)
    check("车头转回 120 度内后停止并重置计时",
          not active and not visible and not beep and monitor.time_wrong == 0.0,
          "time_wrong=%.2f" % monitor.time_wrong)


def test_vehicle_presets():
    import shutil
    import tempfile
    config = copy.deepcopy(DEFAULT_CONFIG)
    config["vehicle"]["mass"] = 1450.0
    first = load_preset(PROJECT, 1)
    second = load_preset(PROJECT, 2)
    third = load_preset(PROJECT, 3)
    first_peak = max(pair[1] for pair in first["engine"]["torque_curve"])
    second_peak = max(pair[1] for pair in second["engine"]["torque_curve"])
    check("车辆预设：1 买菜车 / 2 性能车 / 3 超跑 文件可加载",
          first.get("vehicle", {}).get("mass") == 1450.0
          and second.get("vehicle", {}).get("mass") == 1350.0
          and third.get("vehicle", {}).get("mass") == 1450.0,
          "mass 1/2/3=%.0f/%.0f/%.0f" % (
              first.get("vehicle", {}).get("mass", 0.0),
              second.get("vehicle", {}).get("mass", 0.0),
              third.get("vehicle", {}).get("mass", 0.0)))
    check("性能车预设：峰值扭矩提高到买菜车的 1.25 倍",
          abs(second_peak / first_peak - 1.25) < 1e-9,
          "%.1f -> %.1f N·m" % (first_peak, second_peak))
    second_ratios = second["drivetrain"]["gear_ratios"]
    check("性能车预设：7 个前进挡、齿比更密且保持首/末齿比",
          len(second_ratios) == 7
          and all(second_ratios[i] > second_ratios[i + 1]
                  for i in range(6))
          and abs(second_ratios[0] - 3.10) < 1e-9
          and abs(second_ratios[-1] - 0.85) < 1e-9,
          ",".join("%.2f" % value for value in second_ratios))
    third_ratios = third["drivetrain"]["gear_ratios"]
    third_flat = {section: {key: value for key, value in third[section].items()
                            if not (section == "drivetrain" and key == "gear_ratios")}
                  for section in third}
    first_flat = {section: {key: value for key, value in first[section].items()
                            if not (section == "drivetrain" and key == "gear_ratios")}
                  for section in first}
    check("超跑预设：8 个前进挡，除齿比外仍是买菜车参数",
          len(third_ratios) == 8
          and all(third_ratios[i] > third_ratios[i + 1]
                  for i in range(7))
          and third_flat == first_flat,
          ",".join("%.2f" % value for value in third_ratios))
    perf = copy.deepcopy(DEFAULT_CONFIG)
    for section, group in second.items():
        perf.setdefault(section, {}).update(copy.deepcopy(group))
    brake = _brake_case(perf, target_kmh=100.0)
    check("性能车预设：100-0 制动距离约 35 m",
          34.0 <= brake["distance"] <= 36.0,
          "%.1f m / %.2f s" % (brake["distance"], brake["time"]))
    folder = tempfile.mkdtemp(prefix="minirace_preset_")
    try:
        path = os.path.join(folder, "custom.json")
        save_custom(path, apply_preset(config, first))
        loaded = load_custom(path)
        check("自定义参数可保存并加载回来",
              loaded.get("vehicle", {}).get("mass") == 1450.0
              and loaded.get("brakes", {}).get("decel_limit") == 13.5,
              "mass=%.0f" % loaded.get("vehicle", {}).get("mass", 0.0))
        check("自定义存档只含可调参数（不含 maps/audio）",
              "maps" not in loaded and "audio" not in loaded,
              "sections=%s" % sorted(loaded))
    finally:
        shutil.rmtree(folder, ignore_errors=True)


def test_display_zoom():
    levels = [adjust_level(0, delta) for delta in range(-4, 5)]
    check("显示倍率：7 档，最大 +3=2x、最小 -3=0.5x",
          levels == [-3, -3, -2, -1, 0, 1, 2, 3, 3]
          and abs(zoom_factor(3) - 2.0) < 1e-12
          and abs(zoom_factor(-3) - 0.5) < 1e-12,
          "labels=%s" % ",".join(zoom_label(level) or "0" for level in levels[1:-1]))
    check("显示倍率：默认档无标签，(+-n) 标签格式正确",
          zoom_label(0) == "" and zoom_label(1) == "(+1)"
          and zoom_label(-2) == "(-2)" and zoom_label(3) == "(+3)",
          "%s / %s / %s" % (zoom_label(1), zoom_label(-2), zoom_label(3)))


def test_camera_velocity_up():
    camera = ChaseCamera(1440.0, 900.0, 6.0, angle_rate=20.0,
                         freeze_speed=1.5, max_angle_rate=100.0)
    camera.reset_angle(0.0)
    dt = 0.05
    world_angle = math.radians(35.0)
    speed = 20.0
    for _ in range(80):
        camera.update(0.0, 0.0, speed * math.cos(world_angle),
                      speed * math.sin(world_angle), speed, dt)
    car_screen = camera.world_to_screen(0.0, 0.0)
    check("车固定在屏幕正中（±10%）",
          abs(car_screen[0] - 720.0) < 1.0 and abs(car_screen[1] - 450.0) < 1.0,
          "screen=(%.3f, %.3f)" % car_screen)
    forward = camera.world_to_screen(speed * math.cos(world_angle),
                                     speed * math.sin(world_angle))
    check("前进时速度方向朝上",
          abs(forward[0] - 720.0) < 0.5 and forward[1] < 450.0,
          "velocity point=(%.2f, %.2f)" % forward)

    # 倒挡：相机朝向与前进相反，速度向量应指向屏幕下方
    world_angle = math.radians(215.0)
    for _ in range(100):
        camera.update(0.0, 0.0, speed * math.cos(world_angle),
                      speed * math.sin(world_angle), speed, dt,
                      reverse=True)
    velocity = camera.world_to_screen(speed * math.cos(world_angle),
                                      speed * math.sin(world_angle))
    check("倒挡时相机翻转：速度向量朝下（前进时朝上）",
          abs(velocity[0] - 720.0) < 1.0 and velocity[1] > 450.0,
          "velocity point=(%.2f, %.2f)" % velocity)


def test_camera_freeze_and_continuity():
    camera = ChaseCamera(1440.0, 900.0, 6.0, angle_rate=6.0,
                         freeze_speed=1.5, max_angle_rate=6.0)
    camera.reset_angle(math.radians(10.0))
    # 加速到有速度，角度跟随
    for _ in range(60):
        camera.update(0.0, 0.0, 20.0, 0.0, 20.0, 1.0 / 60.0)
    moving_angle = camera.angle
    # 低速/停车：角度冻结
    for _ in range(30):
        camera.update(0.0, 0.0, 0.2, 0.0, 0.2, 1.0 / 60.0)
    check("低速时相机角度冻结",
          abs(camera.angle - moving_angle) < 1e-9 and camera.frozen,
          "angle %.2f° -> %.2f°" % (math.degrees(moving_angle),
                                    math.degrees(camera.angle)))

    # 角度跨 ±180° 时用最短路径，不整圈翻转
    camera.reset_angle(math.radians(179.0))
    camera.update(0.0, 0.0, -20.0, 1.0, math.hypot(20.0, 1.0), 1.0 / 60.0)
    delta = abs((camera.angle - math.radians(179.0) + math.pi)
                % (2.0 * math.pi) - math.pi)
    check("跨 ±180° 时角度连续（不做 360° 翻转）",
          delta < math.radians(30.0),
          "一步变化 %.2f°" % math.degrees(delta))


def test_wall_slide():
    sim = _track_sim()
    track = sim.track
    start_x, start_y, heading = track.start
    tangent = (math.cos(heading), math.sin(heading))
    normal = (-tangent[1], tangent[0])
    allowed = track.width_m * 0.5 - sim.vehicle.p.half_width - track.margin
    # 把车放到外侧边界附近，世界速度斜着撞墙
    sim.vehicle.x = start_x + normal[0] * (allowed + 0.4)
    sim.vehicle.y = start_y + normal[1] * (allowed + 0.4)
    sim.vehicle.heading = heading
    world_vx = (tangent[0] * 8.0 + normal[0] * 6.0)
    world_vy = (tangent[1] * 8.0 + normal[1] * 6.0)
    cos_h = math.cos(heading)
    sin_h = math.sin(heading)
    sim.vehicle.vx = world_vx * cos_h + world_vy * sin_h
    sim.vehicle.vy = -world_vx * sin_h + world_vy * cos_h
    telemetry = sim.step_raw(0.0, 0.0, 0.0)
    nearest = track.nearest(sim.vehicle.x, sim.vehicle.y, hint_index=0)
    distance = nearest[0]
    relative = sim.vehicle.heading - heading
    support = (abs(math.cos(relative)) * sim.vehicle.p.half_width
               + abs(math.sin(relative)) * sim.vehicle.p.half_length)
    limit = track.width_m * 0.5 - support - track.margin
    # 世界速度的墙外分量
    cos_h = math.cos(sim.vehicle.heading)
    sin_h = math.sin(sim.vehicle.heading)
    wvx = sim.vehicle.vx * cos_h - sim.vehicle.vy * sin_h
    wvy = sim.vehicle.vx * sin_h + sim.vehicle.vy * cos_h
    outward = wvx * normal[0] + wvy * normal[1]
    speed = math.hypot(wvx, wvy)
    check("撞墙被推回赛道内（不穿墙）", distance <= limit + 0.05,
          "到中心线 %.2f m（上限 %.2f m）" % (distance, limit))
    check("撞墙后去掉法向速度", outward <= 0.3,
          "法向速度 %.2f m/s（贴墙一步后的残量）" % outward)
    check("撞墙后保留切向速度（沿墙滑动，不瞬停）", speed > 3.0,
          "撞后速度 %.2f m/s" % speed)
    check("撞墙会设置 telemetry.wall_hit", telemetry.wall_hit,
          "wall_hit=%s" % telemetry.wall_hit)


def main():
    try:
        test_track_geometry()
        test_maps_config()
        test_corner_elements()
        test_circle_wall()
        test_lap_timer()
        test_lap_timer_home_and_cooldown()
        test_wrong_way_monitor()
        test_vehicle_presets()
        test_display_zoom()
        test_camera_velocity_up()
        test_camera_freeze_and_continuity()
        test_wall_slide()
    except Exception as exc:  # noqa: BLE001
        import traceback
        traceback.print_exc()
        print("测试异常：%s" % exc)
        return 1
    failed = [name for name, ok, _detail in _results if not ok]
    print()
    print("%d/%d 项通过" % (len(_results) - len(failed), len(_results)))
    if failed:
        print("失败：")
        for name in failed:
            print("  - %s" % name)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
