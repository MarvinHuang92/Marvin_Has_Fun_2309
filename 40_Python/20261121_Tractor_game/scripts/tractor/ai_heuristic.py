"""阶段 1 骨架：会记牌的规则型 AI。

和 `ai.py` 的区别（也是它现在的主要短板）：

  1. **会记牌**：知道哪些牌已经出现、谁缺哪门（`memory.CardTracker`）
  2. **会给队友送分**：队友当前领先时主动垫分牌（10 / K / 5）
  3. **会算"能不能赢"**：用 1 层评估判断这一手打完本墩谁领先，而不是只看自己手牌大小
  4. **领出会挑大的**：优先兑现"已经确定最大"的牌，避免白送分

仍然是**启发式，不含搜索**。真正的搜索（双明手 + 定约采样）在阶段 2/3 接进来，
接口就开在 `choose_play()` 里 —— 到时候把这里的 1 层评估换成 `search.py` 的调用即可。

TODO（留给阶段 2/3）：
  - [ ] 用 `search.expectimax` / 双明手求解器替换 `_score_play` 的 1 层评估
  - [ ] 亮主阶段引入对手建模（现在只是按手牌打分）
  - [ ] 埋底考虑"造缺门"的长期价值，而不只是保留价值
  - [ ] 尾局（最后 3~5 墩）单独处理：抠底倍数 ×1~64，权重完全不同
"""
from __future__ import annotations

import random
from typing import List, Optional, Sequence, Tuple

from . import moves
from .cards import Card, card_points, is_trump, power
from .engine import Bid, TractorGame
from .fast_state import FastState
from .memory import CardTracker

POINT_RANKS = (5, 10, 13)


def _points(cards: Sequence[Card]) -> int:
    return sum(card_points(c) for c in cards)


