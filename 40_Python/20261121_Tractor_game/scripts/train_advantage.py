# -*- coding: utf-8 -*-
"""训练「优势网络」：输入 (局面 60 维 + 动作 15 维)，输出这一手比平均好多少。

跑法::

    python scripts/train_advantage.py game_log/adv_train.csv models/adv_v1.json 128 120
"""
from __future__ import annotations

import json
import os
import sys

import numpy as np


def main():
    src = sys.argv[1] if len(sys.argv) > 1 else "game_log/adv_train.csv"
    out = sys.argv[2] if len(sys.argv) > 2 else "models/adv_v1.json"
    hidden = int(sys.argv[3]) if len(sys.argv) > 3 else 128
    epochs = int(sys.argv[4]) if len(sys.argv) > 4 else 120
    # AWR：按 exp(A/tau) 加权。tau<=0 就是普通的等权回归。
    awr_tau = float(sys.argv[5]) if len(sys.argv) > 5 else 0.0

    # 数据最后一列有可能是 **两列标签**（A 优势、R 实际结果）。
    # 老数据只有一列（A），新数据（selfplay_adv 加底牌之后）是两列。
    # 传第 6 个参数 two 显式声明，避免把 A 当成特征 → 标签泄漏（这会训出
    # 一个 0.99 相关但完全没用的模型）。
    two_labels = len(sys.argv) > 6 and sys.argv[6] == "two"
    data = np.loadtxt(src, delimiter=",", dtype=np.float64)
    if two_labels:
        x, y = data[:, :-2], data[:, -2]     # 特征 / 优势A（R 不参与训练）
    else:
        x, y = data[:, :-1], data[:, -1]
    n, dim = x.shape
    print("样本 %d 条，特征 %d 维" % (n, dim))
    print("  优势标签：均值 %+.2f  标准差 %.2f  p5 %+.0f  p95 %+.0f"
          % (y.mean(), y.std(), np.percentile(y, 5), np.percentile(y, 95)))

    rng = np.random.default_rng(20261123)
    idx = rng.permutation(n)
    split = int(n * 0.9)
    tr, va = idx[:split], idx[split:]

    mu = x[tr].mean(axis=0)
    sd = x[tr].std(axis=0)
    sd[sd < 1e-6] = 1.0
    xs = (x - mu) / sd
    xt, yt = xs[tr], y[tr]
    xv, yv = xs[va], y[va]

    if awr_tau > 0:
        # 权重归一到均值 1，方便和等权版本比较
        # **先把优势标准化**，否则 exp 会爆炸（A 跨度 ±100，tau=10 时权重到 1e8，
        # 等于只训练几个样本，模型直接退化成垃圾）。
        z = (y - y.mean()) / (y.std() + 1e-9)
        w_all = np.exp(z / awr_tau)
        w_all = w_all / w_all.mean()
        wt, wv = w_all[tr], w_all[va]
        print("  AWR：tau=%.1f，权重范围 %.3f ~ %.3f" % (awr_tau, w_all.min(), w_all.max()))
    else:
        wt = np.ones(len(tr))
        wv = np.ones(len(va))

    base0 = float(np.mean((yv - 0.0) ** 2))
    A = np.hstack([xt, np.ones((len(xt), 1))])
    w_lin, *_ = np.linalg.lstsq(A, yt, rcond=None)
    pred_lin = np.hstack([xv, np.ones((len(xv), 1))]) @ w_lin
    base1 = float(np.mean((yv - pred_lin) ** 2))
    print("  基线 MSE：全预测 0 = %.2f，线性回归 = %.2f" % (base0, base1))

    w1 = rng.normal(0, 0.05, (hidden, dim))
    b1 = np.zeros(hidden)
    w2 = rng.normal(0, 0.05, (1, hidden))
    b2 = np.zeros(1)
    params = [w1, b1, w2, b2]
    m = [np.zeros_like(p) for p in params]
    v = [np.zeros_like(p) for p in params]
    lr, beta1, beta2, eps = 1e-3, 0.9, 0.999, 1e-8
    bs = 1024
    step = 0

    for ep in range(epochs):
        order = rng.permutation(len(xt))
        for i in range(0, len(order), bs):
            b = order[i:i + bs]
            xb, yb = xt[b], yt[b].reshape(-1, 1)
            h_pre = xb @ w1.T + b1
            h = np.maximum(h_pre, 0)
            pred = h @ w2.T + b2
            wb = wt[b].reshape(-1, 1)
            d = (pred - yb) * wb * (2.0 / wb.sum())
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
        if (ep + 1) % 30 == 0 or ep == epochs - 1:
            h = np.maximum(xv @ w1.T + b1, 0)
            pv = (h @ w2.T + b2).ravel()
            print("  epoch %3d  验证 MSE %.2f  （线性 %.2f）"
                  % (ep + 1, float(np.mean((yv - pv) ** 2)), base1))

    h = np.maximum(xv @ w1.T + b1, 0)
    pv = (h @ w2.T + b2).ravel()
    mse = float(np.mean(((yv - pv) ** 2) * wv) / wv.mean())
    corr = float(np.corrcoef(pv, yv)[0, 1])
    # 排序能力：同一局内能不能把好手排在前面，这里只能看整体相关
    print("最终：验证 MSE %.2f，相关系数 %.3f" % (mse, corr))

    os.makedirs(os.path.dirname(out) or ".", exist_ok=True)
    with open(out, "w", encoding="utf-8") as f:
        json.dump({"w1": w1.tolist(), "b1": b1.tolist(),
                   "w2": w2.tolist(), "b2": b2.tolist(),
                   "mu": mu.tolist(), "sd": sd.tolist(),
                   "val_mse": mse, "val_corr": corr,
                   "awr_tau": awr_tau}, f)
    print("已保存 -> %s" % out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
