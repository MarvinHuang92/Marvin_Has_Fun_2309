# -*- coding: utf-8 -*-
"""2 自由度车辆模型 V2（纯数学，不 import pygame）。

坐标系
------
世界坐标：x 向右、y 向上，单位 **米**；航向 ``heading`` 从 +x 轴逆时针（rad）。
车体坐标：x 向前、y 向左；``vy`` 正 = 向左。
本模块不包含任何像素概念：世界 <-> 屏幕的换算由渲染层的 ``minirace.camera.Camera`` 完成。

状态
----
- ``x`` / ``y``：质心（≈车身中心）世界坐标，m
- ``heading``：航向，rad（逆时针正）
- ``vx`` / ``vy``：车体纵向 / 侧向速度，m/s
- ``yaw_rate``：横摆角速度 r，rad/s（逆时针正）
- ``gear``：-1 倒挡，1..6 前进挡
- ``shift_timer`` / ``shift_cooldown``：换挡断油剩余时间 / 两次换挡最小间隔
- ``_ax_last``：上一步纵向加速度，用于纵向载荷转移

模型（单步顺序见 :meth:`Vehicle.step`）
--------------------------------------
1. 自动换挡（按转速 + 油门，带断油时间和换挡冷却）
2. 发动机转速：离合锁止时由轮速反算；低速起步时离合打滑，转速由油门决定
3. 发动机扭矩：外特性曲线 × 油门 - 内摩擦（松油门时就是发动机制动）+ 怠速控制
4. 纵向载荷转移：``Fz_f = mg·b/L - m·ax·h/L``，``Fz_r = mg·a/L + m·ax·h/L``
5. 驱动/制动力按轴分配，超出 ``friction·Fz`` 即打滑（车轮空转/抱死）
6. 侧偏角 -> 线性侧向力，再用摩擦圆剩余量截断（侧滑/推头/甩尾的起点）
7. 车体合力/合力矩 -> 纵向、侧向、横摆加速度，半隐式欧拉积分

未建模：横向载荷转移、轮胎侧偏松弛长度、车轮转动惯量/滑移率、差速器、
轮胎纵滑曲线、发动机转动惯量与涡轮等。详见 docs/车辆动力学模型.md。
"""
import math

TWO_PI = 2.0 * math.pi


def _num(section, key, default):
    """从 dict 里取 float，取不到/类型不对时用默认值。"""
    try:
        value = (section or {}).get(key, default)
        if value is None:
            return float(default)
        return float(value)
    except (TypeError, ValueError):
        return float(default)


def _list_of_float(value, default):
    try:
        items = [float(item) for item in value]
        return items if items else list(default)
    except (TypeError, ValueError):
        return list(default)


