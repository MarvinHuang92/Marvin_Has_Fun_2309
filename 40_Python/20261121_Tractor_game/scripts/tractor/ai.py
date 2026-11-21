"""Very small rule-based AI.

It is deliberately simple: it can bid, bury, follow suit, ruff and choose
between a high (try to win) and a low (discard) play.  No search, no model.
"""
from __future__ import annotations

import random
from typing import Dict, List, Optional, Sequence, Tuple

from .cards import Card, card_points, is_trump, power, trump_power
from .engine import Bid, TractorGame
from .rules import (
    Category,
    Component,
    LeadPattern,
    build_category,
    can_win,
    decompose_lead,
    is_legal_follow,
    pairs_by_slot,
)


def _hand_score_for_suit(hand: Sequence[Card], suit: str, level: int) -> float:
    return sum(1.0 for c in hand if c.suit == suit) + 2.0 * sum(
        1 for c in hand if c.suit == suit and c.rank == level
    )


def choose_bid(game: TractorGame, seat: int) -> Optional[Bid]:
    bids = game.legal_bids(seat)
    if not bids:
        return None
    cur = game.declaration
    hand = game.hands[seat]

    if cur is None:
        # Open with the suit we are longest in; prefer a pair if we have it.
        def score(b: Bid) -> float:
            if b.kind == "single":
                return _hand_score_for_suit(hand, b.suit, game.level)
            if b.kind == "pair":
                return _hand_score_for_suit(hand, b.suit, game.level) + 3.0
            if b.kind == "nt_small":
                return 5.0 + sum(1 for c in hand if c.is_small) * 2
            return 6.0 + sum(1 for c in hand if c.is_big) * 2

        return max(bids, key=score)

    if cur.seat == seat:
        # Current declarer: strengthen if possible, otherwise pass.
        streng = [b for b in bids if b.strengthen]
        if streng:
            return random.choice(streng)
        nts = [b for b in bids if b.kind in ("nt_small", "nt_big")]
        if nts and random.random() < 0.5:
            return random.choice(nts)
        return None

    if game.team(cur.seat) == game.team(seat):
        # Partner declared: usually pass.
        return None

    # Opponent declared: counter with a pair/NT if we have one.
    counters = [b for b in bids if b.level > cur.level]
    if counters and random.random() < 0.65:
        return max(counters, key=lambda b: b.level)
    return None


def _keep_value(card: Card, level: int, trump_suit: Optional[str]) -> float:
    v = 0.0
    if card.is_joker:
        v += 120
    elif card.rank == level:
        v += 110
    elif card.rank == 2:
        v += 105
    elif trump_suit is not None and card.suit == trump_suit:
        v += 80
    v += card.rank * 2
    if card.rank in (5, 10, 13):
        v += 25
    return v


def choose_bury(game: TractorGame, seat: int) -> List[Card]:
    pool = list(game.hands[seat]) + list(game.bottom)
    # Bonus for keeping pairs: approximate by grouping identical cards.
    counts: Dict[Tuple[str, int], int] = {}
    for c in pool:
        counts[(c.suit, c.rank)] = counts.get((c.suit, c.rank), 0) + 1
    scored = []
    for c in pool:
        v = _keep_value(c, game.level, game.trump_suit)
        if counts[(c.suit, c.rank)] >= 2:
            v += 15
        scored.append((v, c))
    scored.sort(key=lambda x: (x[0], x[1].suit, x[1].rank))
    return [c for _, c in scored[:8]]


# ---------------------------------------------------------------------------
# Play construction
# ---------------------------------------------------------------------------

def _pick_pair(rem: Sequence[Card], cat: Category, high: bool) -> Optional[List[Card]]:
    pairs = [p for lst in pairs_by_slot(rem, cat).values() for p in lst]
    if not pairs:
        return None
    p = max(pairs, key=lambda x: x.power) if high else min(pairs, key=lambda x: x.power)
    return list(p.cards)


def _pick_tractor(rem: Sequence[Card], cat: Category, k: int, high: bool) -> Optional[List[Card]]:
    pairs = pairs_by_slot(rem, cat)
    n = len(pairs)
    runs = []
    i = 0
    while i < n:
        if pairs.get(i):
            j = i
            while j + 1 < n and pairs.get(j + 1):
                j += 1
            runs.append((i, j - i + 1))
            i = j + 1
        else:
            i += 1
    candidates = []
    for start, length in runs:
        if length >= k:
            for s in range(start, start + length - k + 1):
                chosen = [pairs[i][0] for i in range(s, s + k)]
                candidates.append((cat.slots[s].power, chosen))
    if not candidates:
        return None
    candidates.sort(key=lambda x: x[0], reverse=high)
    chosen = candidates[0][1]
    return [c for p in chosen for c in p.cards]


def _pick_single(rem: Sequence[Card], cat: Category, high: bool) -> Optional[Card]:
    if not rem:
        return None
    return max(rem, key=lambda c: cat.power_of(c)) if high else min(rem, key=lambda c: cat.power_of(c))