class HeuristicAI:
    """会记牌的启发式 AI。一个实例可以当作一队的策略。"""

    name = "heuristic"

    def __init__(self, rng: Optional[random.Random] = None, verbose: bool = False) -> None:
        self.rng = rng or random.Random(20261121)
        self.verbose = verbose
        self.tracker: Optional[CardTracker] = None
        self._deal_key: Optional[Tuple] = None

    # ------------------------------------------------------------------ 生命周期
    def begin_deal(self, game: TractorGame) -> None:
        """庄家/闲家定了之后调用一次：重置记忆。"""
        self.tracker = CardTracker(game.level, game.trump_suit, my_seat=0)
        self._deal_key = (game.deal_no, game.level, game.trump_suit, game.zhuang)

    def _ensure(self, game: TractorGame, seat: int) -> CardTracker:
        if self.tracker is None:
            self.tracker = CardTracker(game.level, game.trump_suit, my_seat=seat)
        self.tracker.my_seat = seat
        self.tracker.observe_hand(game.hands[seat])
        return self.tracker

    def observe(self, game: TractorGame, seat: int, cards: Sequence[Card], lead=None) -> None:
        """别人出完牌后喂给记忆（评估台会调用）。"""
        if self.tracker is None:
            return
        self.tracker.observe_play(seat, cards, lead)

    # ------------------------------------------------------------------ 亮主
    def bid(self, game: TractorGame, seat: int) -> Optional[Bid]:
        bids = game.legal_bids(seat)
        if not bids:
            return None
        hand = game.hands[seat]
        cur = game.declaration

        def strength(b: Bid) -> float:
            n = sum(1 for c in hand if c.suit == b.suit) if b.suit else 0
            honors = sum(1 for c in hand if c.suit == b.suit and c.rank >= 11) if b.suit else 0
            jokers = sum(1 for c in hand if c.is_joker)
            points = _points(hand)
            base = n * 1.0 + honors * 1.5 + jokers * 2.0 + points * 0.05
            if b.kind == "pair":
                base += 3.0
            elif b.kind in ("nt_small", "nt_big"):
                base += 2.0
            return base

        if cur is None:
            return max(bids, key=strength)
        if cur.seat == seat:
            streng = [b for b in bids if b.strengthen]
            if streng:
                return max(streng, key=strength)
            return None
        if game.team(cur.seat) == game.team(seat):
            return None                      # 队友已经亮了，不抢
        counters = [b for b in bids if b.level > cur.level]
        if not counters:
            return None
        best = max(counters, key=strength)
        # 只有分数明显更强才反主，避免无谓换底
        if strength(best) >= strength_of_bid(cur, hand) + 1.5:
            return best
        return None

    # ------------------------------------------------------------------ 埋底
    def bury(self, game: TractorGame, seat: int) -> List[Card]:
        pool = list(game.hands[seat]) + list(game.bottom)
        level, trump = game.level, game.trump_suit
        groups: dict = {}
        for c in pool:
            groups.setdefault((c.suit, c.rank), []).append(c)

        def keep(c: Card) -> float:
            v = 0.0
            if c.is_joker:
                v += 140
            elif c.rank == level:
                v += 130
            elif c.rank == 2:
                v += 120
            elif is_trump(c, level, trump):
                v += 90
            v += c.rank * 2
            v += card_points(c) * 4          # 分牌尽量别埋
            if len(groups[(c.suit, c.rank)]) >= 2:
                v += 18                       # 成对留着
            return v

        # 埋掉"保留价值最低"的 8 张；同分时优先埋长门里的孤张（顺便造缺门）
        scored = sorted(pool, key=lambda c: (keep(c), c.suit, c.rank))
        return scored[:8]

    # ------------------------------------------------------------------ 出牌
    def play(self, game: TractorGame, seat: int) -> List[Card]:
        tr = self._ensure(game, seat)
        st = FastState.from_game(game)
        moves_list = moves.legal_moves(st, seat, max_moves=120)
        if not moves_list:
            return list(game.hands[seat])[:1]

        scored = [(self._score_play(st, seat, mv, tr), mv) for mv in moves_list]
        scored.sort(key=lambda x: -x[0])
        best = scored[0][1]
        if self.verbose:
            print("  [AI] 座位%d 选 %s（分 %.1f）" % (
                seat, " ".join(c.label for c in best), scored[0][0]))
        return best

    # ------------------------------------------------------------------ 评估
    def _score_play(self, st: FastState, seat: int, cards: Sequence[Card], tr: CardTracker) -> float:
        """1 层评估：这一手打完之后，本墩归谁、能捞多少分。"""
        tmp = st.clone()
        ok, _, result = tmp.play(seat, cards)
        if not ok:
            return -1e9

        my_team = st.team(seat)
        if result is not None:
            # 这一手直接结束本墩
            win = st.team(result.winner) == my_team
            gain = result.points if win else -result.points
            return gain * 2.0 - self._cost(st, cards)

        winner = tmp.winner_so_far()
        leading = winner is not None and st.team(winner) == my_team
        stake = tmp.points_on_table()
        val = (stake * 1.5 if leading else -stake * 1.5) if stake else 0.0

        # 队友已经领先 → 尽量把分垫出去（分牌留在手里是浪费）
        if leading and winner != seat:
            val += _points(cards) * 3.0
        # 自己领先但可能被别人毙/压 → 稍微保守
        if leading and winner == seat:
            val += _points(cards) * 0.5
        # 会浪费大牌要扣分
        val -= self._cost(st, cards)
        # 确定最大的牌给额外奖励（兑现）
        if self._is_master(st, cards, tr):
            val += 25.0
        return val

    def _cost(self, st: FastState, cards: Sequence[Card]) -> float:
        """打掉这些牌的代价：牌力越高越贵，主牌更贵。"""
        total = 0.0
        for c in cards:
            p = power(c, st.level, st.trump_suit)
            total += p * (0.08 if is_trump(c, st.level, st.trump_suit) else 0.05)
        return total

    def _is_master(self, st: FastState, cards: Sequence[Card], tr: CardTracker) -> bool:
        """粗略判断：这手牌在它的花色里已经无人能压（且没人能毙）。"""
        from .rules import build_category

        kind = None
        for c in cards:
            k = tr.category_letter(
                None if is_trump(c, st.level, st.trump_suit) else c.suit
            )
            if kind is None:
                kind = k
            elif kind != k:
                return False
        if kind is None:
            return False
        cat = build_category(st.level, st.trump_suit) if kind == "T" else \
            build_category(st.level, st.trump_suit, side_suit=kind)
        if all(cat.slot_of(c) is not None and cat.power_of(c) >= tr.top_remaining_power(cat) for c in cards):
            if kind == "T":
                return True
            attackers = [s for s in range(4) if st.team(s) != st.team(tr.my_seat)]
            return not tr.can_be_ruffed(kind, attackers)
        return False


def strength_of_bid(bid: Bid, hand: Sequence[Card]) -> float:
    """给 `bid()` 里比较"当前声明"用。"""
    n = sum(1 for c in hand if c.suit == bid.suit) if bid.suit else 0
    honors = sum(1 for c in hand if c.suit == bid.suit and c.rank >= 11) if bid.suit else 0
    jokers = sum(1 for c in hand if c.is_joker)
    base = n * 1.0 + honors * 1.5 + jokers * 2.0
    if bid.kind == "pair":
        base += 3.0
    elif bid.kind in ("nt_small", "nt_big"):
        base += 2.0
    return base
