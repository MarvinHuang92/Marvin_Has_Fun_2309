"""记牌器：只用**公开信息**推断的手牌记忆。

设计原则：这个模块不知道任何人的真实手牌（除了调用者自己的）。
所有结论都必须能从"我看到的牌"推出来：

  - 已经打出来的牌（公开）
  - 我自己的手牌
  - 谁在哪个花色上垫牌了 → 他缺这门（因为规则要求有该花色必须跟）
  - 亮主时公开的那张牌 → 他手里至少有一张该花色

用法（每局重置一次）：:

    tr = CardTracker(level=3, trump_suit=None, my_seat=0)
    tr.observe_hand(game.hands[0])
    tr.observe_play(seat, cards, lead)      # 每次有人出牌都喂进来
    if tr.is_void(2, "S"): ...              # 2 号位缺黑桃
    if tr.is_master(card, cat): ...         # 这张是当前最大的
"""
from __future__ import annotations

from typing import Dict, Iterable, List, Optional, Sequence, Set, Tuple

from .cards import (
    Card,
    SUITS,
    card_points,
    category_of,
    is_trump,
    make_deck,
    power,
)
from .rules import Category, LeadPattern, build_category

CardId = Tuple[str, int, int]


def card_id(card: Card) -> CardId:
    return (card.suit, card.rank, card.copy)


class CardTracker:
    """一局之内的公开信息记忆。"""

    def __init__(self, level: int = 3, trump_suit: Optional[str] = None, my_seat: int = 0) -> None:
        self.level = level
        self.trump_suit = trump_suit
        self.my_seat = my_seat
        self.reset(level, trump_suit, my_seat)

    # ------------------------------------------------------------------ 重置
    def reset(self, level: int, trump_suit: Optional[str], my_seat: int) -> None:
        self.level = level
        self.trump_suit = trump_suit
        self.my_seat = my_seat
        self.played: Set[CardId] = set()
        self.my_hand: Set[CardId] = set()
        # seat -> 已知缺门的花色字母（"S"/"H"/"C"/"D"/"T"）
        self.voids: Dict[int, Set[str]] = {s: set() for s in range(4)}
        # seat -> 从亮主公开信息里得到的花色（他至少有一张）
        self.shown_suit: Dict[int, str] = {}
        self.played_cards: List[Card] = []

    # ------------------------------------------------------------------ 观察
    def observe_hand(self, cards: Sequence[Card]) -> None:
        self.my_hand = {card_id(c) for c in cards}

    def observe_bid(self, seat: int, suit: Optional[str]) -> None:
        """亮主/反主时公开了花色，说明这个座位有该花色。"""
        if suit in SUITS and seat != self.my_seat:
            self.shown_suit[seat] = suit

    def observe_play(self, seat: int, cards: Sequence[Card], lead: Optional[LeadPattern]) -> None:
        """记录一次出牌，并推断缺门。

        规则：有该花色必须跟。所以
          - 出的牌里**一张领出花色都没有** → 这个人缺这门
          - 只要出了一张领出花色 → 不能判缺（可能只是不够张数）
        """
        for c in cards:
            self.played.add(card_id(c))
            self.played_cards.append(c)
        if lead is None or seat == self.my_seat:
            return
        cat = lead.category
        if any(cat.contains(c) for c in cards):
            return
        # 全是别的花色 → 缺门
        self.voids[seat].add(cat.kind)

    # ------------------------------------------------------------------ 查询
    def category_letter(self, suit: Optional[str]) -> str:
        return "T" if suit is None else suit

    def is_void(self, seat: int, kind: str) -> bool:
        return kind in self.voids.get(seat, ())

    def unseen_ids(self) -> List[CardId]:
        """所有还没见过、也不在我手里的牌（三家 + 底牌 + 未发出的）。"""
        out = []
        for c in make_deck():
            cid = card_id(c)
            if cid in self.played or cid in self.my_hand:
                continue
            out.append(cid)
        return out

    def unseen_cards(self) -> List[Card]:
        return [Card(*cid) for cid in self.unseen_ids()]

    def unseen_in_category(self, kind: str) -> List[Card]:
        out = []
        for c in self.unseen_cards():
            if category_of(c, self.level, self.trump_suit) == kind:
                out.append(c)
        return out

    def remaining_count(self, kind: str) -> int:
        return len(self.unseen_in_category(kind))

    def top_remaining_power(self, cat: Category) -> int:
        """某花色里还没出现过的最大牌力（0 表示这门已经干净了）。"""
        best = 0
        for c in self.unseen_cards():
            if cat.slot_of(c) is not None:
                best = max(best, cat.power_of(c))
        return best

    def is_master(self, card: Card, cat: Category) -> bool:
        """这张牌在自己的花色里是不是最大的（还没出现的牌里没有更大的）。

        注意：副牌"最大"不等于"必赢" —— 缺门的人可以用主牌毙。要判断绝对安全，
        还得看对手有没有缺门（见 `can_be_ruffed`）。
        """
        if cat.slot_of(card) is None:
            return False
        p = cat.power_of(card)
        return all(
            (cat.slot_of(c) is None) or cat.power_of(c) < p
            for c in self.unseen_cards()
        )

    def can_be_ruffed(self, kind: str, attackers: Iterable[int]) -> bool:
        """这门还有没有人可能毙（即缺门且手里还有主）。粗判：只要有人已确认缺门就算。"""
        if kind == "T":
            return False
        return any(self.is_void(s, kind) for s in attackers)

    def points_remaining(self) -> int:
        """还没出现的分牌总分（5 分 / 10 分 / K 10 分）。"""
        return sum(card_points(c) for c in self.unseen_cards())

    def points_unseen_in(self, kind: str) -> int:
        return sum(card_points(c) for c in self.unseen_in_category(kind))

    def summary(self) -> str:
        parts = []
        for s in range(4):
            if s == self.my_seat:
                continue
            if self.voids[s]:
                parts.append("%d号缺%s" % (s, "/".join(sorted(self.voids[s]))))
        return "，".join(parts) if parts else "暂无缺门信息"
