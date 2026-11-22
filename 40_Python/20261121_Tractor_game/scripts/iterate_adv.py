# -*- coding: utf-8 -*-
"""一次迭代：在新分布上重训 V，再用新 V 重算优势，再训优势网络。

输入是 `selfplay_adv.py` 产出的 CSV（局面60 + 动作15 + A + R = 77 列）。
A 列只是参考，这里**会用新 V 重算**，所以是真正的一轮迭代。

跑法::

    python scripts/iterate_adv.py game_log/r1.csv models/value_r1.json models/adv_r1.json
"""
from __future__ import annotations

import json
import os
import sys

import numpy as np


def train_mlp(x, y, hidden, epochs, seed, lr=1e-3, bs=1024, verbose=True):
    """标准化 + Adam + MSE，返回 (w1,b1,w2,b2,mu,sd,mse,corr)。"""
    rng = np.random.default_rng(seed)
    n, dim = x.shape
    idx = rng.permutation(n)
    split = int(n * 0.9)
    tr, va = idx[:split], idx[split:]

    mu = x[tr].mean(axis=0)
    sd = x[tr].std(axis=0)
    sd[sd < 1e-6] = 1.0
    xs = (x - mu) / sd
    xt, yt = xs[tr], y[tr]
    xv, yv = xs[va], y[va]

    w1 = rng.normal(0, 0.05, (hidden, dim))
    b1 = np.zeros(hidden)
    w2 = rng.normal(0, 0.05, (1, hidden))
    b2 = np.zeros(1)
    params = [w1, b1, w2, b2]
    m = [np.zeros_like(p) for p in params]
    v = [np.zeros_like(p) for p in params]
    beta1, beta2, eps = 0.9, 0.999, 1e-8
    step = 0

    for ep in range(epochs):
        order = rng.permutation(len(xt))
        for i in range(0, len(order), bs):
            b = order[i:i + bs]
            xb, yb = xt[b], yt[b].reshape(-1, 1)
            h_pre = xb @ w1.T + b1
            h = np.maximum(h_pre, 0)
            pred = h @ w2.T + b2
            d = (pred - yb) * (2.0 / len(b))
            gw2 = d.T @ h
            gb2 = d.sum(axis=0)
            dh = d @ w2
            dh[h_pre <= 0] = 0
            gw1 = dh.T @ xb
            gb1 = dh.sum(axis=0)
            grads = [gw1, gb1, gw2, gb2]
            step += 1
            for k in range(4):
                m[k] = beta1 * m[k] + (1 - beta1) * grads[k]
                v[k] = beta2 * v[k] + (1 - beta2) * (grads[k] ** 2)
                params[k] -= lr * (m[k] / (1 - beta1 ** step)) / (
                    np.sqrt(v[k] / (1 - beta2 ** step)) + eps)
            w1, b1, w2, b2 = params

    h = np.maximum(xv @ w1.T + b1, 0)
    pv = (h @ w2.T + b2).ravel()
    mse = float(np.mean((yv - pv) ** 2))
    corr = float(np.corrcoef(pv, yv)[0, 1])
    if verbose:
        print("    hidden=%-4d MSE %.1f  corr %.3f" % (hidden, mse, corr))
    return w1, b1, w2, b2, mu, sd, mse, corr


def predict(x, w1, b1, w2, b2, mu, sd):
    xs = (x - mu) / sd
    h = np.maximum(xs @ w1.T + b1, 0)
    return (h @ w2.T + b2).ravel()


def save(path, w1, b1, w2, b2, mu, sd, extra):
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"w1": w1.tolist(), "b1": b1.tolist(),
                   "w2": w2.tolist(), "b2": b2.tolist(),
                   "mu": mu.tolist(), "sd": sd.tolist(), **extra}, f)
    print("    -> %s" % path)


def main():
    src = sys.argv[1]
    out_v = sys.argv[2]
    out_adv = sys.argv[3]
    hidden_v = int(sys.argv[4]) if len(sys.argv) > 4 else 192
    hidden_a = int(sys.argv[5]) if len(sys.argv) > 5 else 256
    epochs = int(sys.argv[6]) if len(sys.argv) > 6 else 150

    data = np.loadtxt(src, delimiter=",", dtype=np.float64)
    print("样本 %d 条，%d 列" % data.shape)
    x = data[:, :-2]           # 局面60 + 动作15
    r = data[:, -1]            # 真实结果
    sf = x[:, :60]
    print("  真实结果 R：均值 %+.1f 标准差 %.1f" % (r.mean(), r.std()))

    print("  1) 在新分布上重训 V（局面 -> R）")
    vw1, vb1, vw2, vb2, vmu, vsd, vmse, vcorr = train_mlp(
        sf, r, hidden_v, epochs, 20261126)
    save(out_v, vw1, vb1, vw2, vb2, vmu, vsd,
         {"val_mse": vmse, "val_corr": vcorr})

    print("  2) 用新 V 重算优势 A = R - V(s)")
    a = r - predict(sf, vw1, vb1, vw2, vb2, vmu, vsd)
    print("     A：均值 %+.2f 标准差 %.2f" % (a.mean(), a.std()))

    print("  3) 训练优势网络（局面+动作 -> A）")
    aw1, ab1, aw2, ab2, amu, asd, amse, acorr = train_mlp(
        x, a, hidden_a, epochs, 20261127)
    save(out_adv, aw1, ab1, aw2, ab2, amu, asd,
         {"val_mse": amse, "val_corr": acorr})
    return 0


if __name__ == "__main__":
    sys.exit(main())
