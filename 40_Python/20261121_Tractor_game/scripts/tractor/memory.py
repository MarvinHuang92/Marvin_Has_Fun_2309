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
        self.played_by_seat: Dict[int, List[Card]] = {s: [] for s in range(4)}
        # **我确知的底牌**（只有"最后埋底的人是我自己"时才非空）。
        # 有了它，未见牌里就能扣掉这 8 张 → 对手的牌完全确定。
        self.known_bottom: Set[CardId] = set()

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
            self.played_by_seat[seat].append(c)
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
        """所有还没见过、也不在我手里的牌。

        如果我是最后埋底的人，`known_bottom` 里那 8 张要**扣掉** ——
        那些牌永远不会出现在对手手上。分情况处理，是这个模块唯一"占便宜"的地方，
        但它是**确凿的信息**，不是偷看。
        """
        out = []
        for c in make_deck():
            cid = card_id(c)
            if cid in self.played or cid in self.my_hand or cid in self.known_bottom:
                continue
            out.append(cid)
        return out

    def set_known_bottom(self, cards: Sequence[Card]) -> None:
        self.known_bottom = {card_id(c) for c in cards}
        self.known_bottom.discard(())
        self.known_bottom = {cid for cid in self.known_bottom if cid}

    def bottom_known(self) -> bool:
        return bool(self.known_bottom)

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

    def can_be_ruffed(self, kind: str, attackers: Iterable[int],
                      respect_trump_void: bool = True) -> bool:
        """这门还有没有人可能毙。

        要同时满足两件事：
          1. 他缺这门（已知缺门，或还没确定）
          2. **他手里还有主牌**（已知缺主牌的就不能毙了）

        第 2 条和缺门是同一个推断 —— 领主牌时没跟主牌，就说明他没主牌了。
        所以"谁还能毙"可以精确到人，而不是只能靠全局计数估。
        """
        if kind == "T":
            return False
        if not respect_trump_void:
            return any(self.is_void(s, kind) for s in attackers)
        return any(
            self.is_void(s, kind) and not self.is_void(s, "T")
            for s in attackers
        )

    def trumps_dead_for(self, attackers: Iterable[int]) -> bool:
        """对这些对手来说，主牌是不是"已经没了"（谁也不能毙）。

        两种情况都算：
          1. 未见主牌 = 0（全在我手里或已打出）
          2. **这些对手都已经暴露过缺主牌**（领主时没跟主）
        """
        if self.trumps_remaining_upper() == 0:
            return True
        return all(self.is_void(s, "T") for s in attackers)

    def points_remaining(self) -> int:
        """还没出现的分牌总分（5 分 / 10 分 / K 10 分）。"""
        return sum(card_points(c) for c in self.unseen_cards())

    def points_unseen_in(self, kind: str) -> int:
        return sum(card_points(c) for c in self.unseen_in_category(kind))

    # ------------------------------------------------------- 主牌会不会被毙
    def trump_total(self) -> int:
        """整副牌里主牌一共有多少张（含常主 2 和级牌）。"""
        return sum(1 for c in make_deck() if is_trump(c, self.level, self.trump_suit))

    def trumps_remaining_upper(self) -> int:
        """还没出现、也不在我手里的主牌张数 = 三家手牌里的主牌 + 底牌里的主牌。"""
        return len(self.unseen_in_category("T"))

    def trumps_in_bottom_upper(self, bottom_size: int = 8) -> int:
        """底牌里最多能有几张主牌（底牌一共就 `bottom_size` 张）。"""
        return min(bottom_size, self.trumps_remaining_upper())

    def opponent_trumps_lower(self, bottom_size: int = 8) -> int:
        """三家手上**至少**还有几张主牌（下限）。

        未出现的主牌 = 三家的 + 底牌的，而底牌最多占 `bottom_size` 张，
        所以三家至少还有 `未见主牌 - bottom_size` 张（不小于 0）。
        """
        return max(0, self.trumps_remaining_upper() - bottom_size)

    def opponent_trumps_upper(self, bottom_size: int = 8) -> int:
        return self.trumps_remaining_upper()      # 底牌也可能是 0 张主牌

    def trumps_dead(self, bottom_size: int = 8) -> bool:
        """**全局**判断：是不是谁都没主牌了。

        唯一严格的全局判据是"未见主牌 = 0"。

        ⚠️ 不能用 `未见主牌 <= 8`：底牌里有几张主牌是未知的，
        "未见 8 张"完全可能是"三家 8 张、底牌 0 张"。而且底牌里的主牌整局都不会出现，
        所以**光靠数牌永远数不清** —— 真正的判据是"谁领主牌时没跟主"（`trumps_dead_for`）。
        """
        return self.trumps_remaining_upper() == 0

    def plays_of(self, seat: int) -> List[Card]:
        return list(self.played_by_seat.get(seat, ()))

    def trumps_played_by(self, seat: int) -> int:
        return sum(1 for c in self.played_by_seat.get(seat, ())
                   if is_trump(c, self.level, self.trump_suit))

    def summary(self) -> str:
        parts = []
        for s in range(4):
            if s == self.my_seat:
                continue
            if self.voids[s]:
                parts.append("%d号缺%s" % (s, "/".join(sorted(self.voids[s]))))
        return "，".join(parts) if parts else "暂无缺门信息"
