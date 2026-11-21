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

    def __init__(self, rng: Optional[random.Random] = None, verbose: bool = False,
                 opts: Optional[dict] = None) -> None:
        self.rng = rng or random.Random(20261121)
        self.verbose = verbose
        # 中前盘的开关（默认全关 = 旧行为，便于 A/B 对照）
        self.opts = {
            "bury_void": False,      # 埋底时整门埋掉、造缺门
            "lead_master": False,    # 领出时优先兑现确定最大牌、避开被毙
            "keep_pairs": False,     # 拆对子扣分（对子在拖拉机里很贵）
            "trump_void": True,      # 用「领主牌没跟」推断某人缺主牌
            "use_bottom": True,      # 我是最后埋底的人时，用确知的底牌收紧推断
            "bid_mode": "basic",     # basic / trump / conservative（见 _trump_strength）
            "bid_min": 26.0,         # conservative 模式的开门门槛
        }
        if opts:
            self.opts.update(opts)
        self.tracker: Optional[CardTracker] = None
        self._my_buried: dict = {}       # seat -> 我埋下去的那 8 张
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
        mode = self.opts.get("bid_mode", "basic")
        level = game.level

        def strength(b: Bid) -> float:
            if mode == "basic":
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
            # trump 模式：庄家真正需要的是**主牌的长度和顶上那几张**，
            # 而不是手牌总分。手牌分（5/10/K）留在手里对庄家是中性的。
            base = _trump_strength(hand, b.suit, level)
            if b.kind == "pair":
                base += 4.0
            elif b.kind in ("nt_small", "nt_big"):
                base += 2.0
            return base

        if cur is None:
            best = max(bids, key=strength)
            if mode == "conservative" and strength(best) < self.opts.get("bid_min", 26.0):
                return None                  # 手牌不够硬就先过，别硬抢庄
            return best
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
        margin = 1.5 if mode == "basic" else 3.0
        if strength(best) >= strength_of_bid(cur, hand) + margin:
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

        chosen: List[Card] = []
        if self.opts.get("bury_void"):
            # 造缺门：找一门最短的副牌，如果整门都能埋掉（<=8 张、无分牌、无主），
            # 就整门埋掉 —— 之后这门就能用主牌毙，是拖拉机最值钱的打法之一
            shortest = None
            for suit in ("S", "H", "C", "D"):
                if suit == trump:
                    continue
                cards = [c for c in pool
                         if c.suit == suit and not is_trump(c, level, trump)]
                if not cards or _points(cards) > 0:
                    continue
                if any(len(groups[(c.suit, c.rank)]) >= 2 and c.rank >= 11 for c in cards):
                    continue
                if shortest is None or len(cards) < len(shortest):
                    shortest = cards
            if shortest is not None and len(shortest) <= 8:
                chosen = list(shortest)

        rest = [c for c in pool if c not in chosen]
        rest.sort(key=lambda c: (keep(c), c.suit, c.rank))
        chosen.extend(rest[: max(0, 8 - len(chosen))])
        chosen = chosen[:8]
        return chosen

    def note_buried(self, seat: int, cards) -> None:
        """**真的把牌埋下去了**才调用（提示算法算出的不算）。

        只有最后埋底的人才知道最终底牌；如果把"提示建议的埋法"也记成自己埋的，
        AI 就会错误地以为自己知道底牌。
        """
        self._my_buried[seat] = list(cards)

    def sync_bottom(self, st: FastState, seat: int) -> None:
        """把"我是否知道底牌"同步给记牌器。

        只有当**最后埋底的人是我**时，底牌才是确凿信息；否则一律当作不知道
        （我可能看过更早的底牌，但已经被别人换掉了，不能用）。
        """
        if self.tracker is None:
            return
        if not self.opts.get("use_bottom", True):
            self.tracker.known_bottom = set()
            return
        mine = self._my_buried.get(seat)
        if mine and st.last_burier == seat:
            self.tracker.set_known_bottom(mine)
        else:
            self.tracker.known_bottom = set()

    # ------------------------------------------------------------------ 出牌
    def play(self, game: TractorGame, seat: int) -> List[Card]:
        self._ensure(game, seat)
        return self.choose(FastState.from_game(game), seat)

    def choose(self, st: FastState, seat: int) -> List[Card]:
        """在给定的轻量状态上决策（评测台 / 搜索 / 双明手对账都能直接用）。"""
        tr = self.tracker or CardTracker(st.level, st.trump_suit, seat)
        tr.my_seat = seat
        self.sync_bottom(st, seat)          # 缺门信息是公开的，视角切到当前决策者
        moves_list = moves.legal_moves(st, seat, max_moves=120)
        if not moves_list:
            return list(st.hands[seat])[:1]

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
            return gain * 2.0 - self._cost(st, seat, cards)

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
        val -= self._cost(st, seat, cards)
        # 确定最大的牌给额外奖励（兑现）
        if self._is_master(st, cards, tr):
            val += 25.0
        if self.opts.get("lead_master") and st.lead is None:
            val += self._lead_adjust(st, seat, cards, tr)
        return val

    def _lead_adjust(self, st: FastState, seat: int, cards: Sequence[Card],
                     tr: CardTracker) -> float:
        """领出专用修正（1 层评估对领出几乎无效，必须单独给信号）。

        - 领出确定最大的牌（能兑现分数）→ 加分
        - 领出会被对手毙掉的副牌 → 扣分
        - 领出分牌而自己又不是最大 → 扣分（白送）
        """
        from .cards import is_trump

        kind = "T"
        for c in cards:
            if not is_trump(c, st.level, st.trump_suit):
                kind = c.suit
                break
        attackers = [s for s in range(4) if st.team(s) != st.team(seat)]
        adj = 0.0
        if self._is_master(st, cards, tr):
            adj += 30.0 + _points(cards) * 4.0        # 兑现：越大越赚
        else:
            if kind != "T" and tr.can_be_ruffed(kind, attackers):
                adj -= 20.0                            # 会被毙
            if _points(cards) > 0:
                adj -= 6.0 * _points(cards)            # 分牌送人
        return adj

    def _cost(self, st: FastState, seat: int, cards: Sequence[Card]) -> float:
        """打掉这些牌的代价：牌力越高越贵，主牌更贵；开了 keep_pairs 时拆对子也贵。"""
        total = 0.0
        for c in cards:
            p = power(c, st.level, st.trump_suit)
            total += p * (0.08 if is_trump(c, st.level, st.trump_suit) else 0.05)
        if self.opts.get("keep_pairs"):
            hand = st.hands[seat]
            have: dict = {}
            for c in hand:
                have[(c.suit, c.rank)] = have.get((c.suit, c.rank), 0) + 1
            used: dict = {}
            for c in cards:
                used[(c.suit, c.rank)] = used.get((c.suit, c.rank), 0) + 1
            for key, n in used.items():
                # 手里有对子/拖拉机组件，却只打出一部分 → 拆了
                if have.get(key, 0) >= 2 and n < have[key]:
                    total += 9.0 * n
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
            tv = self.opts.get("trump_void", True)
            # 对手已经暴露过缺主牌 → 谁也不能毙
            if tv and tr.trumps_dead_for(attackers):
                return True
            return not tr.can_be_ruffed(kind, attackers, respect_trump_void=tv)
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


def _trump_strength(hand: Sequence[Card], suit, level: int) -> float:
    """这手牌打 `suit` 为主时，主牌有多硬。

    庄家靠的是**主牌长度 + 顶上那几张**（王/级牌/2/主 A、K），
    不是手牌里的 5/10/K 分数 —— 那些留在手里对庄家是中性的。
    """
    if suit is None:
        # 无主：只有 王 / 级牌 / 常主 2 是主
        return sum(3.0 for c in hand if c.is_joker or c.rank in (level, 2))
    n = sum(1 for c in hand if c.suit == suit)
    top = sum(1 for c in hand
              if (c.suit == suit and c.rank >= 11) or c.is_joker or c.rank in (level, 2))
    return 2.5 * n + 3.0 * top
