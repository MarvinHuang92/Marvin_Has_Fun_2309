# -*- coding: utf-8 -*-
"""把两批优势数据（不同分布）混在一起，验证"对手池"能不能避免只克制上一版。

- `game_log/adv_all.csv`：heuristic 自对弈的分布（165 万条，76 列）
- `game_log/r1.csv`：adv_v2 自对弈的分布（23 万条，77 列，多了 R）

两批的 A 都是用 value_v4 算的，所以可以直接拼。

跑法::

    python scripts/mix_adv_data.py game_log/mix1.csv 400000
"""
from __future__ import annotations

import io
import os
import sys

import numpy as np


def load(path, n_cols, take=None):
    data = np.loadtxt(path, delimiter=",", dtype=np.float64)
    x = data[:, :75]
    a = data[:, n_cols - 2] if n_cols == 77 else data[:, -1]
    if take is not None and len(x) > take:
        rng = np.random.default_rng(20261128)
        idx = rng.choice(len(x), take, replace=False)
        x, a = x[idx], a[idx]
    return x, a


def main():
    out = sys.argv[1] if len(sys.argv) > 1 else "game_log/mix1.csv"
    take = int(sys.argv[2]) if len(sys.argv) > 2 else 400000

    x1, a1 = load("game_log/adv_all.csv", 76, take)
    x2, a2 = load("game_log/r1.csv", 77, None)
    print("heuristic 分布取 %d 条，adv_v2 分布 %d 条" % (len(x1), len(x2)))

    x = np.vstack([x1, x2])
    a = np.concatenate([a1, a2])
    print("合计 %d 条" % len(x))

    os.makedirs(os.path.dirname(out) or ".", exist_ok=True)
    with io.open(out, "w", encoding="utf-8") as f:
        for i in range(len(x)):
            f.write(",".join("%.3f" % v for v in x[i]))
            f.write(",%.3f\n" % a[i])
    print("已写入 %s" % out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
