# -*- coding: utf-8 -*-
"""配置读取：``cfg/sim.json`` 与内置默认值深合并。

- 文件不存在时，自动写出内置默认配置；
- 文件损坏或类型不对时，退回默认值并在 ``logs/run.log`` 里留下 warning；
- 用户只需要改 ``cfg/sim.json``，代码里不写死参数。

单位与坐标（V2.2 起彻底"米/像素"分离）
--------------------------------------
- 物理/世界：**米、秒、千克、牛顿、弧度**；世界大小由 ``world.width_m / height_m``
  直接以米给出，和窗口像素无关。
- 渲染：窗口大小用像素（``window``）；显示缩放用 ``render.pixels_per_meter``
  （px/m，只影响画面），相机是否跟随车辆用 ``render.follow_car``。
- 改窗口大小、显示缩放、是否跟随，都不会改变任何物理结果。
"""
import copy
import json
import logging
import os

LOG = logging.getLogger(__name__)

DEFAULT_CONFIG = {
    "version": 4,
    "window": {
        "width": 1440,
        "height": 900,
        "caption": "Mini Race 2 - Vehicle Simulator",
        "fps": 60,
    },
    "world": {
        # 世界尺寸，单位米（默认 129.6 × 81 m，对应 1440×900 px @ 11.111 px/m）
        "width_m": 129.6,
        "height_m": 81.0,
    },
    # 赛道模式（V3.0）：由 scripts/build_track.py 从 images/track.jpg 生成的 cfg/tracks/track.json
    # 提供中心线/宽度/起点；关掉时退回旧版矩形世界。
    "track": {
        "enabled": False,
        "file": "cfg/tracks/track.json",
        "wall_slide_drag": 0.3,
        "wall_margin": 0.02,
        "camera": {
            "pixels_per_meter": 6.0,
            "angle_rate": 5.0,
            "max_angle_rate": 6.0,
            "freeze_speed": 1.5,
            "center_tolerance": 0.10,
        },
    },
    # 地图列表（V3.1）：F2 切换，开局默认加载上次退出的地图起点。
    "maps": {
        "default": "shanghai",
        "session_file": "data/last_map.json",
        "list": [
            {
                "id": "circle",
                "number": 0,
                "name": "圆形试车场",
                "display_name": "CIRCLE TEST TRACK",
                "file": "cfg/tracks/track_circle.json",
                "pixels_per_meter": 6.0,
            },
            {
                "id": "oval",
                "number": 1,
                "name": "椭圆赛道",
                "display_name": "OVAL TEST TRACK",
                "file": "cfg/tracks/track_oval.json",
                "pixels_per_meter": 6.0,
            },
            {
                "id": "shanghai",
                "number": 2,
                "name": "上海国际赛车场",
                "display_name": "SHANGHAI CIRCUIT",
                "file": "cfg/tracks/track.json",
                "pixels_per_meter": 6.0,
            },
        ],
    },
    "scale": {
        "gravity": 9.81,
    },
    "vehicle": {
        # 固定物理步长；2 自由度车辆 + 轮胎侧偏对步长更敏感，默认 240 Hz
        "step_hz": 240,
        "max_substeps": 16,
        # 整车质量与横摆转动惯量
        "mass": 1450.0,
        "inertia": 2900.0,
        # 轴距、静态前轴荷比例、质心高度
        "wheelbase": 2.70,
        "front_weight_fraction": 0.52,
        "cg_height": 0.40,
        "wheel_radius": 0.32,
        # 方向盘打满时前轮最大转角（度）
        "max_steer_deg": 33.5,
        # 车身半宽/半长（米），仅用于世界边界占位判定
        "half_width": 0.95,
        "half_length": 2.25,
        # 只有纵向速度低于该值才允许换 R/D
        "shift_max_speed": 1.5,
        # 低于该速度视为静止
        "stop_speed": 0.05,
    },
    "tires": {
        # 附着系数（摩擦圆半径 = friction * Fz）
        "friction": 1.10,
        # 侧偏刚度系数：C_alpha = coefficient * Fz * scale（单位 1/rad，按轴合计）
        "cornering_stiffness": 16.0,
        # 轮胎侧向力曲线形状（简化魔术公式 sin(C·atan(B·α))）：
        # C 越大，峰值侧偏角越小、越过峰值后衰减越明显
        "tire_shape": 1.6,
        "front_stiffness_scale": 1.00,
        "rear_stiffness_scale": 1.00,
        # 轮胎载荷敏感性：load_factor = 1 - k*(Fz/Fz_static - 1)
        # 载荷越大单位载荷抓地力越低（抑制制动/转弯时"越压越抓"的失控反馈）
        "load_sensitivity": 0.10,
        # 前后轴附着系数微调（1.0 = 相同；前小后大 => 推头/稳定）
        "front_friction_scale": 1.00,
        "rear_friction_scale": 1.00,
        # 低速时轮胎力按 |vx| / low_speed_fade 线性淡入，避免静止时"打方向就自转"
        "low_speed_fade": 1.2,
        # 低速轮胎"蹭地"阻尼：|vx| < scrub_speed 时按比例衰减 vy 与横摆角速度。
        # 速度趋零时模型里没有静态摩擦，没有它刹车+打方向会原地自转不停。
        "scrub_speed": 1.2,          # m/s
        "scrub_yaw_damping": 8.0,    # 1/s
        "scrub_lateral_damping": 10.0,  # 1/s
    },
    "drivetrain": {
        # 驱动分配：0 = 纯后驱，1 = 纯前驱，0.50 = 全时四驱前后各半
        "drive_split_front": 0.50,
        "final_drive": 5.50,
        "gear_ratios": [3.10, 2.35, 1.85, 1.55, 1.32, 0.85],
        "reverse_ratio": 3.20,
        "efficiency": 0.90,
        "idle_rpm": 900.0,
        "redline_rpm": 7000.0,
        # 离合打滑（起步）时的目标转速上限
        "launch_rpm": 3000.0,
        "shift_up_rpm": 6700.0,
        "shift_down_rpm": 2500.0,
        # 大油门低转速时的降挡（kickdown）转速阈值
        "kickdown_rpm": 3300.0,
        # 换挡过程中断油的时间，以及两次换挡的最小间隔（都可调）
        "shift_time": 0.18,
        "shift_interval": 0.30,
    },
    "engine": {
        # 发动机外特性扭矩曲线 [[rpm, N·m], ...]，线性插值
        "torque_curve": [
            [1000.0, 234.6],
            [2000.0, 306.0],
            [3000.0, 336.6],
            [4500.0, 357.0],
            [5500.0, 336.6],
            [6500.0, 285.6],
            [7200.0, 224.4],
        ],
        # 内摩擦扭矩：T_fric = base + per_rpm * rpm（油门关闭时就是"发动机制动"）
        "friction_base": 16.0,
        "friction_per_rpm": 0.005,
    },
    "aero": {
        # 空气阻力 F = -drag_coefficient * v^2（N，按 N/(m/s)^2 计）
        "drag_coefficient": 0.42,
        # 滚动阻力系数（乘以 m*g）
        "rolling_resistance": 0.015,
    },
    "brakes": {
        # brake_pos = 1.0 时的目标减速度（m/s^2）；实际受轮胎附着限制
        "decel_limit": 13.5,
        # 前轴制动力占比
        "front_bias": 0.62,
    },
    "controls": {
        # 踏板 / 方向盘的"人"模型：按下速率、松开回弹倍率、死区
        "sensitivity_throttle": 1.8,
        "sensitivity_brake": 1.8,
        "sensitivity_steer": 2.0,
        "spring_back": 2.1,
        "throttle_limit": 0.9,
        "brake_limit": 0.8,
        "steer_dead_zone": 0.1,
    },
    "audio": {
        "enabled": True,
        "master_volume": 0.35,
        "engine_volume": 0.9,
        "slip_volume": 0.7,
        # 可选采样包：文件存在就用它，否则回退到程序化合成声。
        # 素材放 sounds/（.gitignore 已忽略，不随代码提交）；只在本机个人使用。
        "sample_pack": {
            "enabled": True,
            "engine_file": "sounds/引擎声音.wav",
            "loop_start_s": None,
            "loop_seconds": 0.5,
            "base_rpm": 2400.0,
            "min_pitch_factor": 0.45,
            "max_pitch_factor": 2.60,
            "target_peak": 0.55,
        },
    },
    "diagnostics": {
        # --diagnose / F9 时的异常判定阈值
        # |Δvx| / dt 超过该值视为单步速度跳变（m/s²）
        "jump_accel_threshold": 50.0,
        # |Δheading| / dt 超过该值视为航向跳变（rad/s）
        "heading_rate_threshold": 20.0,
        # 换挡抖动：window 秒内换挡次数 >= changes 次
        "gear_hunting_window": 2.0,
        "gear_hunting_changes": 4,
        # 连续打滑/侧滑：slip_amount >= threshold 且持续 saturation_time 秒
        "slip_threshold": 0.5,
        "grip_saturation_time": 1.0,
        # 无转向输入时横摆角速度仍过大（自旋/螺旋的特征）
        "yaw_runaway_threshold": 2.0,   # rad/s
        "yaw_runaway_steer": 0.15,      # |steer| 低于此值视为"没有打方向"
        "yaw_runaway_time": 0.5,        # s，持续这么久才记事件
        # 摘要里列出的最近事件条数
        "max_recent_events": 20,
    },
    "render": {
        "background": "images/track.jpg",
        "car_sprite": "images/red-car-small.png",
        # 显示缩放：每米多少像素。只影响画面，不影响物理。
        "pixels_per_meter": 11.111111,
        # 世界比视野大时自动跟随车辆；世界小于视野时相机固定在世界中心。
        "follow_car": True,
        "trail_points": 300,
        "show_hud": True,
        "show_help": True,
        "show_trail": True,
        # 右下角赛道缩略图（V3.1，不旋转）：起点 + 自车位置
        "minimap": {
            "enabled": True,
            "width": 240,
            "height": 170,
            "margin": 14,
        },
    },
}


