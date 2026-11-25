# -*- coding: utf-8 -*-
"""音频：发动机 + 打滑 + 换挡 + 撞墙声音。

默认**不依赖任何音频素材**，用标准库合成 16-bit 单声道 PCM：
- 发动机：按"点火频率 = rpm/30"（4 缸 4 冲程）合成含谐波的循环，做成一张
  32 档的音色表；运行时按转速取相邻两档，用两个通道交叉淡化（pygame 不能实时变调）。
- 打滑：合成一条带拍频的尖叫循环，音量跟随 ``telemetry.slip_amount``。
- 撞墙：合成低频"砰"声，在 ``wall_hit`` 上升沿触发一次。

可选**采样包**（``audio.sample_pack``）：
- 分组模式：``engine_file`` 为怠速循环，``run_engine_files`` 为运行时按 RPM
  交叉淡化的多段循环，``shift_file`` 在挡位变化时播放；
- 兼容单文件模式：把一个 WAV 自动挑平稳段并重采样成 32 档音色表。
文件不存在/格式不支持时自动回退合成声。素材放 ``sounds/``（已 gitignore）。

没有可用的音频设备/混音器时 :class:`Audio` 自动降级为静音，不影响模拟器。
"""
import array
import logging
import math
import os
import random
import time
import wave

import pygame

LOG = logging.getLogger(__name__)

SAMPLE_RATE = 22050
LOOP_SECONDS = 0.20
NUM_PITCHES = 32
RPM_MIN = 800.0
RPM_MAX = 7200.0

# 采样包默认参数（cfg/sim.json -> audio.sample_pack 可覆盖）
SAMPLE_PACK_DEFAULTS = {
    "enabled": True,
    "engine_file": ("sounds/Car_Engine_Gear_Shift_Hum_Loops/"
                    "soundza-car-engine-loop-1.wav"),
    "run_engine_files": [
        "sounds/Car_Engine_Gear_Shift_Hum_Loops/soundza-car-engine-loop-8.wav",
        "sounds/Car_Engine_Gear_Shift_Hum_Loops/soundza-car-engine-loop-9.wav",
        "sounds/Car_Engine_Gear_Shift_Hum_Loops/soundza-car-engine-loop-10.wav",
        "sounds/Car_Engine_Gear_Shift_Hum_Loops/soundza-car-engine-loop-11.wav",
        "sounds/Car_Engine_Gear_Shift_Hum_Loops/soundza-car-engine-loop-12.wav",
        "sounds/Car_Engine_Gear_Shift_Hum_Loops/soundza-car-engine-loop-13.wav",
    ],
    "shift_file": ("sounds/Car_Engine_Gear_Shift_Hum_Loops/"
                   "soundza-gear-shift-1.wav"),
    "run_engine_frequencies": [73.5, 82.5, 92.5, 104.0, 116.5, 131.0],
    "run_loop_seconds": 1.5,     # 每段运行循环截取长度（避免启动过慢）
    "pitch_steps": 64,           # 音高表档数；64 在平滑度和启动/切换开销之间取平衡
    "idle_pitch_factor": 0.95,   # 怠速采样额外变调系数（配合 900 rpm 目标）
    "loop_start_s": 0.0,         # 整段循环素材从 0 开始
    "loop_seconds": 4.0,         # 整段 4 s 循环
    "base_rpm": 2400.0,          # 兼容旧的单文件重采样模式
    "min_pitch_factor": 0.45,
    "max_pitch_factor": 2.60,
    "target_peak": 0.55,
    "crash_volume": 0.85,
}


def _to_pcm(samples):
    """float 列表 [-1, 1] -> 16-bit 单声道 PCM bytes。"""
    pcm = array.array("h")
    for value in samples:
        clamped = -1.0 if value < -1.0 else (1.0 if value > 1.0 else value)
        pcm.append(int(clamped * 32000.0))
    return pcm.tobytes()