class VehicleParams(object):
    """从完整 config dict 读参数，并算出派生量。"""

    def __init__(self, config=None):
        cfg = config or {}
        scale = cfg.get("scale", {}) or {}
        veh = cfg.get("vehicle", {}) or {}
        tires = cfg.get("tires", {}) or {}
        drive = cfg.get("drivetrain", {}) or {}
        engine = cfg.get("engine", {}) or {}
        aero = cfg.get("aero", {}) or {}
        brakes = cfg.get("brakes", {}) or {}

        self.gravity = _num(scale, "gravity", 9.81)

        # 整车与几何
        self.step_hz = _num(veh, "step_hz", 240.0)
        self.max_substeps = int(_num(veh, "max_substeps", 16))
        self.mass = _num(veh, "mass", 1200.0)
        self.inertia = _num(veh, "inertia", 1900.0)
        self.wheelbase = _num(veh, "wheelbase", 2.70)
        self.front_weight_fraction = _num(veh, "front_weight_fraction", 0.52)
        self.cg_height = _num(veh, "cg_height", 0.52)
        self.wheel_radius = _num(veh, "wheel_radius", 0.32)
        self.max_steer_deg = _num(veh, "max_steer_deg", 33.5)
        self.half_width = _num(veh, "half_width", 0.95)
        self.half_length = _num(veh, "half_length", 2.25)
        self.shift_max_speed = _num(veh, "shift_max_speed", 1.5)
        self.stop_speed = _num(veh, "stop_speed", 0.05)

        # 轮胎
        self.friction = _num(tires, "friction", 1.10)
        self.cornering_stiffness = _num(tires, "cornering_stiffness", 16.0)
        self.tire_shape = _num(tires, "tire_shape", 1.6)
        self.front_stiffness_scale = _num(tires, "front_stiffness_scale", 1.00)
        self.rear_stiffness_scale = _num(tires, "rear_stiffness_scale", 1.00)
        self.low_speed_fade = _num(tires, "low_speed_fade", 1.2)
        self.scrub_speed = _num(tires, "scrub_speed", 1.2)
        self.scrub_yaw_damping = _num(tires, "scrub_yaw_damping", 8.0)
        self.scrub_lateral_damping = _num(tires, "scrub_lateral_damping", 10.0)
        self.load_sensitivity = _num(tires, "load_sensitivity", 0.10)
        self.front_friction_scale = _num(tires, "front_friction_scale", 1.00)
        self.rear_friction_scale = _num(tires, "rear_friction_scale", 1.00)

        # 传动
        self.drive_split_front = _num(drive, "drive_split_front", 0.45)
        self.final_drive = _num(drive, "final_drive", 5.50)
        self.gear_ratios = _list_of_float(
            drive.get("gear_ratios"), [3.10, 2.35, 1.85, 1.55, 1.32, 1.14])
        self.reverse_ratio = _num(drive, "reverse_ratio", 3.20)
        self.efficiency = _num(drive, "efficiency", 0.90)
        self.idle_rpm = _num(drive, "idle_rpm", 900.0)
        self.redline_rpm = _num(drive, "redline_rpm", 7000.0)
        self.launch_rpm = _num(drive, "launch_rpm", 3000.0)
        self.shift_up_rpm = _num(drive, "shift_up_rpm", 6700.0)
        self.shift_down_rpm = _num(drive, "shift_down_rpm", 2500.0)
        self.kickdown_rpm = _num(drive, "kickdown_rpm", 3300.0)
        self.shift_time = _num(drive, "shift_time", 0.18)
        self.shift_interval = _num(drive, "shift_interval", 0.30)

        # 发动机
        self.torque_curve = self._parse_curve(engine.get("torque_curve"))
        self.engine_friction_base = _num(engine, "friction_base", 16.0)
        self.engine_friction_per_rpm = _num(engine, "friction_per_rpm", 0.005)

        # 阻力
        self.drag_coefficient = _num(aero, "drag_coefficient", 0.42)
        self.rolling_resistance = _num(aero, "rolling_resistance", 0.015)

        # 制动
        self.brake_decel_limit = _num(brakes, "decel_limit", 10.8)
        self.brake_front_bias = _num(brakes, "front_bias", 0.62)

        # 派生量
        self.a = self.wheelbase * (1.0 - self.front_weight_fraction)  # 质心 -> 前轴
        self.b = self.wheelbase * self.front_weight_fraction          # 质心 -> 后轴
        self.weight = self.mass * self.gravity
        self.static_front_load = self.weight * self.front_weight_fraction
        self.static_rear_load = self.weight * (1.0 - self.front_weight_fraction)
        self.kappa_max = math.tan(math.radians(self.max_steer_deg)) / self.wheelbase
        self.radius_min = 1.0 / self.kappa_max
        self.num_gears = len(self.gear_ratios)

        self._validate()

    # ------------------------------------------------------------------ 工具
    @staticmethod
    def _parse_curve(value):
        default = [
            (1000.0, 230.0), (2000.0, 300.0), (3000.0, 330.0),
            (4500.0, 350.0), (5500.0, 330.0), (6500.0, 280.0),
            (7200.0, 220.0),
        ]
        try:
            curve = sorted((float(pair[0]), float(pair[1])) for pair in value)
            return curve if len(curve) >= 2 else default
        except (TypeError, ValueError, IndexError):
            return default

    def _validate(self):
        if self.mass <= 0.0:
            raise ValueError("vehicle.mass 必须为正数")
        if self.inertia <= 0.0:
            raise ValueError("vehicle.inertia 必须为正数")
        if self.wheelbase <= 0.0:
            raise ValueError("vehicle.wheelbase 必须为正数")
        if not 0.0 < self.front_weight_fraction < 1.0:
            raise ValueError("vehicle.front_weight_fraction 必须在 (0, 1) 内")
        if self.wheel_radius <= 0.0:
            raise ValueError("vehicle.wheel_radius 必须为正数")
        if self.step_hz <= 0.0:
            raise ValueError("vehicle.step_hz 必须为正数")
        if self.friction <= 0.0:
            raise ValueError("tires.friction 必须为正数")
        if self.final_drive <= 0.0:
            raise ValueError("drivetrain.final_drive 必须为正数")
        if not self.gear_ratios or min(self.gear_ratios) <= 0.0:
            raise ValueError("drivetrain.gear_ratios 必须为正数列表")
        if self.redline_rpm <= self.idle_rpm:
            raise ValueError("drivetrain.redline_rpm 必须大于 idle_rpm")
        if self.low_speed_fade <= 0.0:
            raise ValueError("tires.low_speed_fade 必须为正数")
        if self.scrub_speed < 0.0:
            raise ValueError("tires.scrub_speed 不能为负")
        if self.scrub_yaw_damping < 0.0:
            raise ValueError("tires.scrub_yaw_damping 不能为负")
        if self.scrub_lateral_damping < 0.0:
            raise ValueError("tires.scrub_lateral_damping 不能为负")
        if self.tire_shape <= 0.0:
            raise ValueError("tires.tire_shape 必须为正数")
        if self.load_sensitivity < 0.0:
            raise ValueError("tires.load_sensitivity 不能为负")

    def torque_at(self, rpm):
        """发动机外特性扭矩（N·m），线性插值。"""
        curve = self.torque_curve
        if rpm <= curve[0][0]:
            return curve[0][1]
        for index in range(len(curve) - 1):
            r0, t0 = curve[index]
            r1, t1 = curve[index + 1]
            if rpm <= r1:
                if r1 <= r0:
                    return t1
                ratio = (rpm - r0) / (r1 - r0)
                return t0 + (t1 - t0) * ratio
        return curve[-1][1]

    def gear_ratio(self, gear):
        """总齿比（不含主减速比）。倒挡用 reverse_ratio。"""
        if gear == -1:
            return self.reverse_ratio
        if 1 <= gear <= len(self.gear_ratios):
            return self.gear_ratios[gear - 1]
        return self.gear_ratios[0]


