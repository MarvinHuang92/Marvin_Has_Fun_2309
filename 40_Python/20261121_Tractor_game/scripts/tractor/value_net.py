"""价值网络：从真实对局结果学出来的「局面 → 期望净得分」。

这是自对弈这条路的第一个产物，也是**第一次用"这局最后赢没赢"当监督信号**
（之前的标签都来自手写启发式或搜索）。

## 设计

- **输入**（60 维，**按"队"排而不是按"座位"排**，两队共享一个模型）：
  - 每队 5 门 × [张数, 分, 该门最大牌力] = 15
  - 每队 主牌数 + 5 个缺门标记 = 6
  - 每队 5 门的对数 = 5
  - 全局：庄家分、闲家分、墩数、我是不是庄家、剩余牌数 = 5
  - 本墩：桌上已打出的分、当前谁领先、打了几手 = 3
- **输出**：从现在到局末，`team` 的期望**净得分**（我队拿的 − 对方拿的）
- **部署**：numpy 可用就用（约 29 µs/次），否则退回纯 Python（约 200 µs/次）

为什么按"队"而不是按"座位"排特征：两个座位共享同一个模型，团队视角天然对称。
"""
from __future__ import annotations

import json
import math
from typing import Dict, List, Optional, Sequence

from .cards import Card, card_points, is_trump
from .fast_state import FastState

FEATURE_DIM = 133
KINDS = ("T", "S", "H", "C", "D")
POWER_SCALE = 1200.0


def _kind_of(card: Card, level: int, trump) -> str:
    return "T" if is_trump(card, level, trump) else card.suit


_SUIT_IDX = {"S": 0, "H": 1, "C": 2, "D": 3}


_SUIT_IDX = {"S": 0, "H": 1, "C": 2, "D": 3}
_RANK_SLOTS = 15            # rank 2..16


_SUIT_IDX = {"S": 0, "H": 1, "C": 2, "D": 3}
_RANK_SLOTS = 15            # rank 2..16


def _seat_groups(team: int):
    """返回 (我方两个座位, 对方两个座位)，各自按座位号排序。"""
    ours = [s for s in range(4) if (0 if s in (0, 2) else 1) == team]
    theirs = [s for s in range(4) if (0 if s in (0, 2) else 1) != team]
    return ours, theirs


def _features_seat(state: FastState, team: int) -> List[float]:
    """**v2 布局**：133 维，按座位拆开。`team` 是"我们"这一队（0 或 1）。

    和 v1 的区别：**按座位拆开**而不是按队合并。
    "下家缺♠"和"对家缺♠"对决策是不同的，按队合并就把这个区别丢掉了。

    性能注意：这是搜索叶子的热路径，所以内联了 is_trump / card_points 的判断。
    """
    level = state.level
    trump = state.trump_suit

    n = [[0] * 5 for _ in range(4)]        # 每个座位每门张数
    pt = [[0] * 5 for _ in range(4)]       # 每个座位每门分
    top = [[0] * 5 for _ in range(4)]      # 每个座位每门最大牌力
    tr = [0] * 4                            # 每个座位主牌数
    seen = [[0] * (5 * _RANK_SLOTS) for _ in range(4)]

    for s_ in range(4):
        nb, ptb, topb, sb = n[s_], pt[s_], top[s_], seen[s_]
        for c in state.hands[s_]:
            r = c.rank
            suit = c.suit
            if (suit == "J") or r == level or r == 2 or (trump is not None and suit == trump):
                k = 0
                tr[s_] += 1
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
            sb[k * _RANK_SLOTS + r - 2] += 1
            if r == 5:
                ptb[k] += 5
            elif r == 10 or r == 13:
                ptb[k] += 10
            if pw > topb[k]:
                topb[k] = pw

    # 每座位每门的对数 + 最长连对（连续的点数都成对）
    pairs = [[0] * 5 for _ in range(4)]
    runs = [[0] * 5 for _ in range(4)]
    for s_ in range(4):
        sb = seen[s_]
        for k in range(5):
            base = k * _RANK_SLOTS
            best_run = 0
            cur_run = 0
            for i in range(_RANK_SLOTS):
                if sb[base + i] >= 2:
                    pairs[s_][k] += 1
                    cur_run += 1
                    if cur_run > best_run:
                        best_run = cur_run
                else:
                    cur_run = 0
            runs[s_][k] = best_run

    ours, theirs = _seat_groups(team)

    feats: List[float] = []
    for s_ in list(ours) + list(theirs):
        for k in range(5):
            feats.append(n[s_][k] / 10.0)
            feats.append(pt[s_][k] / 50.0)
            feats.append(top[s_][k] / POWER_SCALE)
        for k in range(5):
            feats.append(pairs[s_][k] / 3.0)
        for k in range(5):
            feats.append(runs[s_][k] / 3.0)
        feats.append(tr[s_] / 10.0)
        for k in range(5):
            feats.append(1.0 if n[s_][k] == 0 else 0.0)

    zt = 0 if state.zhuang in (0, 2) else 1
    feats.append(state.points[zt] / 100.0)
    feats.append(state.points[1 - zt] / 100.0)
    feats.append(state.trick_no / 25.0)
    feats.append(1.0 if zt == team else 0.0)
    feats.append((len(state.hands[0]) + len(state.hands[1])
                  + len(state.hands[2]) + len(state.hands[3])) / 100.0)

    if state.plays:
        pot = state.points_on_table()
        winner = state.winner_so_far()
        feats.append(pot / 50.0)
        feats.append(1.0 if (winner is not None and
                             (0 if winner in (0, 2) else 1) == team) else -1.0)
        feats.append(len(state.plays) / 4.0)
    else:
        feats.extend((0.0, 0.0, 0.0))

    # 现在轮到我方出牌吗
    cp = state.current_player
    feats.append(1.0 if (0 if cp in (0, 2) else 1) == team else 0.0)

    assert len(feats) == FEATURE_DIM_V2, len(feats)
    return feats