def _warning_beep():
    """短促的双音提示（WRONG WAY 闪烁时使用）。"""
    duration = 0.18
    length = int(SAMPLE_RATE * duration)
    samples = []
    for index in range(length):
        t = index / float(SAMPLE_RATE)
        freq = 880.0 if t < duration * 0.5 else 1174.7
        envelope = min(1.0, t / 0.01, (duration - t) / 0.025)
        samples.append(0.45 * max(0.0, envelope) * math.sin(2.0 * math.pi * freq * t))
    return _to_pcm(samples)


def _engine_loop(firing_freq):
    """按点火频率生成一段可无缝循环的发动机音色。"""
    length = int(SAMPLE_RATE * LOOP_SECONDS)
    # 取整数个（偶数个）周期，保证首尾相接不爆音
    cycles = max(2, 2 * int(round(firing_freq * LOOP_SECONDS / 2.0)))
    freq = cycles / LOOP_SECONDS
    harmonics = (1.0, 0.62, 0.42, 0.28, 0.18, 0.11)
    samples = []
    for index in range(length):
        t = index / float(SAMPLE_RATE)
        value = 0.0
        for order, amp in enumerate(harmonics, start=1):
            value += amp * math.sin(2.0 * math.pi * freq * order * t
                                    + 0.35 * order)
        # 半阶调制：让声音更像内燃机而不是纯音
        value *= 1.0 + 0.18 * math.sin(math.pi * freq * t)
        samples.append(value * 0.30)
    return _to_pcm(samples)


def _slip_loop():
    """打滑尖叫：主频 + 非谐波邻居 + 拍频调制。"""
    length = int(SAMPLE_RATE * 0.25)
    base_cycles = int(round(950.0 * 0.25))
    freq_a = base_cycles / 0.25
    freq_b = (base_cycles + 3) / 0.25
    freq_c = (base_cycles * 2) / 0.25
    samples = []
    for index in range(length):
        t = index / float(SAMPLE_RATE)
        value = (1.00 * math.sin(2.0 * math.pi * freq_a * t)
                 + 0.55 * math.sin(2.0 * math.pi * freq_b * t + 1.1)
                 + 0.30 * math.sin(2.0 * math.pi * freq_c * t + 0.4))
        value *= 0.72 + 0.28 * math.sin(2.0 * math.pi * 4.0 * t)
        samples.append(value * 0.22)
    return _to_pcm(samples)


def _crash_hit():
    """合成撞墙声：低频"砰" + 少量衰减噪声，再补一个更轻的回弹。"""
    duration = 0.52
    length = int(SAMPLE_RATE * duration)
    rng = random.Random(7)
    samples = []
    for index in range(length):
        t = index / float(SAMPLE_RATE)
        env = math.exp(-t * 9.0)
        thump = (math.sin(2.0 * math.pi * 72.0 * t)
                 + 0.55 * math.sin(2.0 * math.pi * 108.0 * t + 0.4))
        noise = rng.uniform(-1.0, 1.0) * math.exp(-t * 28.0)
        value = (0.9 * thump + 0.55 * noise) * env
        if t > 0.11:
            dt = t - 0.11
            value += 0.45 * math.sin(2.0 * math.pi * 58.0 * dt) * math.exp(-dt * 18.0)
        samples.append(value * 0.55)
    return _to_pcm(samples)


