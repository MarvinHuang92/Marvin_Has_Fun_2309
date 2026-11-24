# -*- coding: utf-8 -*-
"""音频冒烟测试（需要 pygame；用 SDL 的 dummy 音频设备，不出声）。

跑法::

    python scripts/tests_audio.py

验证：音色表生成、通道分配、按转速/打滑更新音量、静音切换、无音频设备时降级，
以及可选采样包（WAV 加载、自动循环段、缺失时回退合成声）。
"""
import array
import math
import os
import shutil
import sys
import tempfile
import wave

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

_results = []


def check(name, ok, detail=""):
    _results.append((name, bool(ok), detail))
    print("[%s] %s%s" % ("PASS" if ok else "FAIL", name,
                         ("  <- " + detail) if detail else ""))


def _write_test_wav(path, rate=22050, seconds=2.0):
    """生成一段双声道 PCM WAV（150 Hz + 300 Hz 谐波），用于测试采样包。"""
    frames = int(rate * seconds)
    data = array.array("h")
    for index in range(frames):
        t = index / float(rate)
        value = 0.42 * math.sin(2.0 * math.pi * 150.0 * t)
        value += 0.20 * math.sin(2.0 * math.pi * 300.0 * t + 0.7)
        sample = int(value * 26000.0)
        data.append(sample)
        data.append(sample)
    with wave.open(path, "wb") as writer:
        writer.setnchannels(2)
        writer.setsampwidth(2)
        writer.setframerate(rate)
        writer.writeframes(data.tobytes())


class FakeTelemetry(object):
    def __init__(self, rpm, throttle, slip):
        self.rpm = rpm
        self.throttle = throttle
        self.slip_amount = slip


def main():
    try:
        import pygame
        from minirace.audio import Audio, NUM_PITCHES
    except ImportError as exc:
        print("无法导入 pygame/音频模块：%s" % exc)
        return 1

    audio = Audio({})
    check("音频初始化（%d 档音色）" % NUM_PITCHES,
          audio.enabled and len(audio.engine_sounds) == NUM_PITCHES,
          "enabled=%s, sounds=%d" % (audio.enabled, len(audio.engine_sounds)))

    if not audio.enabled:
        print("（当前环境没有可用音频设备，后续通道测试跳过）")
        audio.close()
        return 0

    audio.update(FakeTelemetry(rpm=3000.0, throttle=0.8, slip=0.0))
    busy_a = audio._chan_a.get_busy()
    busy_b = audio._chan_b.get_busy()
    volumes = (audio._chan_a.get_volume(), audio._chan_b.get_volume())
    check("发动机双通道交叉淡化已开始播放",
          busy_a and busy_b and sum(volumes) > 0.0,
          "busy=(%s,%s)，volumes=(%.2f,%.2f)" % (
              busy_a, busy_b, volumes[0], volumes[1]))

    # 转速变化后音色索引应变化（重播到新音色）
    before = audio._sound_a
    audio.update(FakeTelemetry(rpm=6800.0, throttle=0.9, slip=0.0))
    after = audio._sound_a
    check("转速升高后切换到更高音色", after >= before,
          "sound index %d -> %d" % (before, after))

    audio.update(FakeTelemetry(rpm=5000.0, throttle=0.9, slip=0.8))
    slip_busy = audio._chan_slip.get_busy()
    slip_volume = audio._chan_slip.get_volume()
    check("出现打滑时播放尖叫音并给音量",
          slip_busy and slip_volume > 0.0,
          "busy=%s，volume=%.2f" % (slip_busy, slip_volume))

    muted = audio.toggle_mute()
    audio.update(FakeTelemetry(rpm=5000.0, throttle=0.9, slip=0.8))
    check("静音后发动机通道音量为 0", muted and audio._chan_a.get_volume() == 0.0,
          "muted=%s" % muted)
    audio.toggle_mute()

    audio.close()
    check("关闭后停止播放", not audio._chan_a.get_busy())

    off = Audio({"enabled": False})
    check("配置关闭音频时安全降级", not off.enabled)
    off.update(FakeTelemetry(3000.0, 1.0, 1.0))
    off.close()

    # ---------------------------------------------------------- 可选采样包
    tmp = tempfile.mkdtemp(prefix="mini_race_audio_")
    try:
        wav_path = os.path.join(tmp, "engine_test.wav")
        _write_test_wav(wav_path)
        sample = Audio({
            "sample_pack": {
                "enabled": True,
                "engine_file": "engine_test.wav",
                "loop_start_s": 0.2,
                "loop_seconds": 0.5,
                "base_rpm": 2400.0,
            },
        }, project_dir=tmp)
        check("采样包 WAV 能加载并生成 %d 档音色" % NUM_PITCHES,
              sample.enabled and sample.engine_source == "sample"
              and len(sample.engine_sounds) == NUM_PITCHES,
              "source=%s, sounds=%d" % (sample.engine_source, len(sample.engine_sounds)))
        if sample.enabled and sample.engine_sounds:
            lengths = set(round(sound.get_length(), 4)
                          for sound in sample.engine_sounds)
            check("采样包音色随转速有不同长度（变调生效）",
                  len(lengths) > 8,
                  "%d 种长度，首/末 %.3f/%.3f s" % (
                      len(lengths), sample.engine_sounds[0].get_length(),
                      sample.engine_sounds[-1].get_length()))
        sample.close()

        fallback = Audio({
            "sample_pack": {"enabled": True, "engine_file": "missing.wav"},
        }, project_dir=tmp)
        check("采样包文件缺失时回退到合成声",
              fallback.enabled and fallback.engine_source == "synth",
              "source=%s" % fallback.engine_source)
        fallback.close()
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    pygame.mixer.quit()
    failed = [name for name, ok, _ in _results if not ok]
    print()
    print("%d/%d 项通过" % (len(_results) - len(failed), len(_results)))
    if failed:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
