# -*- coding: utf-8 -*-
"""GPU 可行性探针：用这个项目的真实形状量 CPU vs GPU

测三件事（都是这个项目里真实存在的负载）：
  1. 训练一步（68 → H → 1，MSE + Adam，batch 见下表）
  2. 推理一次（batch 10 —— 游戏里每次决策要给 ≤10 张牌打分）
  3. 搜索一次（纯 Python 的 rollout，和 GPU 无关，用来说明"哪部分 GPU 帮不上"）

在只有 CPU 的机器上也能跑（GPU 部分会自动跳过）。
装了 CUDA 版 torch 之后，同一份脚本会多出一列 GPU 和加速比。

装 CUDA 版 torch（注意：Python 3.8 最高只能到 torch 2.4.1，不支持 RTX 5070 的 sm_120，
所以要用 3.13）：
    D:\\Programming\\Python_dir_3133\\python.exe -m pip install torch --index-url https://download.pytorch.org/whl/cu128

用法：
    python gpu_probe.py
    python gpu_probe.py --quick      # 少测几组，30 秒出结果
"""

import argparse
import time

import torch
import torch.nn as nn

IN_DIM = 68          # 40 维 state + 14 维老师特征 + 14 维动作 one-hot
WIDTHS = [30, 120, 400, 1600, 6400]
BATCHES = [256, 2048, 8000]
INFER_WIDTHS = [30, 400, 6400]
INFER_BATCHES = [10, 1024, 16384]


def device_info():
    print("=" * 74)
    print("环境")
    print("=" * 74)
    print("torch      : %s" % torch.__version__)
    print("CUDA 编译版 : %s" % (torch.version.cuda or "CPU-only 构建"))
    print("CPU 线程    : %d" % torch.get_num_threads())
    if torch.cuda.is_available():
        print("GPU        : %s（%d MiB）" % (
            torch.cuda.get_device_name(0),
            torch.cuda.get_device_properties(0).total_memory // (1024 * 1024)))
    else:
        print("GPU        : 不可用 —— 下面只有 CPU 列")
    print()


def make_model(width, device):
    return nn.Sequential(nn.Linear(IN_DIM, width), nn.ReLU(), nn.Linear(width, 1)).to(device)


def bench_train(width, batch, device, iters, warmup=3):
    model = make_model(width, device)
    opt = torch.optim.Adam(model.parameters(), lr=1e-3)
    lossf = nn.MSELoss()
    x = torch.randn(batch, IN_DIM, device=device)
    y = torch.randn(batch, 1, device=device)

    def step():
        opt.zero_grad()
        lossf(model(x), y).backward()
        opt.step()

    for _ in range(warmup):
        step()
    if device.type == "cuda":
        torch.cuda.synchronize()
    t0 = time.perf_counter()
    for _ in range(iters):
        step()
    if device.type == "cuda":
        torch.cuda.synchronize()
    return (time.perf_counter() - t0) / iters


def bench_infer(width, batch, device, iters=200):
    model = make_model(width, device).eval()
    x = torch.randn(batch, IN_DIM, device=device)
    with torch.no_grad():
        for _ in range(20):
            model(x)
        if device.type == "cuda":
            torch.cuda.synchronize()
        t0 = time.perf_counter()
        for _ in range(iters):
            model(x)
        if device.type == "cuda":
            torch.cuda.synchronize()
    return (time.perf_counter() - t0) / iters


def fmt(ms):
    return "%.3f" % ms if ms < 10 else "%.1f" % ms


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--quick", action="store_true", help="少测几组")
    args = ap.parse_args()
    widths = WIDTHS[:3] if args.quick else WIDTHS
    batches = BATCHES[:2] if args.quick else BATCHES
    iters = 10 if args.quick else 25

    has_gpu = torch.cuda.is_available()
    dev_cpu = torch.device("cpu")
    dev_gpu = torch.device("cuda") if has_gpu else None
    device_info()

    # ---------------- 训练 ----------------
    print("=" * 74)
    print("训练一步的耗时（毫秒）—— 68 → H → 1，MSE + Adam")
    print("=" * 74)
    if has_gpu:
        print("  %6s %7s %10s %10s %9s" % ("H", "batch", "CPU", "GPU", "加速比"))
    else:
        print("  %6s %7s %10s" % ("H", "batch", "CPU"))
    for w in widths:
        for b in batches:
            t_cpu = bench_train(w, b, dev_cpu, iters) * 1000
            line = "  %6d %7d %10s" % (w, b, fmt(t_cpu))
            if has_gpu:
                try:
                    t_gpu = bench_train(w, b, dev_gpu, iters) * 1000
                    line += " %10s %8.1fx" % (fmt(t_gpu), t_cpu / t_gpu)
                except RuntimeError as exc:      # 显存不够之类
                    line += " %10s %9s" % ("OOM", "-")
            print(line)
    print()

    # ---------------- 推理 ----------------
    print("=" * 74)
    print("推理一次的耗时（毫秒）—— 游戏里每次决策的 batch 是 ≤10")
    print("=" * 74)
    if has_gpu:
        print("  %6s %7s %11s %10s %9s" % ("H", "batch", "CPU", "GPU", "加速比"))
    else:
        print("  %6s %7s %11s" % ("H", "batch", "CPU"))
    for w in INFER_WIDTHS:
        for b in INFER_BATCHES:
            t_cpu = bench_infer(w, b, dev_cpu, 200) * 1000
            line = "  %6d %7d %11s" % (w, b, fmt(t_cpu))
            if has_gpu:
                t_gpu = bench_infer(w, b, dev_gpu, 200) * 1000
                line += " %10s %8.1fx" % (fmt(t_gpu), t_cpu / t_gpu)
            print(line)
    print()

    # ---------------- 纯 Python 搜索 ----------------
    print("=" * 74)
    print("搜索一次 rollout（纯 Python）")
    print("=" * 74)
    try:
        import game_6nimmt as g
        engine = g
    except Exception:
        engine = None
    if engine is None:
        print("  （跳过：当前解释器没装项目依赖）")
    else:
        rows = [[5, 17, 33], [12, 44], [26, 61, 88, 97], [70]]
        my_hand = [3, 19, 38, 55, 72, 90, 101]
        opps = [[7, 21, 42, 58, 77, 95, 103] for _ in range(3)]
        n = 200
        t0 = time.perf_counter()
        for _ in range(n):
            engine.simulateRestN(rows, my_hand, opps, 3, [2, 1, 4], my_hand[0], 104)
        dt = (time.perf_counter() - t0) / n * 1e6
        print("  4 人局单次 rollout: %.1f 微秒（纯 CPU 单线程，GPU 完全用不上）" % dt)
        print("  Lv3 一个决策 = 前 3 名 × 24 次 = 72 次 rollout ≈ %.1f 毫秒"
              % (dt * 72 / 1000))
    print()
    print("=" * 74)
    print("怎么读这张表")
    print("=" * 74)
    print("  加速比 < 1      -> GPU 更慢（小 batch、小模型的典型情况）")
    print("  加速比 1~3      -> 不值得为它引入 CUDA 依赖")
    print("  加速比 > 10     -> 值得，但要先确认这一步在你的总耗时里占比够大")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
