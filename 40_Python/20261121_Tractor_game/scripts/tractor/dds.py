"""双明手求解器（Double Dummy Solver）。

给定**四家手牌全公开**的局面，求这个局面在最优打法下的分数。

为什么需要它：

1. **当裁判**：算出"完美信息下这局能得多少分"，就知道启发式 AI 差多远。
   这是 6 Nimmt 项目一直缺的那把"真天花板"尺子。
2. **接进搜索**：阶段 3 的 PIMC 就是"采样 N 个可能的世界 → 每个世界用 DD 求解 → 聚合"。

## 博弈结构

2v2 结对、每墩四家依次出牌、墩分归赢家一队。总墩分固定，所以是**零和**：
我队拿 1 分 = 对方少 1 分。因此搜索里用"我队净得分"当价值即可。

队友和自己目标一致，且 DD 下信息全公开 → 按**队伍**交替 max/min（不是按座位）。
这正是桥牌 DD 求解器的标准做法。

## 实现

- alpha-beta + 置换表 + 迭代加深 + 时间预算（随时可返回当前最好解）
- 深度单位是**出牌次数**（一手牌 = 1 层）
- 深度耗尽时用 `evaluate()` 估价

## 复杂度说实话

桥牌 52 张 13 墩能到毫秒级；拖拉机 108 张 25 墩**加上组合牌型**，
全解会慢几个数量级。所以实用姿势是：

  - 尾局（最后 3~5 墩）用它求**精确**值
  - 中前盘用它做**限深度**搜索 + 估价
"""
from __future__ import annotations

import math
import time
from dataclasses import dataclass
from typing import Dict, List, Optional, Sequence, Tuple

from . import moves as moves_mod
from .cards import Card, card_points, is_trump, power
from .fast_state import FastState

INF = float("inf")


class _Timeout(Exception):
    pass


@dataclass
class DDResult:
    value: float          # 我队从"现在到局末"的净得分（正 = 我队赚）
    move: Optional[List[Card]]
    depth: int            # 完成的迭代深度（层 = 一手牌）
    nodes: int
    exact: bool           # True = 搜到底了（真双明手）


class DoubleDummySolver:
    def __init__(self, time_limit: float = 3.0, node_limit: int = 400000, use_tt: bool = True) -> None:
        self.time_limit = time_limit
        self.node_limit = node_limit
        self.use_tt = use_tt
        self.tt: Dict[Tuple, Tuple[int, float]] = {}
        self.move_cache: Dict[Tuple, List[List[Card]]] = {}
        self.nodes = 0
        self.deadline = 0.0
        self.nodes_at_tt_cut = 0

    # ------------------------------------------------------------------ 入口
    def solve(self, state: FastState, seat: int, max_depth: int = 120,
              team: Optional[int] = None) -> DDResult:
        """求 `seat` 所在队伍（或显式指定的 `team`）的最优值和最优动作。

        `team` 显式传入时，即使当前轮到对方出牌，也能按我方视角估值 ——
        "单步后悔值"需要这个：我出完这手之后轮到谁，不改变价值口径。
        """
        if team is None:
            team = state.team(seat)
        self.nodes = 0
        self.deadline = time.perf_counter() + self.time_limit
        best: Optional[DDResult] = None
        exact = False

        for depth in range(1, max_depth + 1):
            try:
                value, move = self._root(state, seat, team, depth)
            except _Timeout:
                break
            best = DDResult(value, move, depth, self.nodes, False)
            if depth >= self._remaining_plays(state):
                exact = True
                break

        if best is None:
            # 一步都没搜完（时间太紧）：退回估价 + 第一个合法动作
            mv = moves_mod.any_legal_move(state, seat)
            return DDResult(self.evaluate(state, team), mv, 0, self.nodes, False)
        best.exact = exact
        best.nodes = self.nodes
        return best

    # ------------------------------------------------------------------ 根节点
    def _root(self, state: FastState, seat: int, team: int, depth: int) -> Tuple[float, List[Card]]:
        cand = self._ordered_moves(state, seat)
        if not cand:
            return 0.0, []
        alpha, beta = -INF, INF
        best_val, best_move = -INF, cand[0]
        for mv in cand:
            child = state.clone()
            ok, _, res = child.play(seat, mv)
            if not ok:
                continue
            gain = self._gain(res, team)
            val = gain + self._search(child, team, depth - 1, alpha - gain, beta - gain)
            if val > best_val:
                best_val, best_move = val, mv
            alpha = max(alpha, val)
        return best_val, best_move

    # ------------------------------------------------------------------ 主搜索
    def _search(self, st: FastState, team: int, depth: int, alpha: float, beta: float) -> float:
        self.nodes += 1
        if self.nodes >= self.node_limit:
            raise _Timeout
        if (self.nodes & 1023) == 0 and time.perf_counter() > self.deadline:
            raise _Timeout

        if st.is_terminal():
            return 0.0
        if depth <= 0:
            return self.evaluate(st, team)

        key = (st.position_key(), depth)
        if self.use_tt:
            hit = self.tt.get(key)
            if hit is not None:
                self.nodes_at_tt_cut += 1
                return hit[1]

        seat = st.current_player
        maximize = st.team(seat) == team
        cand = self._ordered_moves(st, seat)
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

        # 只有「完整搜完、没被剪枝」的节点才是精确值；剪枝节点的 best 只是界，
        # 存进置换表会让后续读取拿到错误的值（表现为"AI 比双明手还优"）。
        if self.use_tt and not cutoff:
            self.tt[key] = (depth, best)
        return best

    # ------------------------------------------------------------------ 工具
    @staticmethod
    def _gain(res, team: int) -> float:
        if res is None:
            return 0.0
        return float(res.points) if FastState.team(res.winner) == team else -float(res.points)

    @staticmethod
    def _remaining_plays(state: FastState) -> int:
        return sum(len(state.hands[s]) for s in range(4))

    def _ordered_moves(self, st: FastState, seat: int) -> List[List[Card]]:
        """动作排序：便宜的牌先试（alpha-beta 的剪枝效率高度依赖顺序）。

        动作缓存：同一局面在搜索里会被多次访问，而 `legal_moves` 本身很贵
        （要枚举 + 逐个用引擎判罚校验），所以按 position_key 缓存。
        """
        key = st.position_key()
        cand = self.move_cache.get(key)
        if cand is None:
            cand = moves_mod.legal_moves(st, seat, max_moves=200)
            cand.sort(key=lambda mv: sum(c.rank for c in mv))
            if len(self.move_cache) < 200000:
                self.move_cache[key] = cand
        return cand

    # ------------------------------------------------------------------ 单价牌力
    def _card_strength(self, c: Card, st: FastState) -> float:
        if is_trump(c, st.level, st.trump_suit):
            return 12.0 + power(c, st.level, st.trump_suit) * 0.01
        return float(c.rank)

    # ------------------------------------------------------------------ 估价
    def evaluate(self, st: FastState, team: int) -> float:
        """深度耗尽时的估价：按"剩余分 × 我方牌力占比"估净得分。

        只是截断用的近似；搜到底时（exact=True）不会用到它。
        """
        remaining = 0
        mine = 0.0
        theirs = 0.0
        for s in range(4):
            w = 1.0 if st.team(s) == team else -1.0
            for c in st.hands[s]:
                remaining += card_points(c)
                v = self._card_strength(c, st)
                if w > 0:
                    mine += v
                else:
                    theirs += v
        total = mine + theirs
        if total <= 0:
            return 0.0
        share = mine / total * 2.0 - 1.0      # -1..1
        return remaining * share
