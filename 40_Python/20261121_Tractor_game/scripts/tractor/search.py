"""限深度 alpha-beta 搜索（阶段 3 的第一步）。

和 `dds.py` 的区别：

  - `dds.py` 追求**搜到底**（双明手，用来当裁判）
  - 这里追求**限深度**（中前盘用），所以估价函数是质量的关键

## 为什么需要"定约采样"

alpha-beta 要求四家手牌全知道，而真实对局里我只知道自己那手。
所以搜索前先把"没见过的牌"随机分配到三家（`determinize`），
再对这个世界做完美信息搜索 —— 这就是 PIMC（Perfect Information Monte Carlo）
单样本版。真正的 PIMC 会采样多个世界再聚合，那是下一步。

## 关键：我是用"真状态"来定约采样的

`determinize()` 只从**公开信息**出发：
  - 已经出过的牌（公开）
  - 我自己的手牌
  - 每家还剩几张（公开：每人 25 张起递减）
然后把这些未知牌随机分给三家。**不偷看**真实手牌。
"""
from __future__ import annotations

import random
import time
from typing import Dict, List, Optional, Sequence, Tuple

from . import moves as moves_mod
from .cards import Card, card_points, is_trump, make_deck, power
from .fast_state import FastState
from .rules import build_category

INF = float("inf")


# ---------------------------------------------------------------------------
# 定约采样
# ---------------------------------------------------------------------------

def unseen_pool(state: FastState, seat: int) -> List[Card]:
    """轮到 `seat` 时，所有"没见过也不在我手里"的牌（三家手牌 + 底牌）。"""
    all_ids = {(c.suit, c.rank, c.copy) for c in make_deck()}
    mine = {(c.suit, c.rank, c.copy) for c in state.hands[seat]}
    remaining = {(c.suit, c.rank, c.copy) for s in range(4) for c in state.hands[s]}
    table = {(c.suit, c.rank, c.copy) for _, cs in state.plays for c in cs}
    played = all_ids - remaining - table
    pool = all_ids - played - mine - table
    return [Card(*cid) for cid in pool]


def determinize(state: FastState, seat: int, rng: random.Random) -> FastState:
    """把未知牌随机分给其他三家（保留每家张数），返回一个新状态。

    注意：`state.hands` 里本来是真实手牌，这里**必须**用采样结果覆盖，
    否则搜索就变成偷看了。
    """
    pool = unseen_pool(state, seat)
    rng.shuffle(pool)
    new = state.clone()
    i = 0
    for s in range(4):
        if s == seat:
            continue
        n = len(state.hands[s])
        new.hands[s] = pool[i:i + n]
        i += n
    return new


# ---------------------------------------------------------------------------
# 估价函数
# ---------------------------------------------------------------------------

def _categories_present(state: FastState) -> List[Tuple[str, object]]:
    """当前还有牌的花色类别（含主牌 "T"）。"""
    out = []
    kinds = set()
    for s in range(4):
        for c in state.hands[s]:
            kinds.add("T" if is_trump(c, state.level, state.trump_suit) else c.suit)
    for kind in sorted(kinds):
        cat = build_category(state.level, state.trump_suit) if kind == "T" else \
            build_category(state.level, state.trump_suit, side_suit=kind)
        out.append((kind, cat))
    return out


def evaluate(state: FastState, team: int) -> float:
    """中前盘估价：**从现在到局末**，`team` 的期望净得分。

    三个部分：

    1. **分牌归属**：按每门的"控制方"估算。持有一门最大牌的那一队，
       大概率赢下该门的大部分墩 → 该门的 5/10/K 归它。
    2. **牌力**：非分牌也给一点权重，反映"手里还有多少能赢的牌"。
    3. **主牌控制 + 缺门**：主牌多的一方能把副牌毙掉；缺门的一方更可能被毙。

    这是一个**截断用的近似**，不追求精确；深度够时它会被真实搜索覆盖。
    """
    score = 0.0
    trump_count = {0: 0, 1: 0}
    total_trumps = 0

    for kind, cat in _categories_present(state):
        holders: List[Tuple[int, Card]] = []
        for s in range(4):
            for c in state.hands[s]:
                if cat.contains(c):
                    holders.append((s, c))
        if not holders:
            continue
        top_power = max(cat.power_of(c) for _, c in holders)
        top_holder = next(s for s, c in holders if cat.power_of(c) == top_power)
        controller = state.team(top_holder)
        # 控制方是否缺门（会被对方毙）——缺门时该门的控制权打折
        control_discount = 1.0
        if kind != "T":
            void_control = not any(
                cat.contains(c) for s in range(4)
                if state.team(s) == controller for c in state.hands[s]
            )
            if void_control:
                control_discount = 0.5

        for s, c in holders:
            sign = 1.0 if state.team(s) == team else -1.0
            rel = cat.power_of(c) / (top_power + 1e-9)      # 0..1 的相对牌力
            owns_control = 1.0 if state.team(s) == controller else 0.0
            win_chance = (0.72 * owns_control + 0.28 * rel) * control_discount
            pts = card_points(c)
            score += sign * (pts * win_chance + 0.25 * rel)
            if kind == "T":
                trump_count[state.team(s)] += 1
                total_trumps += 1

    # 主牌控制：多一张主牌大约值 0.5 分（能多毙/多控一墩）
    my_t = trump_count[team]
    their_t = trump_count[1 - team]
    score += 0.5 * (my_t - their_t)

    # 缺门：我队某门缺、且有主 → 能毙，加分；反之扣分
    for kind, cat in _categories_present(state):
        if kind == "T":
            continue
        my_void = not any(cat.contains(c) for s in range(4)
                          if state.team(s) == team for c in state.hands[s])
        their_void = not any(cat.contains(c) for s in range(4)
                             if state.team(s) != team for c in state.hands[s])
        if my_void and my_t > 0 and not their_void:
            score += 0.6
        if their_void and their_t > 0 and not my_void:
            score -= 0.6

    return score


