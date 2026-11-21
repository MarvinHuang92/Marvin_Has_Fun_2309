"""Card model and card-strength helpers for the Tractor game.

Two decks: 104 normal cards + 2 small jokers + 2 big jokers = 108.
A card is identified by (suit, rank, copy).  `copy` is 0 or 1 and is only
needed to distinguish the two physical copies of the same card.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

SUITS: Tuple[str, ...] = ("S", "H", "C", "D")
SUIT_NAMES = {"S": "黑桃", "H": "红桃", "C": "梅花", "D": "方块", "J": "王"}
SUIT_SYMBOLS = {"S": "♠", "H": "♥", "C": "♣", "D": "♦", "J": ""}
RANK_LABELS = {
    2: "2", 3: "3", 4: "4", 5: "5", 6: "6", 7: "7", 8: "8",
    9: "9", 10: "10", 11: "J", 12: "Q", 13: "K", 14: "A",
    15: "小王", 16: "大王",
}
LEVEL_SEQUENCE: Tuple[int, ...] = (3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14)


@dataclass(frozen=True, order=True)
class Card:
    """A physical card.  Normal: suit in S/H/C/D, rank 2..14.
    Jokers: suit == "J", rank 15 (small) or 16 (big).
    """

    suit: str
    rank: int
    copy: int = 0

    @property
    def is_joker(self) -> bool:
        return self.suit == "J"

    @property
    def is_big(self) -> bool:
        return self.suit == "J" and self.rank == 16

    @property
    def is_small(self) -> bool:
        return self.suit == "J" and self.rank == 15

    @property
    def label(self) -> str:
        if self.is_joker:
            return "大王" if self.is_big else "小王"
        return SUIT_SYMBOLS[self.suit] + RANK_LABELS[self.rank]

    @property
    def short(self) -> str:
        if self.is_joker:
            return "BJ" if self.is_big else "SJ"
        return self.suit + RANK_LABELS[self.rank]

    @property
    def color(self) -> str:
        return "red" if self.suit in ("H", "D") else "black"


def make_deck() -> List[Card]:
    cards: List[Card] = []
    for suit in SUITS:
        for rank in range(2, 15):
            for copy in range(2):
                cards.append(Card(suit, rank, copy))
    for rank in (15, 16):
        for copy in range(2):
            cards.append(Card("J", rank, copy))
    return cards


def rank_label(rank: int) -> str:
    return RANK_LABELS.get(rank, str(rank))


def pair_key(card: Card) -> Tuple[str, int]:
    return (card.suit, card.rank)


def is_pair(a: Card, b: Card) -> bool:
    return a.suit == b.suit and a.rank == b.rank and a.copy != b.copy


def card_points(card: Card) -> int:
    """5 -> 5; 10 and K -> 10; everything else 0."""
    if card.rank == 5:
        return 5
    if card.rank in (10, 13):
        return 10
    return 0


def cards_points(cards: Iterable[Card]) -> int:
    return sum(card_points(c) for c in cards)


def is_trump(card: Card, level: int, trump_suit: Optional[str]) -> bool:
    """`trump_suit` is None for no-trump."""
    if card.is_joker:
        return True
    if trump_suit is None:
        return card.rank == level or card.rank == 2
    return card.suit == trump_suit or card.rank == level or card.rank == 2


def category_of(card: Card, level: int, trump_suit: Optional[str]) -> str:
    """'T' for trump, otherwise the side-suit letter S/H/C/D."""
    return "T" if is_trump(card, level, trump_suit) else card.suit


def trump_power(card: Card, level: int, trump_suit: Optional[str]) -> int:
    """Higher is stronger.  Only meaningful for trump cards."""
    if card.is_big:
        return 1000
    if card.is_small:
        return 999
    if trump_suit is None:
        if card.rank == level:
            return 998
        if card.rank == 2:
            return 997
        return 0
    if card.suit == trump_suit and card.rank == level:
        return 998  # main level card
    if card.rank == level:
        return 997  # off-suit level card
    if card.suit == trump_suit and card.rank == 2:
        return 996  # main 2
    if card.rank == 2:
        return 995  # off-suit 2
    if card.suit == trump_suit:
        return 900 + card.rank
    return 0


def power(card: Card, level: int, trump_suit: Optional[str]) -> int:
    """Comparison value inside the card's own category.

    For trump cards this is the custom trump order.  For side-suit cards it is
    just the rank (the level card and 2s are not in a side suit).
    """
    if is_trump(card, level, trump_suit):
        return trump_power(card, level, trump_suit)
    return card.rank


def sort_hand(hand: Sequence[Card], level: int, trump_suit: Optional[str]) -> List[Card]:
    """Display/hand order: trumps first (strongest first), then side suits,
    each side suit strongest first."""
    suit_order = {s: i for i, s in enumerate(SUITS)}

    def key(c: Card):
        trump = is_trump(c, level, trump_suit)
        if trump:
            return (0, 0, -trump_power(c, level, trump_suit), c.suit, c.rank, c.copy)
        return (1, suit_order.get(c.suit, 9), -c.rank, c.suit, c.rank, c.copy)

    return sorted(hand, key=key)


def group_by_pair(cards: Iterable[Card]) -> Dict[Tuple[str, int], List[Card]]:
    groups: Dict[Tuple[str, int], List[Card]] = {}
    for c in cards:
        groups.setdefault(pair_key(c), []).append(c)
    return groups


def pairs_in(cards: Iterable[Card]) -> List[Tuple[Card, Card]]:
    """Return every complete pair (same suit+rank, two copies)."""
    result: List[Tuple[Card, Card]] = []
    for group in group_by_pair(cards).values():
        if len(group) >= 2:
            result.append((group[0], group[1]))
    return result


def cards_text(cards: Sequence[Card]) -> str:
    return " ".join(c.label for c in cards) if cards else "（无）"
