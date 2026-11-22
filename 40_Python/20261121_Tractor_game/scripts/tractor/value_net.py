"""价值网络：从真实对局结果学出来的「局面 → 期望净得分」。

这是自对弈这条路的第一个产物，也是**第一次用"这局最后赢没赢"当监督信号**
（之前的标签都来自手写启发式或搜索）。

## 设计

- **输入**：两边各 5 门 × 3 个统计（张数、分、该门最大牌力）+ 主牌数 + 缺门，
  再加当前比分、墩数、谁是庄家 → 共 47 维
- **输出**：从现在到局末，`team` 的期望**净得分**（和我队拿的 − 对方拿的）
- **部署**：纯 Python 推理（几个点积），**不需要 numpy**；numpy 只在训练时用

为什么按"队"而不是按"座位"排特征：两个座位共享同一个模型，团队视角天然对称。
"""
from __future__ import annotations

import json
import math
from typing import Dict, List, Optional, Sequence

from .cards import Card, card_points, is_trump
from .fast_state import FastState

FEATURE_DIM = 47
KINDS = ("T", "S", "H", "C", "D")
POWER_SCALE = 1200.0


def _kind_of(card: Card, level: int, trump) -> str:
    return "T" if is_trump(card, level, trump) else card.suit


_SUIT_IDX = {"S": 0, "H": 1, "C": 2, "D": 3}


def state_features(state: FastState, team: int) -> List[float]:
    """47 维特征。`team` 是"我们"这一队（0 或 1）。

    性能注意：这是搜索叶子的热路径（每个节点都调），所以内联了
    is_trump / card_points 的判断，避免逐张牌的函数调用。
    """
    level = state.level
    trump = state.trump_suit

    n = [[0, 0, 0, 0, 0], [0, 0, 0, 0, 0]]      # 张数
    pt = [[0, 0, 0, 0, 0], [0, 0, 0, 0, 0]]     # 分
    top = [[0, 0, 0, 0, 0], [0, 0, 0, 0, 0]]    # 该门最大牌力
    tr = [0, 0]                                  # 主牌数

    for s in range(4):
        bucket = 0 if (0 if s in (0, 2) else 1) == team else 1
        nb, ptb, topb = n[bucket], pt[bucket], top[bucket]
        for c in state.hands[s]:
            r = c.rank
            suit = c.suit
            if (suit == "J") or r == level or r == 2 or (trump is not None and suit == trump):
                k = 0
                tr[bucket] += 1
                if r == 16:
                    pw = 1000
                elif r == 15:
                    pw = 999
                elif suit == trump and r == level:
                    pw = 998
                elif r == level:
                    pw = 997
                elif suit == trump and r == 2:
                    pw = 996
                elif r == 2:
                    pw = 995
                else:
                    pw = 900 + r
            else:
                k = 1 + _SUIT_IDX[suit]
                pw = r
            nb[k] += 1
            if r == 5:
                ptb[k] += 5
            elif r == 10 or r == 13:
                ptb[k] += 10
            if pw > topb[k]:
                topb[k] = pw

    feats: List[float] = []
    for b in (0, 1):
        for k in range(5):
            feats.append(n[b][k] / 10.0)
            feats.append(pt[b][k] / 50.0)
            feats.append(top[b][k] / POWER_SCALE)
        feats.append(tr[b] / 10.0)
        for k in range(5):
            feats.append(1.0 if n[b][k] == 0 else 0.0)

    zt = 0 if state.zhuang in (0, 2) else 1
    feats.append(state.points[zt] / 100.0)
    feats.append(state.points[1 - zt] / 100.0)
    feats.append(state.trick_no / 25.0)
    feats.append(1.0 if zt == team else 0.0)
    feats.append((len(state.hands[0]) + len(state.hands[1])
                  + len(state.hands[2]) + len(state.hands[3])) / 100.0)
    assert len(feats) == FEATURE_DIM, len(feats)
    return feats


try:                       # 可选加速：有 numpy 就用，没有也能跑
    import numpy as _np
except Exception:          # pragma: no cover
    _np = None


class ValueNet:
    """两层 MLP。`predict` 是搜索叶子的热路径，所以能向量化就向量化。"""

    def __init__(self, w1: List[List[float]], b1: List[float],
                 w2: List[List[float]], b2: List[float],
                 mu: Optional[List[float]] = None,
                 sd: Optional[List[float]] = None) -> None:
        self.w1, self.b1, self.w2, self.b2 = w1, b1, w2, b2
        self.mu = mu or [0.0] * len(w1[0])
        self.sd = sd or [1.0] * len(w1[0])
        if _np is not None:
            self._W1 = _np.asarray(w1, dtype=_np.float64)
            self._b1 = _np.asarray(b1, dtype=_np.float64)
            self._w2 = _np.asarray(w2[0], dtype=_np.float64)
            self._b2 = float(b2[0])
            self._mu = _np.asarray(self.mu, dtype=_np.float64)
            self._sd = _np.asarray(self.sd, dtype=_np.float64)
        self.backend = "numpy" if _np is not None else "python"

    @classmethod
    def load(cls, path: str) -> "ValueNet":
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return cls(data["w1"], data["b1"], data["w2"], data["b2"],
                   data.get("mu"), data.get("sd"))

    def predict_features(self, feats: Sequence[float]) -> float:
        if _np is not None:
            x = (_np.asarray(feats, dtype=_np.float64) - self._mu) / self._sd
            h = x @ self._W1.T + self._b1
            h = _np.maximum(h, 0.0)
            return float(h @ self._w2 + self._b2)
        x = [(v - m) / sd for v, m, sd in zip(feats, self.mu, self.sd)]
        h = [0.0] * len(self.b1)
        for j in range(len(self.b1)):
            wj = self.w1[j]
            acc = self.b1[j]
            for i, v in enumerate(x):
                acc += wj[i] * v
            h[j] = acc if acc > 0 else 0.0
        out = self.b2[0]
        for j, v in enumerate(h):
            out += self.w2[0][j] * v
        return out

    def predict(self, state: FastState, team: int) -> float:
        return self.predict_features(state_features(state, team))


# ---------------------------------------------------------------------------
# 全局挂载：search.evaluate 会用
# ---------------------------------------------------------------------------
_ACTIVE: Optional[ValueNet] = None


def load_active(path: str) -> ValueNet:
    global _ACTIVE
    _ACTIVE = ValueNet.load(path)
    return _ACTIVE


def clear_active() -> None:
    global _ACTIVE
    _ACTIVE = None


def active() -> Optional[ValueNet]:
    return _ACTIVE
