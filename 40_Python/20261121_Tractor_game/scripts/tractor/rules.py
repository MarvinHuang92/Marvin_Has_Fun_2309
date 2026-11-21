"""Rule engine helpers: categories, patterns, following, trick resolution,
throw validation and the "who blocked the throw" logic.

The implementation uses a "slot" model.  A lead is split into
tractor slots, pair slots and single slots; every other play is matched
against those slots.  This keeps the comparison rules in one place.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, FrozenSet, Iterable, List, Optional, Sequence, Set, Tuple

from .cards import (
    SUITS,
    Card,
    cards_points,
    group_by_pair,
    is_pair,
    is_trump,
    pair_key,
    power,
    rank_label,
    trump_power,
)


# ---------------------------------------------------------------------------
# Categories and rank slots
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class RankSlot:
    idx: int
    power: int
    label: str
    kind: str          # BJ / SJ / MAIN_LEVEL / OFF_LEVEL / MAIN_2 / OFF_2 / LEVEL / TWO / RANK
    rank: int
    suits: Tuple[str, ...]

    def matches(self, card: Card, cat: "Category") -> bool:
        if self.kind == "BJ":
            return card.is_big
        if self.kind == "SJ":
            return card.is_small
        if self.kind == "MAIN_LEVEL":
            return card.suit == cat.trump_suit and card.rank == cat.level
        if self.kind == "OFF_LEVEL":
            return card.suit != cat.trump_suit and card.rank == cat.level
        if self.kind == "MAIN_2":
            return card.suit == cat.trump_suit and card.rank == 2
        if self.kind == "OFF_2":
            return card.suit != cat.trump_suit and card.rank == 2
        if self.kind == "LEVEL":
            return card.rank == cat.level
        if self.kind == "TWO":
            return card.rank == 2
        if self.kind == "RANK":
            return card.suit in self.suits and card.rank == self.rank
        return False


@dataclass(frozen=True)
class Category:
    kind: str                     # "T" = trump, "S" = one side suit
    suit: Optional[str]
    slots: Tuple[RankSlot, ...]
    level: int
    trump_suit: Optional[str]

    @property
    def is_trump(self) -> bool:
        return self.kind == "T"

    @property
    def name(self) -> str:
        return "主牌" if self.is_trump else f"{self.suit} 副牌"

    def slot_of(self, card: Card) -> Optional[RankSlot]:
        if self.is_trump:
            if not is_trump(card, self.level, self.trump_suit):
                return None
        else:
            if card.suit != self.suit or is_trump(card, self.level, self.trump_suit):
                return None
        for s in self.slots:
            if s.matches(card, self):
                return s
        return None

    def contains(self, card: Card) -> bool:
        return self.slot_of(card) is not None

    def power_of(self, card: Card) -> int:
        slot = self.slot_of(card)
        return slot.power if slot else 0

    def slot_by_idx(self, idx: int) -> RankSlot:
        return self.slots[idx]


def _slot(idx: int, kind: str, rank: int, label: str, suits: Tuple[str, ...]) -> RankSlot:
    return RankSlot(idx=idx, power=1000 - idx, label=label, kind=kind, rank=rank, suits=suits)


def build_category(level: int, trump_suit: Optional[str], side_suit: Optional[str] = None) -> Category:
    """Build the rank order for a side suit or for the trump category."""
    if side_suit is not None:
        slots: List[RankSlot] = []
        for r in range(14, 1, -1):
            if r == level or r == 2:
                continue
            slots.append(_slot(len(slots), "RANK", r, rank_label(r), (side_suit,)))
        return Category("S", side_suit, tuple(slots), level, trump_suit)

    slots = []
    slots.append(_slot(len(slots), "BJ", 16, "大王", ("J",)))
    slots.append(_slot(len(slots), "SJ", 15, "小王", ("J",)))
    if trump_suit is None:
        slots.append(_slot(len(slots), "LEVEL", level, f"级牌{rank_label(level)}", SUITS))
        slots.append(_slot(len(slots), "TWO", 2, "常主2", SUITS))
        return Category("T", None, tuple(slots), level, None)

    off = tuple(s for s in SUITS if s != trump_suit)
    slots.append(_slot(len(slots), "MAIN_LEVEL", level, f"主{rank_label(level)}", (trump_suit,)))
    slots.append(_slot(len(slots), "OFF_LEVEL", level, f"副{rank_label(level)}", off))
    slots.append(_slot(len(slots), "MAIN_2", 2, "主2", (trump_suit,)))
    slots.append(_slot(len(slots), "OFF_2", 2, "副2", off))
    for r in range(14, 2, -1):
        if r == level or r == 2:
            continue
        slots.append(_slot(len(slots), "RANK", r, rank_label(r), (trump_suit,)))
    return Category("T", None, tuple(slots), level, trump_suit)


# ---------------------------------------------------------------------------
# Components
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Component:
    kind: str            # "tractor" / "pair" / "single"
    length: int          # number of pairs; single = 0
    cards: Tuple[Card, ...]
    top_idx: int
    top_power: int
    pair_powers: Tuple[int, ...]

    @property
    def size(self) -> int:
        return len(self.cards)

    @property
    def type_rank(self) -> int:
        return {"tractor": 3, "pair": 2, "single": 1}[self.kind]

    def label(self) -> str:
        if self.kind == "single":
            return self.cards[0].label
        if self.kind == "pair":
            return f"{self.cards[0].label}对"
        return f"{self.length}连对"


@dataclass
class LeadPattern:
    category: Category
    slots: List[Component]
    cards: Tuple[Card, ...]
    is_throw: bool

    def slot_count(self) -> int:
        return len(self.slots)


# ---------------------------------------------------------------------------
# Pairs and runs
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Pair:
    slot_idx: int
    power: int
    suit: str
    cards: Tuple[Card, Card]


def pairs_by_slot(cards: Iterable[Card], cat: Category) -> Dict[int, List[Pair]]:
    out: Dict[int, List[Pair]] = {i: [] for i in range(len(cat.slots))}
    for group in group_by_pair(cards).values():
        if len(group) < 2:
            continue
        c = group[0]
        slot = cat.slot_of(c)
        if slot is None:
            continue
        out[slot.idx].append(Pair(slot.idx, slot.power, c.suit, (group[0], group[1])))
    for lst in out.values():
        lst.sort(key=lambda p: (-p.power, p.suit))
    return out


def _maximal_runs(pair_lists: Dict[int, List[Pair]]) -> List[Tuple[int, int]]:
    """Return (start_idx, length) of maximal consecutive non-empty pair slots."""
    runs: List[Tuple[int, int]] = []
    n = len(pair_lists)
    i = 0
    while i < n:
        if pair_lists.get(i):
            j = i
            while j + 1 < n and pair_lists.get(j + 1):
                j += 1
            runs.append((i, j - i + 1))
            i = j + 1
        else:
            i += 1
    return runs


def _component_from_pairs(pairs: Sequence[Pair], cat: Category) -> Component:
    powers = tuple(sorted((p.power for p in pairs), reverse=True))
    top = max(pairs, key=lambda p: p.power)
    cards = tuple(c for p in pairs for c in p.cards)
    return Component(
        kind="tractor" if len(pairs) >= 2 else "pair",
        length=len(pairs),
        cards=cards,
        top_idx=top.slot_idx,
        top_power=top.power,
        pair_powers=powers,
    )


def decompose_lead(cards: Sequence[Card], level: int, trump_suit: Optional[str]) -> Optional[LeadPattern]:
    """Split a lead into maximal tractor slots, pair slots and single slots."""
    if not cards:
        return None
    if all(is_trump(c, level, trump_suit) for c in cards):
        cat = build_category(level, trump_suit)
    else:
        suits = {c.suit for c in cards}
        if len(suits) != 1:
            return None
        suit = next(iter(suits))
        if suit == trump_suit:
            return None
        cat = build_category(level, trump_suit, side_suit=suit)

    if any(cat.slot_of(c) is None for c in cards):
        return None

    pair_lists = pairs_by_slot(cards, cat)
    tractors: List[Component] = []
    while True:
        runs = [r for r in _maximal_runs(pair_lists) if r[1] >= 2]
        if not runs:
            break
        start, length = max(runs, key=lambda r: (r[1], cat.slots[r[0]].power))
        chosen: List[Pair] = []
        for i in range(start, start + length):
            chosen.append(pair_lists[i].pop(0))
        tractors.append(_component_from_pairs(chosen, cat))

    pairs: List[Component] = []
    for i in range(len(cat.slots)):
        for p in pair_lists[i]:
            pairs.append(_component_from_pairs([p], cat))

    used = set()
    for comp in tractors + pairs:
        used.update(comp.cards)
    singles: List[Component] = []
    for c in cards:
        if c in used:
            continue
        slot = cat.slot_of(c)
        if slot is None:
            return None
        singles.append(Component("single", 0, (c,), slot.idx, slot.power, (slot.power,)))

    tractors.sort(key=lambda c: (-c.length, -c.top_power))
    pairs.sort(key=lambda c: -c.top_power)
    singles.sort(key=lambda c: -c.top_power)
    slots = tractors + pairs + singles
    return LeadPattern(cat, slots, tuple(cards), len(slots) > 1)


# ---------------------------------------------------------------------------
# Matching a play against a lead's slots
# ---------------------------------------------------------------------------

def _card_ids(cards: Iterable[Card]) -> Tuple[Tuple[str, int, int], ...]:
    return tuple(sorted((c.suit, c.rank, c.copy) for c in cards))


def match_slots(
    cards: Sequence[Card],
    slots: Sequence[Component],
    cat: Category,
    *,
    require_all: bool = True,
    allow_partial: bool = False,
) -> Optional[List[Optional[Component]]]:
    """Match `cards` to the lead's slots.

    - require_all=True: every slot must be filled and every card used.
    - allow_partial=True: unfillable slots are returned as None and matching
      continues with the remaining cards.
    """
    if len(cards) != sum(s.size for s in slots):
        if not allow_partial:
            return None
        # A partial follow may have fewer cards than the slots need.
    if any(cat.slot_of(c) is None for c in cards):
        return None

    card_by_id = {(c.suit, c.rank, c.copy): c for c in cards}
    memo: Dict[Tuple[int, Tuple[Tuple[str, int, int], ...]], Optional[Tuple[Optional[Component], ...]]] = {}

    def rec(idx: int, remaining: Tuple[Tuple[str, int, int], ...]) -> Optional[Tuple[Optional[Component], ...]]:
        if idx == len(slots):
            if require_all and remaining:
                return None
            return ()
        key = (idx, remaining)
        if key in memo:
            return memo[key]
        slot = slots[idx]
        rem_cards = [card_by_id[i] for i in remaining]
        rem_set = set(remaining)

        if slot.kind == "single":
            if not rem_cards:
                if allow_partial:
                    res = (None,) + (rec(idx + 1, remaining) or ())
                    memo[key] = res
                    return res
                memo[key] = None
                return None
            # highest card is always best for comparison
            c = max(rem_cards, key=lambda x: cat.power_of(x))
            comp = Component("single", 0, (c,), cat.slot_of(c).idx, cat.power_of(c), (cat.power_of(c),))
            rest = rec(idx + 1, tuple(sorted(rem_set - {(c.suit, c.rank, c.copy)})))
            if rest is None:
                if allow_partial:
                    res = (None,) + (rec(idx + 1, remaining) or ())
                    memo[key] = res
                    return res
                memo[key] = None
                return None
            res = (comp,) + rest
            memo[key] = res
            return res

        if slot.kind == "pair":
            pairs = pairs_by_slot(rem_cards, cat)
            all_pairs = [p for lst in pairs.values() for p in lst]
            if not all_pairs:
                if allow_partial:
                    res = (None,) + (rec(idx + 1, remaining) or ())
                    memo[key] = res
                    return res
                memo[key] = None
                return None
            p = max(all_pairs, key=lambda x: x.power)
            comp = _component_from_pairs([p], cat)
            removed = {(p.cards[0].suit, p.cards[0].rank, p.cards[0].copy),
                       (p.cards[1].suit, p.cards[1].rank, p.cards[1].copy)}
            rest = rec(idx + 1, tuple(sorted(rem_set - removed)))
            if rest is None:
                if allow_partial:
                    res = (None,) + (rec(idx + 1, remaining) or ())
                    memo[key] = res
                    return res
                memo[key] = None
                return None
            res = (comp,) + rest
            memo[key] = res
            return res

        # tractor slot: try every possible k-run, highest start first
        k = slot.length
        pairs = pairs_by_slot(rem_cards, cat)
        runs = [r for r in _maximal_runs(pairs) if r[1] >= k]
        candidates: List[Tuple[int, List[Pair]]] = []
        for start, length in runs:
            for s in range(start, start + length - k + 1):
                chosen = [pairs[i][0] for i in range(s, s + k)]
                candidates.append((s, chosen))
        candidates.sort(key=lambda x: -cat.slots[x[0]].power)
        for s, chosen in candidates:
            comp = _component_from_pairs(chosen, cat)
            removed = set()
            for p in chosen:
                removed.add((p.cards[0].suit, p.cards[0].rank, p.cards[0].copy))
                removed.add((p.cards[1].suit, p.cards[1].rank, p.cards[1].copy))
            rest = rec(idx + 1, tuple(sorted(rem_set - removed)))
            if rest is not None:
                res = (comp,) + rest
                memo[key] = res
                return res
        if allow_partial:
            res = (None,) + (rec(idx + 1, remaining) or ())
            memo[key] = res
            return res
        memo[key] = None
        return None

    result = rec(0, _card_ids(cards))
    return list(result) if result is not None else None


def can_fill_all(cards: Sequence[Card], slots: Sequence[Component], cat: Category) -> bool:
    return match_slots(cards, slots, cat, require_all=True) is not None


# ---------------------------------------------------------------------------
# Following rules and trick resolution
# ---------------------------------------------------------------------------

def _contains_all(hand: Sequence[Card], play: Sequence[Card]) -> bool:
    """True if every card object in `hand` appears in `play` (identity)."""
    hand_ids = [(c.suit, c.rank, c.copy) for c in hand]
    play_ids = [(c.suit, c.rank, c.copy) for c in play]
    return all(cid in play_ids for cid in hand_ids) and len(play_ids) == len(set(play_ids))


def is_legal_follow(
    hand: Sequence[Card],
    play: Sequence[Card],
    lead: LeadPattern,
    level: int,
    trump_suit: Optional[str],
) -> Tuple[bool, str]:
    """Pragmatic must-follow validator.

    Returns (ok, reason).  It enforces:
      - play exactly the lead's card count;
      - if you have enough cards of the led category, all played cards must
        be that category, and you must match the same tractors/pairs that
        your hand can match;
      - if you have fewer, you must play all your category cards (fillers free);
      - if void, any cards are legal.
    """
    n = len(lead.cards)
    if len(play) != n:
        return False, f"必须出 {n} 张"
    cat = lead.category
    hand_cat = [c for c in hand if cat.contains(c)]
    play_cat = [c for c in play if cat.contains(c)]

    if len(hand_cat) >= n:
        if len(play_cat) != n:
            return False, f"有{cat.name}必须跟{cat.name}"
        req = match_slots(hand_cat, lead.slots, cat, require_all=False, allow_partial=True)
        act = match_slots(play_cat, lead.slots, cat, require_all=False, allow_partial=True)
        if req is None or act is None:
            return True, ""
        for i, r in enumerate(req):
            if r is not None and act[i] is None:
                return False, f"必须跟出{lead.slots[i].label()}"
        return True, ""

    if len(hand_cat) > 0:
        # must play all category cards you hold, plus fillers
        if not _contains_all(hand_cat, play):
            return False, f"必须先出完手里的{cat.name}"
        return True, ""

    # void: any n cards
    return True, ""


def can_win(
    play: Sequence[Card],
    lead: LeadPattern,
    level: int,
    trump_suit: Optional[str],
    void_in_lead: bool,
) -> Optional[Tuple[str, List[Component]]]:
    """Return ('same'/'ruff', matched components) if the play can win."""
    n = len(lead.cards)
    if len(play) != n:
        return None
    cat = lead.category
    if lead.category.kind == "S" and void_in_lead and all(is_trump(c, level, trump_suit) for c in play):
        trump_cat = build_category(level, trump_suit)
        comps = match_slots(play, lead.slots, trump_cat, require_all=True)
        if comps is not None:
            return "ruff", comps
    if all(cat.contains(c) for c in play):
        comps = match_slots(play, lead.slots, cat, require_all=True)
        if comps is not None:
            return "same", comps
    return None


def compare_components(a: Sequence[Component], b: Sequence[Component]) -> int:
    """Compare two matched component lists slot by slot.  1 = a wins, -1 = b."""
    for ca, cb in zip(a, b):
        pa = list(ca.pair_powers)
        pb = list(cb.pair_powers)
        if pa > pb:
            return 1
        if pa < pb:
            return -1
    return 0


@dataclass
class TrickResult:
    winner: int
    winner_kind: str
    cards: List[Card]
    points: int
    matched: List[Component]


def trick_winner(
    plays: Sequence[Tuple[int, Sequence[Card]]],
    lead: LeadPattern,
    level: int,
    trump_suit: Optional[str],
    void_seats: Set[int],
    order: Sequence[int],
) -> TrickResult:
    """Resolve one trick.  `plays` are in turn order; plays[0] is the leader."""
    leader = plays[0][0]
    candidates: List[Tuple[str, int, List[Component]]] = []
    for seat, cards in plays:
        if seat == leader:
            candidates.append(("same", seat, lead.slots))
            continue
        win = can_win(cards, lead, level, trump_suit, seat in void_seats)
        if win is not None:
            kind, comps = win
            candidates.append((kind, seat, comps))

    ruffs = [c for c in candidates if c[0] == "ruff"]
    pool = ruffs if ruffs else [c for c in candidates if c[0] == "same"]
    if not pool:
        winner = leader
        kind = "same"
        matched = lead.slots
    else:
        # earlier player wins ties
        best = pool[0]
        for cand in pool[1:]:
            cmp = compare_components(cand[2], best[2])
            if cmp > 0:
                best = cand
        kind, winner, matched = best

    all_cards = [c for _, cs in plays for c in cs]
    return TrickResult(winner, kind, all_cards, cards_points(all_cards), matched)


# ---------------------------------------------------------------------------
# Throw validation / blocker
# ---------------------------------------------------------------------------

def _can_beat_component(hand: Sequence[Card], comp: Component, cat: Category) -> bool:
    hand_cat = [c for c in hand if cat.contains(c)]
    if not hand_cat:
        return False
    if comp.kind == "single":
        return any(cat.power_of(c) > comp.top_power for c in hand_cat)
    pairs = pairs_by_slot(hand_cat, cat)
    if comp.kind == "pair":
        return any(p.power > comp.top_power for lst in pairs.values() for p in lst)
    # tractor of length k
    k = comp.length
    for start, length in _maximal_runs(pairs):
        if length >= k and cat.slots[start].power > comp.top_power:
            return True
    return False


def throw_blocker(
    thrower: int,
    hands: Dict[int, Sequence[Card]],
    lead: LeadPattern,
    level: int,
    trump_suit: Optional[str],
) -> Tuple[Optional[int], List[Component]]:
    """First player in turn order who can beat at least one component.

    Order is thrower's next player, then the next, then the next.
    """
    cat = lead.category
    for step in (1, 2, 3):
        seat = (thrower + step) % 4
        beatable = [comp for comp in lead.slots if _can_beat_component(hands[seat], comp, cat)]
        if beatable:
            return seat, beatable
    return None, []


def forced_component(lead: LeadPattern, beatable: Sequence[Component]) -> Component:
    """The '甩错出小' fallback: smallest single/pairstructure that was blocked."""
    singles = [c for c in lead.slots if c.kind == "single"]
    pairs = [c for c in lead.slots if c.kind == "pair"]
    tractors = [c for c in lead.slots if c.kind == "tractor"]
    beat_single = any(c.kind == "single" for c in beatable)
    beat_pair = any(c.kind == "pair" for c in beatable)
    beat_tractor_lengths = {c.length for c in beatable if c.kind == "tractor"}

    candidates: List[Component] = []
    if beat_single and singles:
        candidates.append(min(singles, key=lambda c: c.top_power))
    if beat_pair and pairs:
        candidates.append(min(pairs, key=lambda c: c.top_power))
    for k in beat_tractor_lengths:
        same_len = [c for c in tractors if c.length == k]
        if same_len:
            candidates.append(min(same_len, key=lambda c: c.top_power))
    if not candidates:
        candidates = list(lead.slots)
    return min(candidates, key=lambda c: (c.top_power, c.size))


def lead_info(cards: Sequence[Card], level: int, trump_suit: Optional[str]) -> Optional[LeadPattern]:
    return decompose_lead(cards, level, trump_suit)


def bottom_multiplier(lead: LeadPattern) -> int:
    """Multiplier for the bottom based on the last trick's lead pattern."""
    if not lead.slots:
        return 1
    # largest component by type/length
    best = max(lead.slots, key=lambda c: (c.type_rank, c.length, c.top_power))
    if best.kind == "single":
        return 1
    if best.kind == "pair":
        return 2
    return min(64, 1 << best.length)