class Telemetry(object):
    """一步物理后的观测量，供 HUD / 遥测录制 / AI 使用（SI 单位）。"""

    __slots__ = (
        "x", "y", "heading",
        "vx", "vy", "speed", "speed_abs", "yaw_rate", "radius", "beta_deg",
        "rpm", "gear", "gear_ratio", "engine_torque", "drive_force",
        "shift_timer", "shifting", "clutch_slipping",
        "ax", "ay", "a_long", "a_lat", "grip_usage",
        "wheelspin", "lockup", "sliding", "slip_amount",
        "slip_angle_front", "slip_angle_rear",
        "fx_front", "fx_rear", "fy_front", "fy_rear", "yaw_torque",
        "fz_front", "fz_rear",
        "wall_hit", "brake_clamped",
        "throttle", "brake", "steer", "steer_deg",
    )

    def as_dict(self):
        return dict((name, getattr(self, name)) for name in self.__slots__)


class Vehicle(object):
    """车辆状态与一步积分。"""

    def __init__(self, params, x, y, heading=0.0, bounds=None):
        self.p = params
        self.bounds = bounds
        self.x = float(x)
        self.y = float(y)
        self.heading = float(heading)
        self.reset_state()

    def reset_state(self):
        self.vx = 0.0
        self.vy = 0.0
        self.yaw_rate = 0.0
        self.gear = 1
        self.shift_timer = 0.0
        self.shift_cooldown = 0.0
        self._ax_last = 0.0
        self.rpm = self.p.idle_rpm

    def reset(self, x=None, y=None, heading=0.0):
        if x is not None:
            self.x = float(x)
        if y is not None:
            self.y = float(y)
        self.heading = float(heading)
        self.reset_state()

    # ------------------------------------------------------------------ 操作
    def toggle_reverse(self):
        """R 键：在前进挡与倒挡之间切换（要求接近静止），返回是否成功。"""
        if abs(self.vx) > self.p.shift_max_speed:
            return False
        self.gear = 1 if self.gear == -1 else -1
        self.shift_timer = self.p.shift_time
        self.shift_cooldown = self.p.shift_interval
        return True

    # ------------------------------------------------------------------ 内部
    def _rpm_geared(self, ratio=None):
        p = self.p
        if ratio is None:
            ratio = p.gear_ratio(self.gear)
        wheel_omega = abs(self.vx) / p.wheel_radius
        return wheel_omega * ratio * p.final_drive * 60.0 / TWO_PI

    def _engine_torque(self, throttle, rpm):
        """净发动机扭矩：外特性 × 油门 - 内摩擦；怠速时由怠速控制器补足。"""
        p = self.p
        friction = p.engine_friction_base + p.engine_friction_per_rpm * rpm
        if throttle < 0.02 and rpm <= p.idle_rpm + 100.0:
            indicated = friction
        else:
            indicated = throttle * p.torque_at(rpm)
        return indicated - friction

    def _shift_to(self, gear):
        self.gear = gear
        self.shift_timer = self.p.shift_time
        self.shift_cooldown = self.p.shift_interval

    def _auto_shift(self, controls, dt):
        p = self.p
        if self.shift_timer > 0.0:
            self.shift_timer = max(0.0, self.shift_timer - dt)
        if self.shift_cooldown > 0.0:
            self.shift_cooldown = max(0.0, self.shift_cooldown - dt)
        if self.gear == -1 or self.shift_timer > 0.0 or self.shift_cooldown > 0.0:
            return

        rpm = self._rpm_geared()
        if rpm > p.shift_up_rpm and self.gear < p.num_gears:
            self._shift_to(self.gear + 1)
            return
        if self.gear <= 1:
            return

        target = self.gear - 1
        rpm_target = self._rpm_geared(p.gear_ratio(target))
        need_down = rpm < p.shift_down_rpm
        kickdown = controls.throttle > 0.8 and rpm < p.kickdown_rpm
        if (need_down or kickdown) and rpm_target < p.redline_rpm * 0.96:
            self._shift_to(target)

    def _clamp_to_bounds(self):
        """占位实现：世界四边当墙。返回是否撞到边界。将来换成赛道边界/出界判定。"""
        width, height = self.bounds
        hw = self.p.half_width
        hl = self.p.half_length
        hit = False
        if self.x < hw:
            self.x = hw
            hit = True
        elif self.x > width - hw:
            self.x = width - hw
            hit = True
        if self.y < hl:
            self.y = hl
            hit = True
        elif self.y > height - hl:
            self.y = height - hl
            hit = True
        if hit:
            self.vx = 0.0
            self.vy = 0.0
            self.yaw_rate = 0.0
        return hit

    # ------------------------------------------------------------------ 物理
    def step(self, controls, dt):
        """按 dt 秒推进物理，返回 Telemetry。"""
        p = self.p

        # 1) 自动换挡（会更新 gear / 断油计时）
        self._auto_shift(controls, dt)
        ratio = p.gear_ratio(self.gear)
        direction = -1.0 if self.gear == -1 else 1.0

        # 2) 转速与离合状态
        rpm_geared = self._rpm_geared(ratio)
        if self.shift_timer > 0.0:
            shifting = True
            clutch_slipping = False
            rpm = min(max(rpm_geared, p.idle_rpm), p.redline_rpm)
            engine_torque = 0.0
        else:
            shifting = False
            clutch_slipping = rpm_geared < p.idle_rpm * 1.02
            if clutch_slipping:
                rpm = p.idle_rpm + controls.throttle * (p.launch_rpm - p.idle_rpm)
            else:
                rpm = min(max(rpm_geared, p.idle_rpm), p.redline_rpm)
            engine_torque = self._engine_torque(controls.throttle, rpm)
            if not clutch_slipping and rpm_geared > p.redline_rpm:
                engine_torque = 0.0  # 断油限转

        # 3) 纵向载荷转移（用上一步的纵向加速度）
        g = p.gravity
        fz_front = (p.static_front_load
                    - p.mass * self._ax_last * p.cg_height / p.wheelbase)
        fz_rear = (p.static_rear_load
                   + p.mass * self._ax_last * p.cg_height / p.wheelbase)
        min_load = p.weight * 0.05
        if fz_front < min_load:
            fz_front = min_load
        if fz_rear < min_load:
            fz_rear = min_load

        # 4) 驱动 / 制动需求
        # 驱动力沿轮胎平面（前轮带转向角），制动力作用在车体纵向。
        # 制动力不跟着方向盘转：真实轮胎在抱死滑移时摩擦方向由滑移速度决定，
        # 若强行把制动力沿"转满的前轮平面"施加，满舵+刹车会凭空产生几 kN 的横向力，
        # 把车横向甩出去（V2.6 及之前的"侧滑/后退感"来源）。
        drive_force = (direction * engine_torque * ratio * p.final_drive
                       * p.efficiency / p.wheel_radius)
        drive_front = drive_force * p.drive_split_front
        drive_rear = drive_force * (1.0 - p.drive_split_front)

        if abs(self.vx) > p.stop_speed:
            brake_sign = -1.0 if self.vx > 0.0 else 1.0
        else:
            brake_sign = 0.0
        brake_force = brake_sign * controls.brake * p.brake_decel_limit * p.mass
        brake_front = brake_force * p.brake_front_bias
        brake_rear = brake_force * (1.0 - p.brake_front_bias)

        # 载荷敏感性：重载时单位载荷抓地力下降（简化版）
        def load_factor(load, static_load):
            if static_load <= 1e-9:
                return 1.0
            return max(0.3, 1.0 - p.load_sensitivity * (load / static_load - 1.0))

        mu_front = (p.friction * p.front_friction_scale
                    * load_factor(fz_front, p.static_front_load))
        mu_rear = (p.friction * p.rear_friction_scale
                   * load_factor(fz_rear, p.static_rear_load))
        fmax_front = mu_front * fz_front
        fmax_rear = mu_rear * fz_rear
        wheelspin = False
        lockup = False

        def clamp_long(demand, limit):
            if limit <= 1e-9:
                return 0.0, (1.0 if abs(demand) > 1e-9 else 0.0)
            excess = abs(demand) / limit - 1.0
            if excess > 0.0:
                return math.copysign(limit, demand), excess
            return demand, 0.0

        # 纵向力分别截断：驱动超过附着 -> 车轮空转；制动超过附着 -> 抱死
        fx_front, drive_excess_front = clamp_long(drive_front, fmax_front)
        fx_rear, drive_excess_rear = clamp_long(drive_rear, fmax_rear)
        drive_excess = max(drive_excess_front, drive_excess_rear)
        if drive_excess > 0.0:
            wheelspin = True

        fx_brake_front, brake_excess_front = clamp_long(brake_front, fmax_front)
        fx_brake_rear, brake_excess_rear = clamp_long(brake_rear, fmax_rear)
        brake_excess = max(brake_excess_front, brake_excess_rear)
        if brake_excess > 0.0:
            lockup = True
        long_excess = max(drive_excess, brake_excess)

        # 5) 侧偏角与侧向力（轮胎坐标系，前进/倒车统一处理 + 魔术公式 + 摩擦圆 + 低速淡入）
        delta = math.radians(p.max_steer_deg * controls.steer)  # steer>0 = 左转
        sin_d = math.sin(delta)
        cos_d = math.cos(delta)

        # 前后轴在各自轮胎坐标系下的纵向/侧向速度（u 沿轮胎平面、w 沿轮胎侧向，左正）。
        # 倒车时 u < 0，但侧偏角分母用 |u|：这样"胎面被拖向哪边"的符号不随行驶方向翻转，
        # 后轴的偏航阻尼在倒车时也成立（V2.4 及之前用 travel_sign 翻转侧向力，导致倒车
        # 横向力变成"反阻尼"，一打方向就螺旋加速自旋）。
        u_front = self.vx * cos_d + (self.vy + p.a * self.yaw_rate) * sin_d
        w_front = -self.vx * sin_d + (self.vy + p.a * self.yaw_rate) * cos_d
        u_rear = self.vx
        w_rear = self.vy - p.b * self.yaw_rate
        speed_floor = 0.5
        alpha_front_sae = math.atan2(w_front, max(abs(u_front), speed_floor))
        alpha_rear_sae = math.atan2(w_rear, max(abs(u_rear), speed_floor))

        # 简化魔术公式：Fy = mu*Fz*sin(C*atan(B*alpha))
        # 小角度侧偏刚度 = mu*Fz*C*B = cornering_stiffness*Fz*scale
        # 峰值侧偏角 alpha_peak = tan(pi/(2C)) / B；侧向力与 SAE 侧偏角反号
        shape = p.tire_shape
        stiffness_front = p.cornering_stiffness * p.front_stiffness_scale
        stiffness_rear = p.cornering_stiffness * p.rear_stiffness_scale
        b_front = stiffness_front / (p.friction * shape) if p.friction > 0 else 1.0
        b_rear = stiffness_rear / (p.friction * shape) if p.friction > 0 else 1.0

        def magic(alpha, fz, b_factor, mu):
            return mu * fz * math.sin(shape * math.atan(b_factor * alpha))

        fy_front_demand = magic(-alpha_front_sae, fz_front, b_front, mu_front)
        fy_rear_demand = magic(-alpha_rear_sae, fz_rear, b_rear, mu_rear)

        # 摩擦圆剩余量：纵向占用 = 驱动 + 制动（近似同向叠加）
        long_front = abs(fx_front + fx_brake_front)
        long_rear = abs(fx_rear + fx_brake_rear)
        fy_max_front = math.sqrt(max(fmax_front * fmax_front - long_front * long_front, 0.0))
        fy_max_rear = math.sqrt(max(fmax_rear * fmax_rear - long_rear * long_rear, 0.0))

        def clamp_lat(demand, limit):
            if limit <= 1e-9:
                return 0.0, (1.0 if abs(demand) > 1e-9 else 0.0)
            excess = abs(demand) / limit - 1.0
            if excess > 0.0:
                return math.copysign(limit, demand), excess
            return demand, 0.0

        fy_front, lat_excess_front = clamp_lat(fy_front_demand, fy_max_front)
        fy_rear, lat_excess_rear = clamp_lat(fy_rear_demand, fy_max_rear)

        # 越过侧偏力峰值也算侧滑（打滑程度用于声音/HUD）
        tan_peak = math.tan(math.pi / (2.0 * shape))
        peak_front = tan_peak / b_front if b_front > 0.0 else 0.0
        peak_rear = tan_peak / b_rear if b_rear > 0.0 else 0.0
        peak_excess = 0.0
        if peak_front > 0.0:
            peak_excess = max(peak_excess,
                              (abs(alpha_front_sae) - peak_front) / peak_front)
        if peak_rear > 0.0:
            peak_excess = max(peak_excess,
                              (abs(alpha_rear_sae) - peak_rear) / peak_rear)
        peak_excess = max(0.0, peak_excess)

        if p.low_speed_fade > 0.0:
            fade = min(1.0, abs(self.vx) / p.low_speed_fade)
        else:
            fade = 1.0
        fy_front *= fade
        fy_rear *= fade

        lat_excess = max(lat_excess_front, lat_excess_rear, peak_excess)
        sliding = lat_excess > 1e-3
        slip_amount = min(1.0, max(long_excess, lat_excess))

        # 6) 每轴合力先变换到车体坐标，再按摩擦圆截断一次（制动力在车体纵向）
        fx_front_body = fx_front * cos_d - fy_front * sin_d + fx_brake_front
        fy_front_body = fx_front * sin_d + fy_front * cos_d
        fx_rear_body = fx_rear + fx_brake_rear
        fy_rear_body = fy_rear

        def clamp_vector(fx_value, fy_value, limit):
            magnitude = math.hypot(fx_value, fy_value)
            if limit > 1e-9 and magnitude > limit:
                scale = limit / magnitude
                return fx_value * scale, fy_value * scale
            return fx_value, fy_value

        fx_front_body, fy_front_body = clamp_vector(fx_front_body, fy_front_body, fmax_front)
        fx_rear_body, fy_rear_body = clamp_vector(fx_rear_body, fy_rear_body, fmax_rear)

        fx_tyre = fx_front_body + fx_rear_body
        fy_tyre = fy_front_body + fy_rear_body
        yaw_torque = p.a * fy_front_body - p.b * fy_rear_body

        # 空气阻力 + 滚动阻力（纵向，按运动方向反向）
        speed_abs = math.hypot(self.vx, self.vy)
        fx_body = fx_tyre
        if abs(self.vx) > 1e-6:
            drag = p.drag_coefficient * self.vx * self.vx
            rolling = p.rolling_resistance * p.mass * g
            fx_body -= math.copysign(drag + rolling, self.vx)

        # 7) 加速度（车体坐标）
        a_long = fx_tyre / p.mass
        a_lat = fy_tyre / p.mass
        ax = fx_body / p.mass + self.yaw_rate * self.vy
        ay = a_lat - self.yaw_rate * self.vx
        yaw_acc = yaw_torque / p.inertia

        # 低速轮胎"蹭地"阻尼：速度趋零时侧向力随 low_speed_fade 一起消失，
        # 若不加这一项，刹车/打方向把车逼停后残余的 vy / 横摆角速度没有任何东西耗散，
        # 车会原地一直自转。这里只在 |vx| < scrub_speed 时按比例施加（0 -> 满强度）。
        # 它本质上是摩擦力，加速度/力矩同样受附着上限约束，不能超过 μ·g。
        if p.scrub_speed > 0.0 and abs(self.vx) < p.scrub_speed:
            scrub = 1.0 - abs(self.vx) / p.scrub_speed
            grip_acc = p.friction * p.gravity
            scrub_ay = -p.scrub_lateral_damping * scrub * self.vy
            scrub_ay = max(-grip_acc, min(grip_acc, scrub_ay))
            ay += scrub_ay
            yaw_cap = grip_acc * p.mass * max(p.a, p.b) / p.inertia
            scrub_yaw = -p.scrub_yaw_damping * scrub * self.yaw_rate
            yaw_acc += max(-yaw_cap, min(yaw_cap, scrub_yaw))

        # 8) 半隐式欧拉积分
        vx_before = self.vx
        self.vx += ax * dt
        self.vy += ay * dt
        self.yaw_rate += yaw_acc * dt
        # 刹车不允许把车沿车头方向"反推"（含旋转带来的 r·vy 项）：
        # 否则低速侧滑时会出现"车头还没转过头、车却沿车头反方向后溜"的错觉。
        # 前进挡刹车时强制 vx >= 0，倒挡刹车时强制 vx <= 0。
        brake_clamped = False
        if controls.brake > 0.05:
            if self.gear > 0 and self.vx < 0.0:
                self.vx = 0.0
                brake_clamped = True
            elif self.gear < 0 and self.vx > 0.0:
                self.vx = 0.0
                brake_clamped = True
        self.heading += self.yaw_rate * dt
        cos_h = math.cos(self.heading)
        sin_h = math.sin(self.heading)
        world_vx = self.vx * cos_h - self.vy * sin_h
        world_vy = self.vx * sin_h + self.vy * cos_h
        self.x += world_vx * dt
        self.y += world_vy * dt
        # 载荷转移只用轮胎纵向力产生的加速度，不用含 r*vy 的车体加速度
        self._ax_last = a_long

        # 静止判定：没有油门且速度很低时直接停住，避免数值蠕行
        if math.hypot(self.vx, self.vy) < p.stop_speed and controls.throttle < 0.02:
            self.vx = 0.0
            self.vy = 0.0
            self.yaw_rate = 0.0

        if self.bounds is not None:
            wall_hit = self._clamp_to_bounds()
        else:
            wall_hit = False

        speed_abs = math.hypot(self.vx, self.vy)

        # 9) 打滑时让转速"飞"起来（没有建车轮转动惯量，用转速抬升近似）
        if wheelspin and not clutch_slipping and not shifting:
            rpm = min(p.redline_rpm, rpm + min(long_excess, 1.0) * 1200.0)

        self.rpm = rpm

        # 10) 观测量
        telemetry = Telemetry()
        telemetry.x = self.x
        telemetry.y = self.y
        telemetry.heading = self.heading
        telemetry.vx = self.vx
        telemetry.vy = self.vy
        telemetry.speed = self.vx
        telemetry.speed_abs = speed_abs
        telemetry.yaw_rate = self.yaw_rate
        telemetry.radius = (speed_abs / abs(self.yaw_rate)
                            if abs(self.yaw_rate) > 1e-4 else 0.0)
        telemetry.beta_deg = (math.degrees(math.atan2(self.vy, abs(self.vx)))
                              if abs(self.vx) > p.stop_speed else 0.0)
        telemetry.rpm = rpm
        telemetry.gear = self.gear
        telemetry.gear_ratio = ratio * p.final_drive
        telemetry.engine_torque = engine_torque
        telemetry.drive_force = drive_force
        telemetry.shift_timer = self.shift_timer
        telemetry.shifting = shifting
        telemetry.clutch_slipping = clutch_slipping
        telemetry.ax = ax
        telemetry.ay = ay
        telemetry.a_long = a_long
        telemetry.a_lat = a_lat
        util_front = (math.hypot(fx_front_body, fy_front_body) / fmax_front
                      if fmax_front > 1e-9 else 0.0)
        util_rear = (math.hypot(fx_rear_body, fy_rear_body) / fmax_rear
                     if fmax_rear > 1e-9 else 0.0)
        telemetry.grip_usage = max(util_front, util_rear)
        telemetry.wheelspin = wheelspin
        telemetry.lockup = lockup
        telemetry.sliding = sliding
        telemetry.slip_amount = slip_amount
        telemetry.slip_angle_front = math.degrees(-alpha_front_sae)
        telemetry.slip_angle_rear = math.degrees(-alpha_rear_sae)
        telemetry.fx_front = fx_front_body
        telemetry.fx_rear = fx_rear_body
        telemetry.fy_front = fy_front_body
        telemetry.fy_rear = fy_rear_body
        telemetry.yaw_torque = yaw_torque
        telemetry.fz_front = fz_front
        telemetry.fz_rear = fz_rear
        telemetry.wall_hit = wall_hit
        telemetry.brake_clamped = brake_clamped
        telemetry.throttle = controls.throttle
        telemetry.brake = controls.brake
        telemetry.steer = controls.steer
        telemetry.steer_deg = math.degrees(delta)
        return telemetry