def _features_team(state: FastState, team: int) -> List[float]:
    """**v1 布局**：60 维，按队合并（更便宜，约 30 微秒）。"""
    level = state.level
    trump = state.trump_suit

    n = [[0, 0, 0, 0, 0], [0, 0, 0, 0, 0]]
    pt = [[0, 0, 0, 0, 0], [0, 0, 0, 0, 0]]
    top = [[0, 0, 0, 0, 0], [0, 0, 0, 0, 0]]
    tr = [0, 0]
    seen = [[0] * (5 * _RANK_SLOTS) for _ in range(2)]

    for s_ in range(4):
        bucket = 0 if (0 if s_ in (0, 2) else 1) == team else 1
        nb, ptb, topb, sb = n[bucket], pt[bucket], top[bucket], seen[bucket]
        for c in state.hands[s_]:
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
            sb[k * _RANK_SLOTS + r - 2] += 1
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
    for b in (0, 1):
        sb = seen[b]
        for k in range(5):
            base = k * _RANK_SLOTS
            pairs = 0
            for i in range(_RANK_SLOTS):
                if sb[base + i] >= 2:
                    pairs += 1
            feats.append(pairs / 3.0)

    zt = 0 if state.zhuang in (0, 2) else 1
    feats.append(state.points[zt] / 100.0)
    feats.append(state.points[1 - zt] / 100.0)
    feats.append(state.trick_no / 25.0)
    feats.append(1.0 if zt == team else 0.0)
    feats.append((len(state.hands[0]) + len(state.hands[1])
                  + len(state.hands[2]) + len(state.hands[3])) / 100.0)

    if state.plays:
        pot = state.points_on_table()
        winner = state.winner_so_far()
        feats.append(pot / 50.0)
        feats.append(1.0 if (winner is not None and
                             (0 if winner in (0, 2) else 1) == team) else -1.0)
        feats.append(len(state.plays) / 4.0)
    else:
        feats.extend((0.0, 0.0, 0.0))

    assert len(feats) == FEATURE_DIM_V1, len(feats)
    return feats


FEATURE_DIM_V1 = 60
FEATURE_DIM_V2 = 133
# 默认用哪套特征（数据生成脚本用这个）
FEATURE_DIM = FEATURE_DIM_V2


def state_features(state: FastState, team: int) -> List[float]:
    """默认布局（v2，133 维）。老的 v1 模型请用 ValueNet.predict。"""
    return _features_seat(state, team)


ACTION_DIM = 15


def action_features(state: FastState, seat: int, cards) -> List[float]:
    """15 维动作特征。和 `_features_team` 的 60 维拼起来供优势网络使用。"""
    from .rules import build_category

    level = state.level
    trump = state.trump_suit
    n = len(cards)
    kind_cnt = [0, 0, 0, 0, 0]
    pts = 0
    powers = []
    ranks = set()
    rank_cnt = {}
    all_trump = True

    for c in cards:
        if (c.suit == "J") or c.rank == level or c.rank == 2 or (trump is not None and c.suit == trump):
            k = 0
            kind = "T"
        else:
            k = 1 + _SUIT_IDX[c.suit]
            kind = c.suit
            all_trump = False
        kind_cnt[k] += 1
        if c.rank == 5:
            pts += 5
        elif c.rank == 10 or c.rank == 13:
            pts += 10
        ranks.add(c.rank)
        ranks_list = None
        powers.append(build_category(level, trump, None if kind == "T" else kind).power_of(c))
        rank_cnt[c.rank] = rank_cnt.get(c.rank, 0) + 1

    is_lead = state.lead is None
    feats: List[float] = [
        n / 8.0,
        0.0 if is_lead else 1.0,
    ]
    for k in range(5):
        feats.append(kind_cnt[k] / 4.0)
    feats.append(pts / 50.0)
    mx = max(powers) if powers else 0
    mn = min(powers) if powers else 0
    feats.append(mx / POWER_SCALE)
    feats.append(mn / POWER_SCALE)
    feats.append((sum(powers) / len(powers) / POWER_SCALE) if powers else 0.0)
    feats.append(len(ranks) / 4.0)
    feats.append(1.0 if any(v >= 2 for v in rank_cnt.values()) else 0.0)
    feats.append(1.0 if all_trump else 0.0)

    # 这手牌出下去之后，当前这墩是不是我方领先
    if not is_lead and state.plays:
        winner = state.winner_so_far()
        mine = winner is not None and (0 if winner in (0, 2) else 1) == state.team(seat)
        cur = 0
        if winner is not None:
            lead_cat = state.lead.category
            for s_, played in state.plays:
                if s_ == winner:
                    for c in played:
                        cur = max(cur, lead_cat.power_of(c))
        feats.append(1.0 if (mx > cur or mine) and mx >= cur else 0.0)
    else:
        feats.append(1.0 if is_lead else 0.0)

    assert len(feats) == ACTION_DIM, len(feats)
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
        # 特征布局由权重维度推断：60 -> v1（按队），133 -> v2（按座位）
        dim = len(self.w1[0])
        if dim == FEATURE_DIM_V1:
            return self.predict_features(_features_team(state, team))
        return self.predict_features(_features_seat(state, team))


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
