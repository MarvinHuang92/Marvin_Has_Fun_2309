"""给界面用的 AI 选择器：把三种强度的对手统一成一个接口。

界面只关心"这手牌该出什么"，不需要知道背后是规则、记牌还是搜索。
换强度只改这里的一个字符串，决策逻辑本身全在各自模块里。

| 档位 | 实现 | 特征 |
|---|---|---|
| `rule` | `ai.py` | 原始规则型，最弱，一局约 12 ms |
| `heuristic` | `ai_heuristic.py` | 会记牌 + 给队友送分 + 1 层评估，一局约 80 ms |
| `search` | `ai_heuristic.py` + `ai_search.py` | 记牌之上再做限深度 alpha-beta，每步 100 ms，明显更慢 |
"""
from __future__ import annotations

from typing import List, Optional

from . import ai as rule_ai
from .cards import Card
from .engine import Bid, TractorGame

LEVELS = ("rule", "heuristic", "search")
LEVEL_NAMES = {
    "rule": "简单（原始规则）",
    "heuristic": "会记牌（推荐）",
    "search": "会搜索（很慢）",
}


class AiEngine:
    """一个门面：界面按这个接口调用即可。"""

    def __init__(self, kind: str = "heuristic", search_ms: int = 100) -> None:
        self.kind = kind if kind in LEVELS else "heuristic"
        self.search_ms = search_ms
        self._brain = None
        self._search = None
        self._build()

    def _build(self) -> None:
        if self.kind == "rule":
            self._brain = None
            self._search = None
            return
        from .ai_heuristic import HeuristicAI

        self._brain = HeuristicAI()
        if self.kind == "search":
            from .ai_search import SearchAI
            self._search = SearchAI(depth=40, time_limit=self.search_ms / 1000.0)
        else:
            self._search = None

    def set_kind(self, kind: str) -> None:
        self.kind = kind if kind in LEVELS else self.kind
        self._build()

    # ---------------------------------------------------------------- 生命周期
    def begin_deal(self, game: TractorGame) -> None:
        if self._brain is not None:
            self._brain.begin_deal(game)

    def observe(self, game: TractorGame, seat: int, cards, lead) -> None:
        """每次有人出完牌都要喂进来，记牌器才知道场上少了什么。"""
        if self._brain is not None:
            self._brain.observe(game, seat, cards, lead)

    # ---------------------------------------------------------------- 三个决策
    def bid(self, game: TractorGame, seat: int) -> Optional[Bid]:
        if self._brain is None:
            return rule_ai.choose_bid(game, seat)
        return self._brain.bid(game, seat)

    def bury(self, game: TractorGame, seat: int) -> List[Card]:
        if self._brain is None:
            return rule_ai.choose_bury(game, seat)
        return self._brain.bury(game, seat)

    def note_buried(self, seat: int, cards) -> None:
        if self._brain is not None:
            self._brain.note_buried(seat, cards)

    def play(self, game: TractorGame, seat: int) -> List[Card]:
        if self._brain is None:
            return rule_ai.choose_play(game, seat)
        self._brain._ensure(game, seat)
        if self._search is not None:
            from .fast_state import FastState

            st = FastState.from_game(game)
            self._brain.sync_bottom(st, seat)
            return self._search.choose(st, seat, tracker=self._brain.tracker)
        return self._brain.play(game, seat)