def _deep_merge(base, override):
    """把 override 递归合并进 base 的副本（dict 合并，其余整体覆盖）。"""
    result = copy.deepcopy(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def config_path(project_dir):
    return os.path.join(str(project_dir), "cfg", "sim.json")


def load_config(project_dir):
    """读取配置；缺失时写默认文件，损坏时用默认值。返回普通 dict。"""
    path = config_path(project_dir)
    if not os.path.exists(path):
        try:
            folder = os.path.dirname(path)
            if folder and not os.path.isdir(folder):
                os.makedirs(folder)
            with open(path, "w", encoding="utf-8") as fh:
                json.dump(DEFAULT_CONFIG, fh, ensure_ascii=False, indent=2)
                fh.write("\n")
            LOG.info("未找到配置文件，已写出默认配置：%s", path)
        except OSError as exc:
            LOG.warning("写默认配置失败（继续用内置默认值）：%s", exc)
        return copy.deepcopy(DEFAULT_CONFIG)

    try:
        with open(path, "r", encoding="utf-8") as fh:
            raw = json.load(fh)
    except (OSError, ValueError) as exc:
        LOG.warning("配置文件读取失败，使用内置默认值：%s", exc)
        return copy.deepcopy(DEFAULT_CONFIG)

    if not isinstance(raw, dict):
        LOG.warning("配置文件顶层不是对象，使用内置默认值")
        return copy.deepcopy(DEFAULT_CONFIG)

    merged = _deep_merge(DEFAULT_CONFIG, raw)
    merged["version"] = DEFAULT_CONFIG["version"]
    return merged