def _build_play(
    hand: Sequence[Card],
    lead: LeadPattern,
    level: int,
    trump_suit: Optional[str],
    high: bool,
) -> List[Card]:
    n = len(lead.cards)
    cat = lead.category
    hand_cat = [c for c in hand if cat.contains(c)]

    if len(hand_cat) < n:
        # Must play all led-suit cards; fill with the lowest non-point cards.
        selected = list(hand_cat)
        rest = [c for c in hand if c not in selected]
        rest.sort(key=lambda c: (card_points(c), c.rank))
        selected.extend(rest[: max(0, n - len(selected))])
        return selected[:n]

    rem = list(hand_cat)
    selected: List[Card] = []
    for slot in lead.slots:
        if slot.kind == "single":
            c = _pick_single(rem, cat, high)
            if c is not None:
                selected.append(c)
                rem.remove(c)
        elif slot.kind == "pair":
            cards = _pick_pair(rem, cat, high)
            if cards:
                selected.extend(cards)
                for c in cards:
                    rem.remove(c)
        else:
            cards = _pick_tractor(rem, cat, slot.length, high)
            if cards:
                selected.extend(cards)
                for c in cards:
                    rem.remove(c)
    # fill up to n from the remaining category cards
    rem.sort(key=lambda c: cat.power_of(c), reverse=high)
    while len(selected) < n and rem:
        selected.append(rem.pop(0))
    return selected[:n]


def _build_ruff_play(
    hand: Sequence[Card],
    lead: LeadPattern,
    level: int,
    trump_suit: Optional[str],
    high: bool,
) -> Optional[List[Card]]:
    trump_cat = build_category(level, trump_suit)
    trumps = [c for c in hand if is_trump(c, level, trump_suit)]
    n = len(lead.cards)
    if len(trumps) < n:
        return None
    # Use the same slot-filling approach as _build_play, but with trumps.
    rem = list(trumps)
    selected: List[Card] = []
    for slot in lead.slots:
        if slot.kind == "single":
            c = _pick_single(rem, trump_cat, high)
            if c is None:
                return None
            selected.append(c)
            rem.remove(c)
        elif slot.kind == "pair":
            cards = _pick_pair(rem, trump_cat, high)
            if cards is None:
                return None
            selected.extend(cards)
            for c in cards:
                rem.remove(c)
        else:
            cards = _pick_tractor(rem, trump_cat, slot.length, high)
            if cards is None:
                return None
            selected.extend(cards)
            for c in cards:
                rem.remove(c)
    if len(selected) != n:
        return None
    return selected


def choose_play(game: TractorGame, seat: int) -> List[Card]:
    hand = list(game.hands[seat])
    if not hand:
        return []
    if game.trick is None or game.trick.lead is None:
        # lead: prefer a low side-suit non-point single
        def lead_key(c: Card):
            return (
                0 if not is_trump(c, game.level, game.trump_suit) else 1,
                card_points(c),
                c.rank,
            )

        # occasionally lead a pair/tractor from a side suit
        if random.random() < 0.25:
            for suit in ("S", "H", "C", "D"):
                subset = [c for c in hand if c.suit == suit and not is_trump(c, game.level, game.trump_suit)]
                if len(subset) >= 2:
                    # try a pair
                    for i in range(len(subset)):
                        for j in range(i + 1, len(subset)):
                            a, b = subset[i], subset[j]
                            if a.suit == b.suit and a.rank == b.rank and a.copy != b.copy:
                                return [a, b]
        return [min(hand, key=lead_key)]

    lead = game.trick.lead
    n = len(lead.cards)
    cat = lead.category
    hand_cat = [c for c in hand if cat.contains(c)]
    void = len(hand_cat) == 0

    # Try to win first.
    high_play: Optional[List[Card]] = None
    if void and cat.kind == "S":
        high_play = _build_ruff_play(hand, lead, game.level, game.trump_suit, True)
    else:
        high_play = _build_play(hand, lead, game.level, game.trump_suit, True)
    if high_play:
        win = can_win(high_play, lead, game.level, game.trump_suit, void)
        if win is not None:
            ok, _ = is_legal_follow(hand, high_play, lead, game.level, game.trump_suit)
            if ok:
                return high_play

    # Otherwise play low.
    low_play = _build_play(hand, lead, game.level, game.trump_suit, False)
    if low_play:
        ok, _ = is_legal_follow(hand, low_play, lead, game.level, game.trump_suit)
        if ok:
            return low_play

    # Last resort: any legal-ish selection.
    if len(hand_cat) >= n:
        return hand_cat[:n]
    selected = list(hand_cat)
    rest = [c for c in hand if c not in selected]
    rest.sort(key=lambda c: (card_points(c), c.rank))
    selected.extend(rest[: max(0, n - len(selected))])
    return selected[:n]
