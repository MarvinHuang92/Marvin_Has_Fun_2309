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

import os
import random
import time
from typing import Dict, List, Optional, Sequence, Tuple

from . import moves as moves_mod
from .cards import Card, card_points, is_trump, make_deck, power
from .fast_state import FastState
from .rules import build_category

INF = float("inf")

# 估价是否把「本墩已经在桌上的分」算进去。默认开；设 EVAL_POT=0 可关掉做 A/B。
EVAL_POT = os.environ.get("EVAL_POT", "1") != "0"


def _move_key(mv: Sequence[Card]) -> Tuple:
    return tuple(sorted((c.suit, c.rank, c.copy) for c in mv))


# ---------------------------------------------------------------------------
# 定约采样
# ---------------------------------------------------------------------------

def unseen_pool(state: FastState, seat: int,
                known_bottom: Optional[set] = None) -> List[Card]:
    """轮到 `seat` 时，所有"没见过也不在我手里"的牌。

    分两种情况（差别很大）：

    - **不知道底牌**：池子 = 三家手牌 + 底牌 8 张（83 张起）。
      对 AI 来说"另外 83 张里有 75 张在对手手上、8 张是底牌，但不知道哪 8 张"，
      所以从 83 张里随机分 75 张给三家，剩下 8 张自然成为"这个世界的底牌"。
    - **知道底牌**（我自己是最后埋底的人）：那 8 张永远不会出现在对手手上，
      直接从池子里扣掉 → 剩下的每一张都**确定**在某个对手手里。

    早期版本把底牌无条件算进了"已出牌"，等于告诉 AI 哪 8 张不在对手手上 —— 那是偷看。
    现在只在**真的知道**的时候才扣。
    """
    all_ids = {(c.suit, c.rank, c.copy) for c in make_deck()}
    mine = {(c.suit, c.rank, c.copy) for c in state.hands[seat]}
    remaining = {(c.suit, c.rank, c.copy) for s in range(4) for c in state.hands[s]}
    table = {(c.suit, c.rank, c.copy) for _, cs in state.plays for c in cs}
    bottom = {(c.suit, c.rank, c.copy) for c in state.bottom}
    played = all_ids - remaining - table - bottom      # 真正打出过的牌（公开信息）
    pool = all_ids - played - mine - table
    if known_bottom:
        pool = pool - set(known_bottom)                # 确知的底牌：永远不会在对手手上
    return [Card(*cid) for cid in pool]


def determinize(state: FastState, seat: int, rng: random.Random,
                tracker=None) -> FastState:
    """把未知牌随机分给其他三家（保留每家张数），返回一个新状态。

    注意：`state.hands` 里本来是真实手牌，这里**必须**用采样结果覆盖，
    否则搜索就变成偷看了。

    传入 `tracker` 时会**尊重缺门约束**：已知某家缺某门，就不能发给他这门牌。
    这比均匀采样更接近真实 —— 也正是"信息只有在能改变信念时才有价值"的落地。
    """
    pool = unseen_pool(state, seat,
                       known_bottom=getattr(tracker, "known_bottom", None))
    rng.shuffle(pool)
    new = state.clone()

    seats = [s for s in range(4) if s != seat]
    if tracker is not None:
        # 受限最严的先发（缺门多的先挑）
        seats.sort(key=lambda s: -len(tracker.voids.get(s, ())))

    for s in seats:
        n = len(state.hands[s])
        banned = set(tracker.voids.get(s, ())) if tracker is not None else set()
        if not banned:
            new.hands[s] = pool[:n]
            pool = pool[n:]
            continue
        allowed = [c for c in pool if _kind_of(c, state) not in banned]
        if len(allowed) >= n:
            picked = rng.sample(allowed, n)
        else:
            # 约束太紧（理论上不该发生）：先满足约束，剩余随便补
            picked = list(allowed)
            rest = [c for c in pool if c not in allowed]
            picked += rng.sample(rest, min(n - len(picked), len(rest)))
        for c in picked:
            pool.remove(c)
        new.hands[s] = picked
    return new


def _kind_of(card: Card, state: FastState) -> str:
    return "T" if is_trump(card, state.level, state.trump_suit) else card.suit


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


def _scan_by_kind(state: FastState):
    """一次扫描：门 → [(座位, 牌)]，以及每队还握有哪些门。"""
    level, trump = state.level, state.trump_suit
    by_kind: Dict[str, List[Tuple[int, Card]]] = {}
    team_has = [set(), set()]
    for s in range(4):
        t = state.team(s)
        for c in state.hands[s]:
            kind = "T" if is_trump(c, level, trump) else c.suit
            by_kind.setdefault(kind, []).append((s, c))
            team_has[t].add(kind)
    return by_kind, team_has


def _tail_terms(state: FastState, team: int, by_kind, team_has) -> float:
    """两个模型共用的尾部：主牌控制、缺门、本墩已在桌上的分。"""
    my_t = sum(1 for s in range(4) if state.team(s) == team
               for c in state.hands[s] if is_trump(c, state.level, state.trump_suit))
    their_t = sum(1 for s in range(4) if state.team(s) != team
                  for c in state.hands[s] if is_trump(c, state.level, state.trump_suit))
    score = 0.5 * (my_t - their_t)

    for kind in by_kind:
        if kind == "T":
            continue
        my_void = kind not in team_has[team]
        their_void = kind not in team_has[1 - team]
        if my_void and my_t > 0 and not their_void:
            score += 0.6
        if their_void and their_t > 0 and not my_void:
            score -= 0.6

    # 本墩正在打的牌：它们已经离开手牌，上面所有项都看不见它们
    if EVAL_POT and state.plays:
        pot = state.points_on_table()
        if pot:
            winner = state.winner_so_far()
            mine = winner is not None and state.team(winner) == team
            score += pot if mine else -pot
    return score


