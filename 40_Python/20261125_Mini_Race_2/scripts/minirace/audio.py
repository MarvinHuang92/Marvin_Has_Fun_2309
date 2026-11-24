# -*- coding: utf-8 -*-
"""音频：发动机声（随转速变调）+ 打滑/尖叫（随滑移量变响）。

默认**不依赖任何音频素材**，用标准库合成 16-bit 单声道 PCM：
- 发动机：按"点火频率 = rpm/30"（4 缸 4 冲程）合成含谐波的循环，做成一张
  32 档的音色表；运行时按转速取相邻两档，用两个通道交叉淡化（pygame 不能实时变调）。
- 打滑：合成一条带拍频的尖叫循环，音量跟随 ``telemetry.slip_amount``。

可选**采样包**（``audio.sample_pack``）：如果配置的文件存在，就从 WAV 里自动挑一段
平稳片段做无缝循环，再重采样成同样的 32 档音色表；文件不存在/格式不支持时自动回退
到合成声。素材文件建议放在 ``sounds/``（已加入 .gitignore，不随代码提交）。

没有可用的音频设备/混音器时 :class:`Audio` 自动降级为静音，不影响模拟器。
"""
import array
import logging
import math
import os
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
    "engine_file": "sounds/引擎声音.wav",
    "loop_start_s": None,        # None = 自动挑平稳段
    "loop_seconds": 0.5,
    "base_rpm": 2400.0,          # 采样对应的发动机转速（用于换算变调倍率）
    "min_pitch_factor": 0.45,
    "max_pitch_factor": 2.60,
    "target_peak": 0.55,
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


