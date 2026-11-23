"""Game state machine for Tractor (2 decks, 4 players, permanent 2s)."""
from __future__ import annotations

import random
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence, Set, Tuple

from .cards import (
    LEVEL_SEQUENCE,
    SUIT_NAMES,
    Card,
    cards_points,
    is_trump,
    make_deck,
    rank_label,
    sort_hand,
)
from .rules import (
    Component,
    LeadPattern,
    bottom_multiplier,
    decompose_lead,
    forced_component,
    is_legal_follow,
    throw_blocker,
    trick_winner,
)


@dataclass
class Bid:
    seat: int
    kind: str                 # single / pair / nt_small / nt_big
    suit: Optional[str]
    cards: Tuple[Card, ...]
    level: int
    strengthen: bool = False
    seq: int = 0

    def label(self) -> str:
        if self.kind == "single":
            return f"亮{SUIT_NAMES[self.suit]}{rank_label(self.cards[0].rank)}单张"
        if self.kind == "pair":
            prefix = "加固" if self.strengthen else "亮/反"
            return f"{prefix}{SUIT_NAMES[self.suit]}{rank_label(self.cards[0].rank)}对"
        if self.kind == "nt_small":
            return "小王对（无主）"
        return "大王对（无主）"


@dataclass
class Trick:
    leader: int
    lead: Optional[LeadPattern] = None
    plays: List[Tuple[int, List[Card]]] = field(default_factory=list)
    void_seats: Set[int] = field(default_factory=set)