def _eval_control(state: FastState, team: int, by_kind, team_has) -> float:
    """模型 A（二元控制）：谁持有该门最大牌，这门的分就归谁。"""
    score = 0.0
    for kind, holders in by_kind.items():
        cat = build_category(state.level, state.trump_suit,
                             None if kind == "T" else kind)
        top_power = 0
        top_holder = holders[0][0]
        for s, c in holders:
            p = cat.power_of(c)
            if p > top_power:
                top_power, top_holder = p, s
        controller = state.team(top_holder)
        inv = 1.0 / (top_power + 1e-9)
        for s, c in holders:
            rel = cat.power_of(c) * inv
            sign = 1.0 if state.team(s) == team else -1.0
            owns = 1.0 if state.team(s) == controller else 0.0
            score += sign * (card_points(c) * (0.72 * owns + 0.28 * rel) + 0.25 * rel)
    return score + _tail_terms(state, team, by_kind, team_has)


def _eval_rank(state: FastState, team: int, by_kind, team_has) -> float:
    """模型 B（位置/压牌数）：一张分牌能不能赢，取决于**在它上面有几张对手的牌**。

    比二元控制细：一门里"我有 3 张大牌、对手有 2 张"和"我只有 1 张最大牌、
    对手有 4 张次大"在这门里的分数归属完全不同，二元模型看不出区别。
    """
    score = 0.0
    for kind, holders in by_kind.items():
        cat = build_category(state.level, state.trump_suit,
                             None if kind == "T" else kind)
        order = sorted(holders, key=lambda sc: -cat.power_of(sc[1]))
        my_above = opp_above = 0
        for idx, (s, c) in enumerate(order):
            mine = state.team(s) == team
            above = opp_above if mine else my_above
            # 上面压着 4 张对手牌基本就赢不了
            chance = max(0.08, 1.0 - 0.25 * above)
            rel = 1.0 / (idx + 1.0)
            if mine:
                score += card_points(c) * chance + 0.2 * rel
                my_above += 1
            else:
                score -= card_points(c) * chance + 0.2 * rel
                opp_above += 1
    return score + _tail_terms(state, team, by_kind, team_has)


def evaluate(state: FastState, team: int, kind: str = "control") -> float:
    """中前盘估价：**从现在到局末**，`team` 的期望净得分。

    两种模型通过 `kind` 选择：

    - `"control"`（默认）：二元控制，谁持最大牌这门就归谁（快；实测与 rank 打平）
    - `"rank"`：按门内牌力排序，看"压在这张上面的对手牌有几张"

    两者共用主牌控制 / 缺门 / 本墩分三项。
    这是**截断用的近似**，不追求精确；深度够时它会被真实搜索覆盖。
    """
    by_kind, team_has = _scan_by_kind(state)
    if not by_kind:
        return 0.0
    if kind == "control":
        return _eval_control(state, team, by_kind, team_has)
    return _eval_rank(state, team, by_kind, team_has)


# ---------------------------------------------------------------------------
# 搜索器
# ---------------------------------------------------------------------------

class _Timeout(Exception):
    pass


class Searcher:
    def __init__(self, depth: int = 10, time_limit: float = 0.05,
                 node_limit: int = 60000, validate: bool = False,
                 eval_kind: str = "control") -> None:
        self.max_depth = depth
        self.time_limit = time_limit
        self.node_limit = node_limit
        # validate=True 只用于测试：核对「跳过校验」和「逐手校验」结果一致
        self.validate = validate
        self.eval_kind = eval_kind
        self.tt: Dict[Tuple, float] = {}
        self.move_cache: Dict[Tuple, List[List[Card]]] = {}
        self.nodes = 0
        self.depth_done = 0
        self.deadline = 0.0
        # 上一次完整迭代里、根节点每个候选动作的估值（PIMC 跨世界平均要用）
        self.root_values: Dict[Tuple, float] = {}
        self.root_moves: Dict[Tuple, List[Card]] = {}

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
        values: Dict[Tuple, float] = {}
        moves: Dict[Tuple, List[Card]] = {}
        for mv in cand:
            child = state.clone()
            ok, _, res = child.play(seat, mv, validate=self.validate)
            if not ok:
                continue
            gain = self._gain(res, team)
            val = gain + self._search(child, team, depth - 1,
                                      alpha - gain, beta - gain)
            key = _move_key(mv)
            values[key] = val
            moves[key] = list(mv)
            if val > best_val:
                best_val, best_move = val, mv
            alpha = max(alpha, val)
        self.root_values = values
        self.root_moves = moves
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
            return evaluate(st, team, self.eval_kind)

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
                ok, _, res = child.play(seat, mv, validate=self.validate)
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
                ok, _, res = child.play(seat, mv, validate=self.validate)
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