class Audio(object):
    """发动机 + 打滑音效。初始化失败时 ``enabled`` 为 False，全部调用安全。"""

    def __init__(self, config=None, project_dir=None):
        cfg = config or {}
        self.enabled = False
        self.muted = False
        self.project_dir = project_dir
        self.engine_sounds = []
        self.engine_source = "synth"
        self.sample_file = None
        self.sample_loop_start = None
        self.sample_f0 = 0.0
        self.base_rpm = None
        self.slip_sound = None
        self.beep_sound = None
        self._chan_a = None
        self._chan_beep = None
        self._chan_b = None
        self._chan_slip = None
        self._sound_a = -1
        self._sound_b = -1
        self._slip_playing = False
        self.master_volume = float(cfg.get("master_volume", 0.35))
        self.engine_volume = float(cfg.get("engine_volume", 0.9))
        self.slip_volume = float(cfg.get("slip_volume", 0.7))
        pack = dict(SAMPLE_PACK_DEFAULTS)
        pack.update(cfg.get("sample_pack") or {})
        self.sample_pack = pack

        if not cfg.get("enabled", True):
            LOG.info("音频已在配置中关闭")
            return

        try:
            if pygame.mixer.get_init() is None:
                pygame.mixer.init(frequency=SAMPLE_RATE, size=-16,
                                  channels=1, buffer=512)
            pygame.mixer.set_num_channels(8)
            self.engine_sounds = self._build_engine_sounds()
            self.slip_sound = pygame.mixer.Sound(buffer=_slip_loop())
            self.beep_sound = pygame.mixer.Sound(buffer=_warning_beep())
            self._chan_a = pygame.mixer.Channel(6)
            self._chan_beep = pygame.mixer.Channel(4)
            self._chan_b = pygame.mixer.Channel(7)
            self._chan_slip = pygame.mixer.Channel(5)
            self.enabled = True
            LOG.info("音频已启用：%d 档发动机音色（%s）+ 打滑音（采样率 %d Hz）",
                     len(self.engine_sounds), self.engine_source, SAMPLE_RATE)
        except (pygame.error, OSError, ValueError) as exc:
            LOG.warning("音频初始化失败，本次静音运行：%s", exc)
            self.enabled = False

    # ------------------------------------------------------------------ 内部
    def _build_engine_sounds(self):
        if self.sample_pack.get("enabled", True):
            try:
                sounds = self._build_sample_engine_sounds(self.sample_pack)
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

    def _build_sample_engine_sounds(self, pack):
        engine_file = pack.get("engine_file") or ""
        if not engine_file:
            return None
        path = engine_file
        if not os.path.isabs(path):
            base = self.project_dir or os.getcwd()
            path = os.path.join(str(base), path)
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
        LOG.info("采样包发动机声：%s（%.1f s，循环起点 %.2f s，基频 %.1f Hz，基转速 %.0f rpm）",
                 os.path.basename(path), len(values) / float(rate),
                 self.sample_loop_start, f0, base_rpm)
        return sounds

    def _ensure_channel(self, channel, slot_name, index):
        """让某个通道播放指定音色；音色没变就不重播（避免每帧 reset 造成爆音）。"""
        if channel is None:
            return
        if getattr(self, slot_name) == index:
            return
        channel.play(self.engine_sounds[index], loops=-1, fade_ms=25)
        setattr(self, slot_name, index)

    def _rpm_position(self, rpm):
        clamped = max(RPM_MIN, min(RPM_MAX, rpm))
        ratio = math.log(clamped / RPM_MIN) / math.log(RPM_MAX / RPM_MIN)
        return ratio * (NUM_PITCHES - 1)

    # ------------------------------------------------------------------ 对外
    def toggle_mute(self):
        self.muted = not self.muted
        if self.muted:
            self._set_engine_channels(0.0)
            if self._chan_slip is not None:
                self._chan_slip.set_volume(0.0)
        return self.muted

    def warning_beep(self):
        """WRONG WAY 闪烁显示期间播放一次短提示音（静音/禁用时安全忽略）。"""
        if not self.enabled or self.muted or self.beep_sound is None:
            return
        if self._chan_beep is None:
            return
        self._chan_beep.set_volume(self.master_volume)
        self._chan_beep.play(self.beep_sound)

    def update(self, telemetry, paused=False):
        """每渲染帧调一次：按转速/油门/滑移量更新音量。"""
        if not self.enabled:
            return
        if telemetry is None or paused or self.muted:
            self._set_engine_channels(0.0)
            if self._chan_slip is not None:
                self._chan_slip.set_volume(0.0)
            return

        rpm = telemetry.rpm
        pos = self._rpm_position(rpm)
        index = int(pos)
        frac = pos - index
        next_index = min(index + 1, NUM_PITCHES - 1)
        if next_index == index:
            frac = 0.0
        load = min(1.0, max(0.0, telemetry.throttle / 0.9))
        gain = self.master_volume * self.engine_volume * (0.30 + 0.70 * load)
        self._ensure_channel(self._chan_a, "_sound_a", index)
        self._ensure_channel(self._chan_b, "_sound_b", next_index)
        self._set_engine_channels(gain * (1.0 - frac), gain * frac)

        # 打滑/尖叫
        slip = min(1.0, max(0.0, telemetry.slip_amount))
        if self._chan_slip is not None:
            volume = self.master_volume * self.slip_volume * slip * 0.8
            if slip > 0.04:
                if not self._slip_playing:
                    self._chan_slip.play(self.slip_sound, loops=-1)
                    self._slip_playing = True
                # 先播放再设音量：带 fade_ms 的 play 会先把音量拉到 0
                self._chan_slip.set_volume(volume)
            elif self._slip_playing:
                self._chan_slip.set_volume(0.0)
                self._chan_slip.fadeout(120)
                self._slip_playing = False

    def _set_engine_channels(self, volume_a, volume_b=None):
        if self._chan_a is not None:
            self._chan_a.set_volume(max(0.0, volume_a))
        if self._chan_b is not None:
            self._chan_b.set_volume(max(0.0, volume_b if volume_b is not None else 0.0))

    def close(self):
        if not self.enabled:
            return
        try:
            if self._chan_a is not None:
                self._chan_a.stop()
            if self._chan_b is not None:
                self._chan_b.stop()
            if self._chan_slip is not None:
                self._chan_slip.stop()
        except pygame.error:
            pass