class TractorGame:
    """One table.  Seat 0 is the human by convention; the UI can change it."""

    def __init__(self, seed: Optional[int] = None) -> None:
        self.rng = random.Random(seed)
        self.levels: Dict[int, int] = {0: 3, 1: 3}
        self.first_deal = True
        self.next_zhuang: Optional[int] = None
        self.zhuang: Optional[int] = None
        self.level = 3
        self.trump_suit: Optional[str] = None
        self.deal_no = 0
        self.phase = "idle"
        self.hands: Dict[int, List[Card]] = {i: [] for i in range(4)}
        self.hands_start: Dict[int, List[Card]] = {i: [] for i in range(4)}
        self.bottom: List[Card] = []
        self.declaration: Optional[Bid] = None
        self.bids: List[Bid] = []
        self.current_bidder = 0
        self.passed_since_bid: Set[int] = set()
        self.pending_bury_by: Optional[int] = None
        self.extra_allowed = False
        self.last_burier: Optional[int] = None
        self.seen_bottoms: Dict[int, List[frozenset]] = {i: [] for i in range(4)}
        self.bottom_history: List[dict] = []
        self.defender_points = 0
        self.declarer_points = 0
        self.trick: Optional[Trick] = None
        self.trick_no = 0
        self.trick_history: List[dict] = []
        self.last_trick_lead: Optional[LeadPattern] = None
        self.last_trick_winner: Optional[int] = None
        self.throw_blockers: List[dict] = []
        self.last_throw_info: Optional[dict] = None
        self.deal_result: Optional[dict] = None
        self.deal_record: Optional[dict] = None
        self.match_over = False
        self.winner_team: Optional[int] = None
        self.log: List[str] = []
        self.order = [0, 1, 2, 3]
        self.current_player = 0

    # ------------------------------------------------------------------ basics
    def team(self, seat: int) -> int:
        return 0 if seat in (0, 2) else 1

    def partner(self, seat: int) -> int:
        return (seat + 2) % 4

    def next_seat(self, seat: int) -> int:
        return (seat + 1) % 4

    def team_name(self, team: int) -> str:
        # 用方位代替甲乙丙丁：座位 0/2 是南北，1/3 是东西
        return "南北" if team == 0 else "东西"

    def seat_name(self, seat: int) -> str:
        names = ["你", "下家", "对家", "上家"]
        return names[seat]

    def add_log(self, text: str) -> None:
        self.log.append(text)
        if len(self.log) > 200:
            del self.log[:100]

    def acting_seat(self) -> Optional[int]:
        if self.phase in ("bid_initial", "bid_extra"):
            return self.current_bidder
        if self.phase in ("bury_initial", "bury_extra"):
            return self.pending_bury_by
        if self.phase == "play":
            return self.current_player
        return None

    # ------------------------------------------------------------- match/deal
    def start_match(self) -> None:
        self.levels = {0: 3, 1: 3}
        self.first_deal = True
        self.next_zhuang = None
        self.match_over = False
        self.winner_team = None
        self.deal_no = 0
        self.log = []
        self.add_log("新的一场开始，双方从 3 打起。")
        self.start_deal()

    def start_deal(self) -> None:
        self.deal_no += 1
        self.trump_suit = None
        if self.first_deal:
            self.zhuang = None
            self.level = 3
            self.current_bidder = self.rng.randrange(4)
        else:
            assert self.next_zhuang is not None
            self.zhuang = self.next_zhuang
            self.level = self.levels[self.team(self.zhuang)]
            self.current_bidder = self.zhuang

        deck = make_deck()
        self.rng.shuffle(deck)
        self.hands = {i: sort_hand(deck[i * 25:(i + 1) * 25], self.level, self.trump_suit) for i in range(4)}
        self.bottom = deck[100:108]
        self.hands_start = {i: list(h) for i, h in self.hands.items()}

        self.phase = "bid_initial"
        self.declaration = None
        self.bids = []
        self.passed_since_bid = set()
        self.pending_bury_by = None
        self.extra_allowed = False
        self.last_burier = None
        self.seen_bottoms = {i: [] for i in range(4)}
        self.bottom_history = []
        self.defender_points = 0
        self.declarer_points = 0
        self.trick = None
        self.trick_no = 0
        self.trick_history = []
        self.last_trick_lead = None
        self.last_trick_winner = None
        self.throw_blockers = []
        self.last_throw_info = None
        self.deal_result = None
        self.deal_record = None
        self.add_log(f"第 {self.deal_no} 局发牌，每人 25 张，底牌 8 张。")
        if self.zhuang is not None:
            self.add_log(f"本局庄家：{self.seat_name(self.zhuang)}；级牌 {rank_label(self.level)}。")

    # ---------------------------------------------------------------- bidding
    def _bid_candidates(self, seat: int) -> List[Bid]:
        hand = self.hands[seat]
        out: List[Bid] = []
        for suit in ("S", "H", "C", "D"):
            cards = [c for c in hand if c.suit == suit and c.rank == self.level]
            if len(cards) >= 1:
                out.append(Bid(seat, "single", suit, (cards[0],), 1))
            if len(cards) >= 2:
                out.append(Bid(seat, "pair", suit, (cards[0], cards[1]), 2))
        small = [c for c in hand if c.is_small]
        big = [c for c in hand if c.is_big]
        if len(small) >= 2:
            out.append(Bid(seat, "nt_small", None, (small[0], small[1]), 3))
        if len(big) >= 2:
            out.append(Bid(seat, "nt_big", None, (big[0], big[1]), 4))
        # strengthen the current single declaration
        cur = self.declaration
        if cur is not None and cur.seat == seat and cur.kind == "single":
            same = [c for c in hand if c.suit == cur.suit and c.rank == self.level]
            if len(same) >= 2:
                out.append(Bid(seat, "pair", cur.suit, (same[0], same[1]), 2, strengthen=True))
        return out

    def _bid_allowed(self, seat: int, bid: Bid) -> bool:
        cur = self.declaration
        if cur is None:
            return True
        if seat == cur.seat:
            if bid.strengthen:
                return True
            if bid.kind in ("nt_small", "nt_big") and bid.level > cur.level:
                return True
            return False
        if bid.strengthen:
            return False
        if bid.kind == "pair" and cur.kind == "single" and bid.suit == cur.suit:
            return False
        return bid.level > cur.level

    def legal_bids(self, seat: int) -> List[Bid]:
        result = [b for b in self._bid_candidates(seat) if self._bid_allowed(seat, b)]
        # dedupe
        seen = set()
        unique: List[Bid] = []
        for b in result:
            key = (b.kind, b.suit, b.strengthen)
            if key in seen:
                continue
            seen.add(key)
            unique.append(b)
        unique.sort(key=lambda b: (b.level, 0 if b.kind != "pair" else 1))
        return unique

    def submit_bid(self, seat: int, bid: Optional[Bid]) -> Tuple[bool, str]:
        if self.phase not in ("bid_initial", "bid_extra"):
            return False, "当前不是亮主阶段"
        if seat != self.current_bidder:
            return False, "还没轮到你"
        if bid is None:
            self.passed_since_bid.add(seat)
            self.add_log(f"{self.seat_name(seat)} 过。")
            self._advance_bid()
            return True, ""
        if not self._bid_allowed(seat, bid):
            return False, "这个声明不合法"
        expected_level = {"single": 1, "pair": 2, "nt_small": 3, "nt_big": 4}
        if bid.kind not in expected_level or bid.level != expected_level[bid.kind]:
            return False, "声明牌型不合法"
        if bid.strengthen:
            cur = self.declaration
            if not (cur and cur.seat == seat and cur.kind == "single"
                    and bid.kind == "pair" and bid.suit == cur.suit):
                return False, "只能加固自己刚亮的单张"
        # cards must be in hand and form the declared pattern
        for c in bid.cards:
            if c not in self.hands[seat]:
                return False, "声明用的牌不在手里"
        if bid.kind == "single":
            if len(bid.cards) != 1 or bid.cards[0].rank != self.level or bid.cards[0].suit != bid.suit:
                return False, "单张声明不合法"
        elif bid.kind == "pair":
            if len(bid.cards) != 2:
                return False, "对子声明不合法"
            a, b = bid.cards
            if (a.suit != bid.suit or a.rank != self.level
                    or a.suit != b.suit or a.rank != b.rank):
                return False, "对子声明不合法"
        elif bid.kind == "nt_small":
            if len(bid.cards) != 2 or not all(c.is_small for c in bid.cards):
                return False, "小王对声明不合法"
        elif bid.kind == "nt_big":
            if len(bid.cards) != 2 or not all(c.is_big for c in bid.cards):
                return False, "大王对声明不合法"
        self.declaration = bid
        self.trump_suit = bid.suit
        self.bids.append(bid)
        self.passed_since_bid = set()
        self.add_log(f"{self.seat_name(seat)}：{bid.label()}")
        if self.phase == "bid_extra" and not bid.strengthen:
            self.pending_bury_by = seat
            self.phase = "bury_extra"
            self.add_log(f"{self.seat_name(seat)} 抄底/换底，请埋 8 张。")
            return True, ""
        self._advance_bid()
        return True, ""

    def _advance_bid(self) -> None:
        self.current_bidder = self.next_seat(self.current_bidder)
        if len(self.passed_since_bid) >= 4:
            self._end_bid_phase()

    def _end_bid_phase(self) -> None:
        if self.phase == "bid_initial":
            self._finish_initial_bid()
        else:
            self.start_play()

    def _finish_initial_bid(self) -> None:
        decl = self.declaration
        if decl is None:
            if self.first_deal:
                self.add_log("无人亮主，本局重发。")
                self.start_deal()
                return
            self.trump_suit = None
            self.level = self.levels[self.team(self.zhuang)]
            self.phase = "bury_initial"
            self.pending_bury_by = self.zhuang
            self.extra_allowed = False
            self.add_log("无人亮主，打无主；庄家埋底。")
            return
        if self.first_deal:
            self.zhuang = decl.seat
            self.add_log(f"{self.seat_name(self.zhuang)} 当庄。")
        self.level = self.levels[self.team(self.zhuang)]
        self.trump_suit = decl.suit
        self.phase = "bury_initial"
        self.pending_bury_by = self.zhuang
        self.extra_allowed = True
        trump = "无主" if decl.suit is None else f"{SUIT_NAMES[decl.suit]}主"
        self.add_log(f"主牌：{trump}；庄家 {self.seat_name(self.zhuang)} 埋底。")

    # ------------------------------------------------------------------ bury
    def _combined_bury_pool(self, seat: int) -> List[Card]:
        return list(self.hands[seat]) + list(self.bottom)

    def submit_bury(self, seat: int, cards: Sequence[Card]) -> Tuple[bool, str]:
        if self.phase not in ("bury_initial", "bury_extra"):
            return False, "当前不是埋底阶段"
        if seat != self.pending_bury_by:
            return False, "还没轮到你埋底"
        if len(cards) != 8:
            return False, "必须埋 8 张"
        if len(set(cards)) != 8:
            return False, "埋的牌不能重复"
        combined = self._combined_bury_pool(seat)
        for c in cards:
            if c not in combined:
                return False, "埋的牌不在手牌+底牌里"
        new_hand = list(combined)
        for c in cards:
            new_hand.remove(c)
        if len(new_hand) != 25:
            return False, "剩余手牌必须 25 张"
        self.hands[seat] = sort_hand(new_hand, self.level, self.trump_suit)
        self.bottom = list(cards)
        self.last_burier = seat
        self.seen_bottoms[seat].append(frozenset(cards))
        self.bottom_history.append({
            "burier": seat,
            "cards": list(cards),
            "trick_no": self.trick_no,
        })
        self.add_log(f"{self.seat_name(seat)} 埋底 8 张。")

        if self.phase == "bury_initial":
            if self.extra_allowed:
                self.phase = "bid_extra"
                self.current_bidder = self.next_seat(self.zhuang)
                self.passed_since_bid = set()
                self.add_log("进入抄底阶段：可以反主/换底，加固不换底。")
            else:
                self.start_play()
        else:
            self.phase = "bid_extra"
            self.current_bidder = self.next_seat(seat)
            self.passed_since_bid = set()
            self.add_log("继续抄底阶段。")
        return True, ""

    # ------------------------------------------------------------------ play
    def start_play(self) -> None:
        self.phase = "play"
        self.current_player = self.zhuang
        self.trick = None
        self.add_log("开始出牌，庄家先领。")
        self._start_trick()

    def _start_trick(self) -> None:
        self.trick = Trick(self.current_player)

    def _compute_void_seats(self, lead: LeadPattern) -> None:
        cat = lead.category
        self.trick.void_seats = {
            seat for seat in range(4)
            if not any(cat.contains(c) for c in self.hands[seat])
        }

    def _cards_in_hand(self, seat: int, cards: Sequence[Card]) -> bool:
        hand = list(self.hands[seat])
        for c in cards:
            if c not in hand:
                return False
            hand.remove(c)
        return True

    def play_lead(self, seat: int, cards: Sequence[Card]) -> Tuple[bool, str]:
        if self.phase != "play" or self.trick is None:
            return False, "当前不是出牌阶段"
        if seat != self.current_player:
            return False, "还没轮到你"
        if self.trick.plays:
            return False, "本墩已经有人领出"
        if not cards or len(cards) != len(set(cards)):
            return False, "出牌不合法"
        if not self._cards_in_hand(seat, cards):
            return False, "牌不在手里"
        pattern = decompose_lead(cards, self.level, self.trump_suit)
        if pattern is None:
            return False, "这些牌不能一起出"

        self.last_throw_info = None
        if pattern.is_throw:
            blocker, beatable = throw_blocker(seat, self.hands, pattern, self.level, self.trump_suit)
            if blocker is not None:
                forced = forced_component(pattern, beatable)
                intended = [c.label for c in cards]
                self.throw_blockers.append({
                    "thrower": seat,
                    "blocker": blocker,
                    "intended": intended,     # 原本想甩的牌（用户要能看见）
                    "forced": forced.label(),
                })
                self.last_throw_info = {
                    "thrower": seat,
                    "blocker": blocker,
                    "intended": intended,
                    "forced": forced.label(),
                }
                forced_cards = list(forced.cards)
                for c in forced_cards:
                    self.hands[seat].remove(c)
                forced_pattern = decompose_lead(forced_cards, self.level, self.trump_suit)
                assert forced_pattern is not None
                self.trick.lead = forced_pattern
                self.trick.plays.append((seat, forced_cards))
                self._compute_void_seats(forced_pattern)
                # 记录里要同时给出"原本想甩什么"和"实际出了什么"
                # （用户 2026-11-23 反馈：只看"改出什么"没法回顾自己/电脑想干什么）
                self.add_log(
                    f"{self.seat_name(seat)} 想甩 "
                    f"{', '.join(c.label for c in cards)}，"
                    f"被 {self.seat_name(blocker)} 卡住，"
                    f"改出 {', '.join(c.label for c in forced_cards)}。"
                )
                self.current_player = self.next_seat(seat)
                return True, ""

        for c in cards:
            self.hands[seat].remove(c)
        self.trick.lead = pattern
        self.trick.plays.append((seat, list(cards)))
        self._compute_void_seats(pattern)
        self.add_log(f"{self.seat_name(seat)} 领出 {', '.join(c.label for c in cards)}。")
        self.current_player = self.next_seat(seat)
        return True, ""

    def play_follow(self, seat: int, cards: Sequence[Card]) -> Tuple[bool, str]:
        if self.phase != "play" or self.trick is None or self.trick.lead is None:
            return False, "当前不是出牌阶段"
        if seat != self.current_player:
            return False, "还没轮到你"
        if not cards or len(cards) != len(set(cards)):
            return False, "出牌不合法"
        if len(cards) != len(self.trick.lead.cards):
            return False, f"必须出 {len(self.trick.lead.cards)} 张"
        if not self._cards_in_hand(seat, cards):
            return False, "牌不在手里"
        ok, reason = is_legal_follow(self.hands[seat], cards, self.trick.lead, self.level, self.trump_suit)
        if not ok:
            return False, reason
        for c in cards:
            self.hands[seat].remove(c)
        self.trick.plays.append((seat, list(cards)))
        self.add_log(f"{self.seat_name(seat)} 出 {', '.join(c.label for c in cards)}。")
        if len(self.trick.plays) == 4:
            self._resolve_trick()
        else:
            self.current_player = self.next_seat(seat)
        return True, ""

    def _resolve_trick(self) -> None:
        assert self.trick is not None and self.trick.lead is not None
        result = trick_winner(
            self.trick.plays, self.trick.lead, self.level, self.trump_suit,
            self.trick.void_seats, self.order,
        )
        winner_team = self.team(result.winner)
        zhuang_team = self.team(self.zhuang)
        if winner_team == zhuang_team:
            self.declarer_points += result.points
        else:
            self.defender_points += result.points
        self.trick_history.append({
            "leader": self.trick.leader,
            "lead": [c.label for c in self.trick.lead.cards],
            "plays": [(s, [c.label for c in cs]) for s, cs in self.trick.plays],
            "winner": result.winner,
            "kind": result.winner_kind,
            "points": result.points,
        })
        self.last_trick_lead = self.trick.lead
        self.last_trick_winner = result.winner
        self.trick_no += 1
        self.add_log(
            f"第 {self.trick_no} 墩：{self.seat_name(result.winner)} 赢，"
            f"{result.points} 分。"
        )
        if all(len(self.hands[i]) == 0 for i in range(4)):
            self._settle()
        else:
            self.current_player = result.winner
            self._start_trick()

    # ---------------------------------------------------------------- scoring
    def _settle(self) -> None:
        self.phase = "settle"
        bottom_points = cards_points(self.bottom)
        zhuang_team = self.team(self.zhuang)
        if self.last_trick_winner is not None and self.team(self.last_trick_winner) != zhuang_team:
            mult = bottom_multiplier(self.last_trick_lead) if self.last_trick_lead else 1
            self.defender_points += bottom_points * mult
            self.add_log(f"闲家抠底：底牌 {bottom_points} 分 × {mult} 倍。")
        else:
            mult = 0
            self.add_log("庄家保底，底牌分不结算给闲家。")

        score = self.defender_points
        if score == 0:
            kind, side, delta = "大光", "zhuang", 3
        elif score < 40:
            kind, side, delta = "小光", "zhuang", 2
        elif score < 80:
            kind, side, delta = "庄家守住", "zhuang", 1
        else:
            kind, side, delta = "闲家上台", "def", (score - 80) // 40

        zhuang_level = self.levels[zhuang_team]
        def_team = 1 - zhuang_team
        match_over = False
        winner_team = None
        if side == "zhuang":
            if zhuang_level == 14:
                match_over = True
                winner_team = zhuang_team
            else:
                self.levels[zhuang_team] = min(14, zhuang_level + delta)
            self.next_zhuang = self.partner(self.zhuang)
        else:
            self.levels[def_team] = min(14, self.levels[def_team] + delta)
            self.next_zhuang = self.next_seat(self.zhuang)

        self.match_over = match_over
        if match_over:
            self.winner_team = winner_team
            self.phase = "match_over"
        self.deal_result = {
            "deal_no": self.deal_no,
            "zhuang": self.zhuang,
            "zhuang_team": zhuang_team,
            "level": self.level,
            "trump": "NT" if self.trump_suit is None else self.trump_suit,
            "score": score,
            "kind": kind,
            "side": side,
            "delta": delta,
            "levels_after": dict(self.levels),
            "next_zhuang": self.next_zhuang,
            "bottom_points": bottom_points,
            "multiplier": mult,
            "last_winner": self.last_trick_winner,
            "match_over": match_over,
            "winner_team": winner_team,
        }
        self.add_log(
            f"结算：闲家 {score} 分，{kind}；"
            + (f"胜方 {self.team_name(winner_team)}。" if match_over else "继续下一局。")
        )
        self.deal_record = {
            "deal_no": self.deal_no,
            "zhuang": self.zhuang,
            "level": self.level,
            "trump": "NT" if self.trump_suit is None else self.trump_suit,
            "hands_start": {i: [c.short for c in self.hands_start[i]] for i in range(4)},
            "bottom": [c.short for c in self.bottom],
            "bids": [
                {"seat": b.seat, "label": b.label(), "strengthen": b.strengthen}
                for b in self.bids
            ],
            "tricks": self.trick_history,
            "result": self.deal_result,
            "seen_bottoms": {
                i: [[c.short for c in s] for s in self.seen_bottoms[i]]
                for i in range(4)
            },
            "bottom_history": [
                {"burier": h["burier"], "cards": [c.short for c in h["cards"]]}
                for h in self.bottom_history
            ],
            "throw_blockers": list(self.throw_blockers),
        }

    def next_deal(self) -> None:
        if self.match_over:
            return
        self.first_deal = False
        self.start_deal()
