# -*- coding: utf-8 -*-
"""用自对弈数据训练价值网络。

输入 47 维局面特征，输出"我方从现在到局末的期望净得分"。
标签来自**真实对局结果**（自对弈），不是手写启发式也不是搜索估值。

跑法::

    python scripts/train_value.py game_log/value_train.csv models/value_v1.json

训练用 numpy；**部署不需要 numpy**（前向是纯 Python 点积，见 tractor/value_net.py）。
"""
from __future__ import annotations

import json
import os
import sys

import numpy as np


def load(path):
    data = np.loadtxt(path, delimiter=",", dtype=np.float64)
    x = data[:, :-1]
    y = data[:, -1]
    return x, y


def main():
    src = sys.argv[1] if len(sys.argv) > 1 else "game_log/value_train.csv"
    out = sys.argv[2] if len(sys.argv) > 2 else "models/value_v1.json"
    hidden = int(sys.argv[3]) if len(sys.argv) > 3 else 64
    epochs = int(sys.argv[4]) if len(sys.argv) > 4 else 40

    x, y = load(src)
    n, dim = x.shape
    print("样本 %d 条，特征 %d 维" % (n, dim))
    print("  标签：均值 %+.2f  标准差 %.2f  最小 %+.0f  最大 %+.0f  零值占比 %.1f%%"
          % (y.mean(), y.std(), y.min(), y.max(), 100.0 * (np.abs(y) < 0.5).mean()))

    rng = np.random.default_rng(20261122)
    idx = rng.permutation(n)
    split = int(n * 0.9)
    tr, va = idx[:split], idx[split:]

    # 标准化特征（保存下来，部署时要用）
    mu = x[tr].mean(axis=0)
    sd = x[tr].std(axis=0)
    sd[sd < 1e-6] = 1.0
    xs = (x - mu) / sd

    xt, yt = xs[tr], y[tr]
    xv, yv = xs[va], y[va]

    # 基线 1：永远预测 0
    base0 = float(np.mean((yv - 0.0) ** 2))
    # 基线 2：线性回归（闭式解）
    A = np.hstack([xt, np.ones((len(xt), 1))])
    w_lin, *_ = np.linalg.lstsq(A, yt, rcond=None)
    pred_lin = np.hstack([xv, np.ones((len(xv), 1))]) @ w_lin
    base1 = float(np.mean((yv - pred_lin) ** 2))
    print("  基线 MSE：全预测 0 = %.2f，线性回归 = %.2f" % (base0, base1))

    # 两层 MLP
    w1 = rng.normal(0, 0.1, (hidden, dim))
    b1 = np.zeros(hidden)
    w2 = rng.normal(0, 0.1, (1, hidden))
    b2 = np.zeros(1)
    params = [w1, b1, w2, b2]
    m = [np.zeros_like(p) for p in params]
    v = [np.zeros_like(p) for p in params]
    lr, beta1, beta2, eps = 1e-3, 0.9, 0.999, 1e-8
    bs = 512
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
                mh = m[k] / (1 - beta1 ** step)
                vh = v[k] / (1 - beta2 ** step)
                params[k] -= lr * mh / (np.sqrt(vh) + eps)
            w1, b1, w2, b2 = params
        if (ep + 1) % 10 == 0 or ep == epochs - 1:
            h = np.maximum(xv @ w1.T + b1, 0)
            pv = (h @ w2.T + b2).ravel()
            mse = float(np.mean((yv - pv) ** 2))
            print("  epoch %3d  验证 MSE %.2f  （线性 %.2f）" % (ep + 1, mse, base1))

    h = np.maximum(xv @ w1.T + b1, 0)
    pv = (h @ w2.T + b2).ravel()
    mse = float(np.mean((yv - pv) ** 2))
    corr = float(np.corrcoef(pv, yv)[0, 1])
    print("最终：验证 MSE %.2f，相关系数 %.3f" % (mse, corr))

    os.makedirs(os.path.dirname(out) or ".", exist_ok=True)
    payload = {
        "w1": w1.tolist(), "b1": b1.tolist(),
        "w2": w2.tolist(), "b2": b2.tolist(),
        "mu": mu.tolist(), "sd": sd.tolist(),
        "val_mse": mse, "val_corr": corr,
        "note": "features 已按 (x-mu)/sd 标准化，推理时要同样处理",
    }
    with open(out, "w", encoding="utf-8") as f:
        json.dump(payload, f)
    print("已保存 -> %s" % out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
