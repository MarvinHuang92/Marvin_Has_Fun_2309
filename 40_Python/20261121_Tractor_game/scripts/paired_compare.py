# -*- coding: utf-8 -*-
"""配对比较两个模型：同样的牌、同样的种子，逐局做差再求均值与置信区间。"""
import sys

import numpy as np


def load(path):
    xs = {}
    with open(path, encoding="utf-8") as f:
        for line in f:
            i, d = line.strip().split(",")
            xs[int(i)] = float(d)
    return xs


a = load(sys.argv[1])      # 例如 v4
b = load(sys.argv[2])      # 例如 v6
keys = sorted(set(a) & set(b))
d = np.array([a[k] - b[k] for k in keys])
n = len(d)
m = d.mean()
sd = d.std(ddof=1)
ci = 1.96 * sd / np.sqrt(n)
print("配对比较：%s - %s" % (sys.argv[1].split("\\")[-1], sys.argv[2].split("\\")[-1]))
print("  共同局数 %d" % n)
print("  逐局差的均值 %+.3f ±%.3f（正数 = 前者得分更高，即后者更强）" % (m, ci))
print("  前者胜 %d 局，后者胜 %d 局，平 %d 局"
      % (int((d > 0).sum()), int((d < 0).sum()), int((d == 0).sum())))
print("  单侧 t 检验 p ≈ %.3f" % (0.5 * (1 - np.math.erf(abs(m) / (sd / np.sqrt(n)) / np.sqrt(2)))
                                  if hasattr(np.math, "erf") else float("nan")))
