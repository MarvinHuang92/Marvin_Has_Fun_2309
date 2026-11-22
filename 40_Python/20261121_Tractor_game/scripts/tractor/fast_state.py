"""搜索用的轻量状态。

和 `TractorGame` 的区别：

  - 没有 log / trick_history / bottom_history / 存档字段 —— 克隆要快
  - 只保留"出牌阶段"需要的：四家手牌、底牌、分数、领出牌型、本墩出牌、当前座位
  - 重用 `rules.py` 的 `decompose_lead` / `is_legal_follow` / `trick_winner`，
    保证和正式引擎的判罚完全一致

已知简化（骨架阶段的取舍）：

  - **不处理甩牌被卡**：`play()` 直接接受领出的牌型，不会改判"出小"。
    要搜索甩牌时，请用 `moves.legal_leads(..., allow_throws=False)`，
    这样根本不会产生甩牌，二者保持一致。
  - 不结算抠底倍数：搜索只关心"到局末为止的墩分"。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence, Set, Tuple

from .cards import Card, card_points
from .rules import (
    LeadPattern,
    TrickResult,
    decompose_lead,
    is_legal_follow,
    trick_winner,
)

Play = Tuple[int, List[Card]]


@dataclass
class FastState:
    hands: Dict[int, List[Card]]
    bottom: List[Card]
    level: int
    trump_suit: Optional[str]
    zhuang: int
    points: Dict[int, int]            # team -> 已拿到的墩分
    current_player: int
    leader: int = 0
    lead: Optional[LeadPattern] = None
    plays: List[Play] = field(default_factory=list)
    void_seats: Set[int] = field(default_factory=set)
    trick_no: int = 0
    last_burier: Optional[int] = None      # 谁是最后埋底的人（决定"我知不知道底牌"）
    # 埋底的先后顺序（每次埋底/换底都记一个座位）。换底可能连续发生多次，
    # 推"我看过的底牌现在在谁手里"必须用这个顺序，只用 last_burier 是错的。
    buriers: Tuple[int, ...] = ()

    # ------------------------------------------------------------------ 构造
    @classmethod
    def from_game(cls, game) -> "FastState":
        zt = game.team(game.zhuang) if game.zhuang is not None else 0
        st = cls(
            hands={s: list(game.hands[s]) for s in range(4)},
            bottom=list(game.bottom),
            level=game.level,
            trump_suit=game.trump_suit,
            zhuang=game.zhuang if game.zhuang is not None else 0,
            points={zt: game.declarer_points, 1 - zt: game.defender_points},
            current_player=game.zhuang if game.zhuang is not None else 0,
            leader=game.zhuang if game.zhuang is not None else 0,
        )
        # 把当前这一墩也接过来，这样能直接对着"正在进行中的局面"搜索/启发式打分
        if game.trick is not None and game.trick.lead is not None:
            st.lead = game.trick.lead
            st.plays = [(s, list(cs)) for s, cs in game.trick.plays]
            st.void_seats = set(game.trick.void_seats)
            st.current_player = game.current_player
            st.leader = game.trick.leader
        st.trick_no = getattr(game, "trick_no", 0)
        st.last_burier = getattr(game, "last_burier", None)
        hist = getattr(game, "bottom_history", None) or []
        st.buriers = tuple(h.get("burier") for h in hist
                           if h.get("burier") is not None)
        return st

    def clone(self) -> "FastState":
        return FastState(
            hands={s: list(h) for s, h in self.hands.items()},
            bottom=list(self.bottom),
            level=self.level,
            trump_suit=self.trump_suit,
            zhuang=self.zhuang,
            points=dict(self.points),
            current_player=self.current_player,
            leader=self.leader,
            lead=self.lead,                     # LeadPattern 建好后不再修改，可共享
            plays=[(s, list(cs)) for s, cs in self.plays],
            void_seats=set(self.void_seats),
            trick_no=self.trick_no,
            last_burier=self.last_burier,
            buriers=self.buriers,
        )

    # ------------------------------------------------------------------ 基础
    @staticmethod
    def team(seat: int) -> int:
        return 0 if seat in (0, 2) else 1

    @staticmethod
    def partner(seat: int) -> int:
        return (seat + 2) % 4

    @staticmethod
    def next_seat(seat: int) -> int:
        return (seat + 1) % 4

    def team_of_player(self, seat: int) -> int:
        return self.team(seat)

    def is_terminal(self) -> bool:
        return all(len(self.hands[s]) == 0 for s in range(4))

    def defender_points(self) -> int:
        return self.points[1 - self.team(self.zhuang)]

    def declarer_points(self) -> int:
        return self.points[self.team(self.zhuang)]

    # ------------------------------------------------------------------ 出牌
    def _compute_void_seats(self, lead: LeadPattern) -> None:
        cat = lead.category
        self.void_seats = {
            s for s in range(4) if not any(cat.contains(c) for c in self.hands[s])
        }

    def cards_in_hand(self, seat: int, cards: Sequence[Card]) -> bool:
        pool = list(self.hands[seat])
        for c in cards:
            if c not in pool:
                return False
            pool.remove(c)
        return True

    def play(self, seat: int, cards: Sequence[Card],
             validate: bool = True) -> Tuple[bool, str, Optional[TrickResult]]:
        """出一次牌。如果这一墩凑满 4 手，会自动结算并返回 TrickResult。

        `validate=False`：跳过 `is_legal_follow` 校验。**只给搜索引擎用**——
        搜索里的动作全部来自 `moves.legal_moves*` 的合法枚举，再校验一遍是纯浪费
        （profile 里 match_slots/is_legal_follow 占 17%）。调用方要自己保证合法。
        """
        if seat != self.current_player:
            return False, "还没轮到他", None
        cards = list(cards)
        if not cards or len(cards) != len(set(cards)):
            return False, "出牌不合法", None
        if not self.cards_in_hand(seat, cards):
            return False, "牌不在手里", None

        if self.lead is None:
            pattern = decompose_lead(cards, self.level, self.trump_suit)
            if pattern is None:
                return False, "这些牌不能一起出", None
            for c in cards:
                self.hands[seat].remove(c)
            self.lead = pattern
            self.plays = [(seat, cards)]
            self._compute_void_seats(pattern)
            self.leader = seat
            self.current_player = self.next_seat(seat)
            return True, "", None

        if len(cards) != len(self.lead.cards):
            return False, "张数不对", None
        if validate:
            ok, reason = is_legal_follow(self.hands[seat], cards, self.lead,
                                         self.level, self.trump_suit)
            if not ok:
                return False, reason, None
        for c in cards:
            self.hands[seat].remove(c)
        self.plays.append((seat, cards))

        if len(self.plays) < 4:
            self.current_player = self.next_seat(seat)
            return True, "", None
        return True, "", self._resolve()

    def _resolve(self) -> TrickResult:
        assert self.lead is not None
        result = trick_winner(
            self.plays, self.lead, self.level, self.trump_suit, self.void_seats, (0, 1, 2, 3)
        )
        self.points[self.team(result.winner)] += result.points
        self.trick_no += 1
        self.current_player = result.winner
        self.leader = result.winner
        self.lead = None
        self.plays = []
        self.void_seats = set()
        return result

    # ------------------------------------------------------------------ 评估
    def winner_so_far(self) -> Optional[int]:
        """本墩目前谁最大（用于"队友是否领先"的判断）。"""
        if self.lead is None or not self.plays:
            return None
        result = trick_winner(
            self.plays, self.lead, self.level, self.trump_suit, self.void_seats, (0, 1, 2, 3)
        )
        return result.winner

    def points_on_table(self) -> int:
        return sum(card_points(c) for _, cs in self.plays for c in cs)

    def position_key(self) -> Tuple:
        "置换表用的键：**不含分数**（搜索值就是从现在到局末的净得分，与已得分无关）。"
        return (
            self.current_player,
            tuple(tuple(sorted(self.hands[s])) for s in range(4)),
            self.lead.cards if self.lead else (),
            tuple((s, tuple(sorted(cs))) for s, cs in self.plays),
        )

    def key(self) -> Tuple:
        """置换表用的状态键（不含牌序，只含牌集合）。"""
        return (
            self.trick_no,
            self.current_player,
            tuple(sorted((s, tuple(sorted(self.hands[s]))) for s in range(4))),
            self.lead.cards if self.lead else (),
            tuple((s, tuple(sorted(cs))) for s, cs in self.plays),
            self.points[0],
            self.points[1],
        )