# ---------------------------------------------------------------------------
# 搜索器
# ---------------------------------------------------------------------------

class _Timeout(Exception):
    pass


class Searcher:
    def __init__(self, depth: int = 10, time_limit: float = 0.05,
                 node_limit: int = 60000) -> None:
        self.max_depth = depth
        self.time_limit = time_limit
        self.node_limit = node_limit
        self.tt: Dict[Tuple, float] = {}
        self.move_cache: Dict[Tuple, List[List[Card]]] = {}
        self.nodes = 0
        self.depth_done = 0
        self.deadline = 0.0

    # ------------------------------------------------------------------ 入口
    def choose(self, state: FastState, seat: int) -> Tuple[Optional[List[Card]], float]:
        """返回 (最优动作, 估计值)。值 = `seat` 所在队伍从现在到局末的净得分。

        迭代加深：时间用完时，返回**上一层完整搜完**的最优动作，
        而不是临时的兜底动作 —— 这点决定了限时搜索能不能用。
        """
        team = state.team(seat)
        self.deadline = time.perf_counter() + self.time_limit
        self.nodes = 0
        best_move: Optional[List[Card]] = None
        best_val = 0.0
        for d in range(1, self.max_depth + 1):
            try:
                mv, val = self._root(state, seat, team, d)
            except _Timeout:
                break
            if mv is not None:
                best_move, best_val = mv, val
                self.depth_done = d
        if best_move is None:
            best_move = moves_mod.any_legal_move(state, seat)
        return best_move, best_val

    def _root(self, state: FastState, seat: int, team: int,
              depth: int) -> Tuple[Optional[List[Card]], float]:
        cand = self._ordered(state, seat)
        if not cand:
            return None, 0.0
        best_val, best_move = -INF, cand[0]
        alpha, beta = -INF, INF
        for mv in cand:
            child = state.clone()
            ok, _, res = child.play(seat, mv)
            if not ok:
                continue
            gain = self._gain(res, team)
            val = gain + self._search(child, team, depth - 1,
                                      alpha - gain, beta - gain)
            if val > best_val:
                best_val, best_move = val, mv
            alpha = max(alpha, val)
        return best_move, best_val

    # ------------------------------------------------------------------ 主搜索
    def _search(self, st: FastState, team: int, depth: int,
                alpha: float, beta: float) -> float:
        self.nodes += 1
        if self.nodes >= self.node_limit:
            raise _Timeout
        if (self.nodes & 7) == 0 and time.perf_counter() > self.deadline:
            raise _Timeout
        if st.is_terminal():
            return 0.0
        if depth <= 0:
            return evaluate(st, team)

        key = (st.position_key(), depth)
        hit = self.tt.get(key)
        if hit is not None:
            return hit

        seat = st.current_player
        maximize = st.team(seat) == team
        cand = self._ordered(st, seat, fast=True)
        if not cand:
            return 0.0

        cutoff = False
        if maximize:
            best = -INF
            for mv in cand:
                child = st.clone()
                ok, _, res = child.play(seat, mv)
                if not ok:
                    continue
                gain = self._gain(res, team)
                val = gain + self._search(child, team, depth - 1, alpha - gain, beta - gain)
                best = max(best, val)
                alpha = max(alpha, val)
                if alpha >= beta:
                    cutoff = True
                    break
        else:
            best = INF
            for mv in cand:
                child = st.clone()
                ok, _, res = child.play(seat, mv)
                if not ok:
                    continue
                gain = self._gain(res, team)
                val = gain + self._search(child, team, depth - 1, alpha - gain, beta - gain)
                best = min(best, val)
                beta = min(beta, val)
                if alpha >= beta:
                    cutoff = True
                    break

        if not cutoff:
            self.tt[key] = best
        return best

    # ------------------------------------------------------------------ 工具
    @staticmethod
    def _gain(res, team: int) -> float:
        if res is None:
            return 0.0
        return float(res.points) if FastState.team(res.winner) == team else -float(res.points)

    def _ordered(self, st: FastState, seat: int, fast: bool = False) -> List[List[Card]]:
        key = (st.position_key(), fast)
        cand = self.move_cache.get(key)
        if cand is None:
            if fast:
                cand = moves_mod.legal_moves_fast(st, seat, limit=8)
            else:
                cand = moves_mod.legal_moves(st, seat, max_moves=80)
            cand.sort(key=lambda mv: sum(c.rank for c in mv))
            if len(self.move_cache) < 100000:
                self.move_cache[key] = cand
        return cand