# ---------------------------------------------------------------- 采样包工具
def _read_wav_mono(path):
    """读 WAV（PCM 8/16/24/32-bit，单/多声道）-> (float 单声道列表, 采样率)。"""
    with wave.open(path, "rb") as wf:
        if wf.getcomptype() != "NONE":
            raise ValueError("只支持未压缩 PCM WAV")
        channels = wf.getnchannels()
        rate = wf.getframerate()
        width = wf.getsampwidth()
        frames = wf.getnframes()
        raw = wf.readframes(frames)
    values = []
    if width == 1:
        data = array.array("B")
        data.frombytes(raw)
        values = [(value - 128) / 128.0 for value in data]
    elif width == 2:
        data = array.array("h")
        data.frombytes(raw)
        values = [value / 32768.0 for value in data]
    elif width == 3:
        for index in range(0, len(raw) - 2, 3):
            value = raw[index] | (raw[index + 1] << 8) | (raw[index + 2] << 16)
            if value & 0x800000:
                value -= 0x1000000
            values.append(value / 8388608.0)
    elif width == 4:
        data = array.array("i")
        data.frombytes(raw)
        values = [value / 2147483648.0 for value in data]
    else:
        raise ValueError("不支持的 WAV 位宽：%d bit" % (width * 8))
    if channels > 1:
        mono = []
        for index in range(0, len(values) - channels + 1, channels):
            mono.append(sum(values[index:index + channels]) / float(channels))
        values = mono
    return values, rate


def _mean(values):
    return sum(values) / float(len(values)) if values else 0.0


def _rms(values):
    if not values:
        return 0.0
    return math.sqrt(sum(value * value for value in values) / float(len(values)))


def _choose_loop_start(values, rate, seconds):
    """自动挑一段最"平稳"的窗口当循环：优先分段 RMS 稳定，其次才要响一点。

    发动机循环最怕的是音高/音量在循环里起伏（会听到"呜—呜—"），所以对波动
    （变异系数）的惩罚远大于对响度的偏好。
    """
    window = int(rate * seconds)
    if window < 64 or len(values) < window * 2:
        return 0
    step = max(window // 2, 1)
    block = max(window // 4, 32)
    best_start = 0
    best_score = -1.0
    for start in range(0, len(values) - window + 1, step):
        blocks = [values[offset:offset + block]
                  for offset in range(start, start + window - block + 1, block)]
        levels = [_rms(part) for part in blocks]
        average = _mean(levels)
        if average < 2e-3:
            continue
        variance = sum((level - average) ** 2 for level in levels) / len(levels)
        variation = math.sqrt(variance) / average
        score = math.sqrt(average) / (1.0 + 15.0 * variation)
        if score > best_score:
            best_score = score
            best_start = start
    return best_start


def _estimate_f0(values, start, rate, seconds):
    """自相关粗估基频（先 2 倍降采样，够用且快）。"""
    length = min(int(rate * min(seconds, 0.5)), 4096)
    segment = values[start:start + length]
    if len(segment) < 128:
        return 0.0
    decimated = [(segment[i] + segment[i + 1]) * 0.5
                 for i in range(0, len(segment) - 1, 2)]
    decimated_rate = rate / 2.0
    average = _mean(decimated)
    decimated = [value - average for value in decimated]
    low_lag = max(4, int(decimated_rate / 400.0))
    high_lag = min(len(decimated) // 2, int(decimated_rate / 40.0))
    if high_lag <= low_lag:
        return 0.0
    best_lag = 0
    best_corr = 0.0
    for lag in range(low_lag, high_lag + 1):
        total = 0.0
        for index in range(0, len(decimated) - lag):
            total += decimated[index] * decimated[index + lag]
        if total > best_corr:
            best_corr = total
            best_lag = lag
    if best_lag <= 0:
        return 0.0
    return decimated_rate / float(best_lag)


def _extract_loop(values, start, rate, seconds, f0):
    """按整数个基频周期截取循环，减少接缝爆音。"""
    if f0 > 1.0:
        cycles = max(4, int(round(f0 * seconds)))
        length = int(round(cycles * rate / f0))
    else:
        length = int(round(rate * seconds))
    length = max(64, min(length, len(values) - start))
    loop = values[start:start + length]
    return _seam_crossfade(loop, rate)


def _seam_crossfade(loop, rate):
    """把循环尾部交叉淡化到头部，消除接缝爆音（长度会缩短 fade 个样本）。"""
    fade = min(int(rate * 0.02), len(loop) // 4)
    if fade < 2:
        return loop
    output = loop[:len(loop) - fade]
    tail = len(loop) - fade
    for index in range(fade):
        weight = index / float(fade)
        output[index] = loop[index] * weight + loop[tail + index] * (1.0 - weight)
    return output


def _resample_loop(loop, factor, target_peak):
    """线性插值重采样（factor>1 音调升高）+ 峰值归一化。"""
    source = len(loop)
    factor = max(0.05, min(8.0, factor))
    length = max(32, int(round(source / factor)))
    output = [0.0] * length
    position = 0.0
    for index in range(length):
        base = int(position)
        frac = position - base
        low = loop[base % source]
        high = loop[(base + 1) % source]
        output[index] = low + (high - low) * frac
        position += factor
    peak = max(abs(value) for value in output)
    if peak > 1e-6:
        scale = target_peak / peak
        output = [value * scale for value in output]
    return output



def _load_wav_samples(path, target_peak=0.55):
    """读入一个 WAV 并重采样到混音器采样率，保持时长不变。"""
    values, rate = _read_wav_mono(path)
    if not values:
        raise ValueError("空 WAV：%s" % path)
    average = _mean(values)
    values = [value - average for value in values]
    factor = rate / float(SAMPLE_RATE)
    return _resample_loop(values, factor, target_peak)


class Audio(object):
    """发动机 + 打滑 + 换挡 + 撞墙音效。初始化失败时 ``enabled`` 为 False。"""

    def __init__(self, config=None, project_dir=None):
        cfg = config or {}
        self.enabled = False
        self.muted = False
        self.project_dir = project_dir
        self.engine_sounds = []
        self.idle_sound = None
        self.engine_source = "synth"
        self.sample_file = None
        self.sample_loop_start = None
        self.sample_f0 = 0.0
        self.base_rpm = None
        self.sample_run_count = 0
        self.pitch_steps = NUM_PITCHES
        self.slip_sound = None
        self.shift_sound = None
        self.crash_sound = None
        self.beep_sound = None
        self._chan_a = None
        self._chan_b = None
        self._chan_idle = None
        self._chan_slip = None
        self._chan_shift = None
        self._chan_crash = None
        self._chan_beep = None
        self._sound_a = -1
        self._sound_b = -1
        self._slip_playing = False
        self._last_gear = None
        self._last_speed = 0.0
        self._wall_was_hit = False
        self._crash_ready_at = 0.0
        self._first_update_at = None
        self.startup_gain = 0.0
        self.master_volume = float(cfg.get("master_volume", 0.35))
        self.engine_volume = float(cfg.get("engine_volume", 0.9))
        self.slip_volume = float(cfg.get("slip_volume", 0.7))
        pack = dict(SAMPLE_PACK_DEFAULTS)
        pack.update(cfg.get("sample_pack") or {})
        self.sample_pack = pack
        self.crash_volume = float(pack.get("crash_volume", 0.85))
        self.startup_delay_s = max(0.0, float(cfg.get("startup_delay_s", 0.6)))
        self.fade_in_s = max(0.0, float(cfg.get("fade_in_s", 0.4)))

        if not cfg.get("enabled", True):
            LOG.info("音频已在配置中关闭")
            return

        try:
            if pygame.mixer.get_init() is None:
                pygame.mixer.init(frequency=SAMPLE_RATE, size=-16,
                                  channels=1, buffer=512)
            pygame.mixer.set_num_channels(8)
            self.engine_sounds = self._build_engine_sounds()
            self.pitch_steps = len(self.engine_sounds)
            try:
                self._build_extra_sounds(pack)
            except (OSError, wave.Error, ValueError) as exc:
                LOG.warning("换挡采样加载失败，跳过换挡声：%s", exc)
                self.shift_sound = None
            self.slip_sound = pygame.mixer.Sound(buffer=_slip_loop())
            self.crash_sound = pygame.mixer.Sound(buffer=_crash_hit())
            self.beep_sound = pygame.mixer.Sound(buffer=_warning_beep())
            self._chan_a = pygame.mixer.Channel(6)
            self._chan_b = pygame.mixer.Channel(7)
            self._chan_idle = pygame.mixer.Channel(2)
            self._chan_slip = pygame.mixer.Channel(5)
            self._chan_shift = pygame.mixer.Channel(3)
            self._chan_crash = pygame.mixer.Channel(1)
            self._chan_beep = pygame.mixer.Channel(4)
            self.enabled = True
            LOG.info("音频已启用：发动机 %d 档（%s）+ 换挡/撞墙/打滑（采样率 %d Hz）",
                     len(self.engine_sounds), self.engine_source, SAMPLE_RATE)
        except (pygame.error, OSError, ValueError, wave.Error) as exc:
            LOG.warning("音频初始化失败，本次静音运行：%s", exc)
            self.enabled = False

    # ------------------------------------------------------------------ 内部
    def _resolve(self, path):
        if not path:
            return ""
        if os.path.isabs(path):
            return path
        base = self.project_dir or os.getcwd()
        return os.path.join(str(base), path)

    def _build_engine_sounds(self):
        pack = self.sample_pack
        if pack.get("enabled", True):
            try:
                if pack.get("run_engine_files"):
                    sounds = self._build_sample_group_sounds(pack)
                    if sounds is not None:
                        self.engine_source = "sample_groups"
                        return sounds
                sounds = self._build_sample_engine_sounds(pack)
                if sounds is not None:
                    self.engine_source = "sample"
                    return sounds
            except (IOError, OSError, wave.Error, ValueError, MemoryError) as exc:
                LOG.warning("采样包加载失败，改用合成声：%s", exc)
        self.engine_source = "synth"
        ratio = RPM_MAX / RPM_MIN
        sounds = []
        for index in range(NUM_PITCHES):
            rpm = RPM_MIN * (ratio ** (index / float(NUM_PITCHES - 1)))
            firing = rpm / 30.0
            sounds.append(pygame.mixer.Sound(buffer=_engine_loop(firing)))
        return sounds

    def _build_sample_group_sounds(self, pack):
        """用 loop-8..13 作为素材，按 RPM 生成频率近似正比的 32 档音色表。"""
        idle_file = pack.get("engine_file") or ""
        run_files = list(pack.get("run_engine_files") or [])
        if not idle_file or not run_files:
            return None
        idle_path = self._resolve(idle_file)
        run_paths = [self._resolve(item) for item in run_files]
        for path in [idle_path] + run_paths:
            if not os.path.isfile(path):
                LOG.info("分组采样文件不存在，使用合成声：%s", path)
                return None
        target_peak = float(pack.get("target_peak", 0.55))
        frequencies = [float(value) for value in pack.get(
            "run_engine_frequencies") or []]
        if len(frequencies) != len(run_paths):
            LOG.info("运行采样缺少频率表，使用默认分组频率")
            frequencies = [73.5, 82.5, 92.5, 104.0, 116.5, 131.0]
            frequencies = frequencies[:len(run_paths)]
            while len(frequencies) < len(run_paths):
                frequencies.append(frequencies[-1] * 1.15)
        run_seconds = float(pack.get("run_loop_seconds", 1.5))
        run_seconds = max(0.5, min(4.0, run_seconds))
        steps = int(pack.get("pitch_steps", 64))
        steps = max(32, min(256, steps))
        samples = []
        for path in run_paths:
            values = _load_wav_samples(path, target_peak)
            limit = int(SAMPLE_RATE * run_seconds)
            if len(values) > limit:
                values = values[:limit]
            samples.append(values)
        # 32 档 RPM 表：每一档选择自然频率最接近目标点火频率的素材，再重采样
        sounds = []
        ratio = RPM_MAX / RPM_MIN
        for index in range(steps):
            rpm = RPM_MIN * (ratio ** (index / float(steps - 1)))
            target = rpm / 30.0  # 4 缸 4 冲程点火频率
            source_index = min(range(len(frequencies)),
                               key=lambda item: abs(frequencies[item] - target))
            factor = target / max(1.0, frequencies[source_index])
            factor = max(0.40, min(2.50, factor))
            output = _resample_loop(samples[source_index], factor, target_peak)
            sounds.append(pygame.mixer.Sound(buffer=_to_pcm(output)))
        idle = _load_wav_samples(idle_path, target_peak)
        idle_factor = float(pack.get("idle_pitch_factor", 1.0))
        if abs(idle_factor - 1.0) > 1e-6:
            idle = _resample_loop(idle, idle_factor, target_peak)
        self.idle_sound = pygame.mixer.Sound(buffer=_to_pcm(idle))
        self.sample_file = idle_path
        self.sample_run_count = len(run_paths)
        LOG.info("采样包分组：怠速 %s + 运行 %d 段，按 RPM 生成 %d 档点火频率表",
                 os.path.basename(idle_path), len(run_paths), steps)
        return sounds

    def _build_extra_sounds(self, pack):
        self.shift_sound = None
        shift_file = pack.get("shift_file") or ""
        if shift_file:
            path = self._resolve(shift_file)
            if os.path.isfile(path):
                target_peak = float(pack.get("target_peak", 0.55))
                self.shift_sound = pygame.mixer.Sound(buffer=_to_pcm(
                    _load_wav_samples(path, min(0.9, target_peak * 1.25))))
            else:
                LOG.info("换挡采样不存在，跳过换挡声：%s", path)

    def _build_sample_engine_sounds(self, pack):
        """兼容旧的单文件模式：把一个采样重采样成 32 档音色表。"""
        engine_file = pack.get("engine_file") or ""
        if not engine_file:
            return None
        path = self._resolve(engine_file)
        if not os.path.isfile(path):
            LOG.info("采样包文件不存在，使用合成声：%s", path)
            return None
        values, rate = _read_wav_mono(path)
        if len(values) < rate * 0.2:
            LOG.warning("采样包太短（<0.2 s），使用合成声：%s", path)
            return None
        loop_seconds = float(pack.get("loop_seconds", 0.5))
        loop_seconds = max(0.15, min(2.0, loop_seconds))
        start_setting = pack.get("loop_start_s")
        if start_setting is None:
            start = _choose_loop_start(values, rate, loop_seconds)
        else:
            start = int(float(start_setting) * rate)
        start = max(0, min(start, len(values) - 1))
        f0 = _estimate_f0(values, start, rate, loop_seconds)
        loop = _extract_loop(values, start, rate, loop_seconds, f0)
        average = _mean(loop)
        loop = [value - average for value in loop]
        base_rpm = float(pack.get("base_rpm", 2400.0))
        if base_rpm <= 0.0:
            base_rpm = 2400.0
        low_factor = float(pack.get("min_pitch_factor", 0.45))
        high_factor = float(pack.get("max_pitch_factor", 2.60))
        target_peak = float(pack.get("target_peak", 0.55))
        ratio = RPM_MAX / RPM_MIN
        sounds = []
        for index in range(NUM_PITCHES):
            rpm = RPM_MIN * (ratio ** (index / float(NUM_PITCHES - 1)))
            factor = rpm / base_rpm
            factor = max(low_factor, min(high_factor, factor))
            samples = _resample_loop(loop, factor, target_peak)
            sounds.append(pygame.mixer.Sound(buffer=_to_pcm(samples)))
        self.sample_file = path
        self.sample_loop_start = start / float(rate)
        self.sample_f0 = f0
        self.base_rpm = base_rpm
        LOG.info("采样包发动机声：%s（%.1f s，循环起点 %.2f s，基频 %.1f Hz）",
                 os.path.basename(path), len(values) / float(rate),
                 self.sample_loop_start, f0)
        return sounds

    def _ensure_voice(self, index, target_indices):
        """确保某个目标音高在 A/B 两个 voice 之一上。

        关键：移动音高时只替换“当前不在目标集合里”的 voice，
        另一个 voice 继续发声，避免两路同时重启造成断开/断断续续。
        """
        if not self.engine_sounds:
            return
        index = max(0, min(len(self.engine_sounds) - 1, int(index)))
        if self._sound_a == index or self._sound_b == index:
            return
        candidates = []
        if self._sound_a not in target_indices:
            candidates.append(("a", self._chan_a, self._chan_a.get_volume()))
        if self._sound_b not in target_indices:
            candidates.append(("b", self._chan_b, self._chan_b.get_volume()))
        if not candidates:
            candidates = [("a", self._chan_a, self._chan_a.get_volume()),
                          ("b", self._chan_b, self._chan_b.get_volume())]
        slot, channel, _ = min(candidates, key=lambda item: item[2])
        channel.set_volume(0.0)
        channel.play(self.engine_sounds[index], loops=-1, fade_ms=25)
        if slot == "a":
            self._sound_a = index
        else:
            self._sound_b = index

    def _set_voice_volumes(self, low_index, low_volume, high_index, high_volume):
        for slot, channel in (("a", self._chan_a), ("b", self._chan_b)):
            if channel is None:
                continue
            index = self._sound_a if slot == "a" else self._sound_b
            if index == low_index and index == high_index:
                volume = low_volume + high_volume
            elif index == low_index:
                volume = low_volume
            elif index == high_index:
                volume = high_volume
            else:
                volume = 0.0
            channel.set_volume(max(0.0, volume))

    def _ensure_idle(self):
        if self._chan_idle is None or self.idle_sound is None:
            return
        if not self._chan_idle.get_busy():
            self._chan_idle.set_volume(0.0)
            self._chan_idle.play(self.idle_sound, loops=-1, fade_ms=120)

    def _rpm_position(self, rpm):
        clamped = max(RPM_MIN, min(RPM_MAX, rpm))
        ratio = math.log(clamped / RPM_MIN) / math.log(RPM_MAX / RPM_MIN)
        return ratio * (self.pitch_steps - 1)

    def _run_position(self, rpm):
        if self.sample_run_count <= 1:
            return 0.0
        clamped = max(RPM_MIN, min(RPM_MAX, rpm))
        ratio = math.log(clamped / RPM_MIN) / math.log(RPM_MAX / RPM_MIN)
        return ratio * (self.sample_run_count - 1)

    # ------------------------------------------------------------------ 对外
    def toggle_mute(self):
        self.muted = not self.muted
        if self.muted:
            self._silence()
            if self._chan_crash is not None:
                self._chan_crash.stop()
        return self.muted

    def warning_beep(self):
        """WRONG WAY 闪烁显示期间播放一次短提示音（静音/禁用时安全忽略）。"""
        if (not self.enabled or self.muted or self.startup_gain < 0.99
                or self.beep_sound is None):
            return
        if self._chan_beep is None:
            return
        self._chan_beep.set_volume(self.master_volume)
        self._chan_beep.play(self.beep_sound)

    def _play_shift(self):
        if (not self.enabled or self.muted or self.startup_gain < 0.99
                or self.shift_sound is None or self._chan_shift is None):
            return
        self._chan_shift.set_volume(self.master_volume * 0.8)
        self._chan_shift.play(self.shift_sound)

    def _play_crash(self, strength):
        if (not self.enabled or self.muted or self.startup_gain < 0.99
                or self.crash_sound is None or self._chan_crash is None):
            return
        now = time.time()
        if now < self._crash_ready_at:
            return
        self._crash_ready_at = now + 0.35
        volume = min(1.0, max(0.25, strength / 18.0))
        self._chan_crash.set_volume(self.master_volume * self.crash_volume * volume)
        self._chan_crash.play(self.crash_sound)

    def _update_generic_engine(self, telemetry, gain):
        rpm = telemetry.rpm
        pos = self._rpm_position(rpm)
        index = int(pos)
        frac = pos - index
        next_index = min(index + 1, self.pitch_steps - 1)
        if next_index == index:
            frac = 0.0
        targets = (index,) if next_index == index else (index, next_index)
        for target in targets:
            self._ensure_voice(target, targets)
        self._set_voice_volumes(index, gain * (1.0 - frac),
                                next_index, gain * frac)

    def _update_sample_groups(self, telemetry, speed_abs):
        load = min(1.0, max(0.0, telemetry.throttle / 0.9))
        gain = (self.master_volume * self.engine_volume
                * (0.30 + 0.70 * load) * self.startup_gain)
        idle_mix = min(1.0, max(0.0, 1.0 - speed_abs / 2.5))
        run_gain = gain * (1.0 - idle_mix)
        self._ensure_idle()
        if self._chan_idle is not None:
            self._chan_idle.set_volume(max(0.0, gain * idle_mix * 0.9))
        self._update_generic_engine(telemetry, run_gain)

    def update(self, telemetry, paused=False):
        """每渲染帧调一次：按转速/油门/滑移/挡位/撞墙更新声音。"""
        if not self.enabled:
            return
        if telemetry is None:
            self._silence()
            return
        speed_abs = abs(float(getattr(telemetry, "speed_abs", 0.0)))
        gear = int(getattr(telemetry, "gear", 1))
        wall_hit = bool(getattr(telemetry, "wall_hit", False))
        if self._last_gear is None:
            self._last_gear = gear
        gear_changed = gear != self._last_gear
        self._last_gear = gear
        now = time.time()
        if self._first_update_at is None:
            self._first_update_at = now
        elapsed = now - self._first_update_at
        if elapsed < self.startup_delay_s:
            self.startup_gain = 0.0
        else:
            fade = self.fade_in_s
            self.startup_gain = 1.0 if fade <= 0.0 else min(
                1.0, (elapsed - self.startup_delay_s) / fade)
        if paused or self.muted or self.startup_gain <= 0.0:
            self._silence()
            self._last_speed = speed_abs
            self._wall_was_hit = wall_hit
            return
        if gear_changed:
            self._play_shift()

        load = min(1.0, max(0.0, telemetry.throttle / 0.9))
        if self.engine_source == "sample_groups":
            self._update_sample_groups(telemetry, speed_abs)
        else:
            gain = (self.master_volume * self.engine_volume
                    * (0.30 + 0.70 * load) * self.startup_gain)
            self._update_generic_engine(telemetry, gain)
            if self._chan_idle is not None:
                self._chan_idle.set_volume(0.0)

        # 打滑/尖叫
        slip = min(1.0, max(0.0, telemetry.slip_amount))
        if self._chan_slip is not None:
            volume = (self.master_volume * self.slip_volume * slip * 0.8
                      * self.startup_gain)
            if slip > 0.04:
                if not self._slip_playing:
                    self._chan_slip.play(self.slip_sound, loops=-1)
                    self._slip_playing = True
                self._chan_slip.set_volume(volume)
            elif self._slip_playing:
                self._chan_slip.set_volume(0.0)
                self._chan_slip.fadeout(120)
                self._slip_playing = False

        # 撞墙：只在开始碰撞的那一帧触发，音量参考碰撞前速度
        if wall_hit and not self._wall_was_hit:
            self._play_crash(self._last_speed)
        self._wall_was_hit = wall_hit
        self._last_speed = speed_abs

    def _silence(self):
        self._set_engine_channels(0.0, 0.0)
        if self._chan_idle is not None:
            self._chan_idle.set_volume(0.0)
        if self._chan_slip is not None:
            self._chan_slip.set_volume(0.0)

    def _set_engine_channels(self, volume_a, volume_b=None):
        if self._chan_a is not None:
            self._chan_a.set_volume(max(0.0, volume_a))
        if self._chan_b is not None:
            self._chan_b.set_volume(max(0.0, volume_b if volume_b is not None else 0.0))

    def close(self):
        if not self.enabled:
            return
        try:
            for channel in (self._chan_a, self._chan_b, self._chan_idle,
                            self._chan_slip, self._chan_shift, self._chan_crash):
                if channel is not None:
                    channel.stop()
        except pygame.error:
            pass
