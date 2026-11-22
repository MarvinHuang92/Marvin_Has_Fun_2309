"""优势网络驱动的出牌 AI：枚举所有合法走法，选优势最高的一手。

和搜索的区别：搜索是"往后推演 + 用价值网络估价"，这里是
**直接问"这一手比平均好多少"**（优势是训练时从真实对局结果里学出来的）。

局面特征用 v1 布局（60 维，按队），动作特征 15 维，拼起来 75 维。
"""
from __future__ import annotations

import random
from typing import List, Optional

from .cards import Card
from .engine import Bid, TractorGame
from .fast_state import FastState
from .moves import legal_moves
from .search import determinize
from . import value_net


class AdvantageAI:
    def __init__(self, model_path: str, seed: int = 20261124,
                 samples: int = 1) -> None:
        self.net = value_net.ValueNet.load(model_path)
        self.rng = random.Random(seed)
        self.samples = max(1, samples)
        self.helper = None
        self.tracker = None
        self._build_helper()

    def _build_helper(self) -> None:
        """亮主/埋底/记牌沿用启发式那一套（优势网络只管出牌）。"""
        from .ai_heuristic import HeuristicAI

        self.helper = HeuristicAI(rng=self.rng)
        self.tracker = self.helper.tracker

    # ------------------------------------------------------------------ 接口
    def begin_deal(self, game: TractorGame) -> None:
        self.helper.begin_deal(game)

    def _ensure(self, game, seat) -> None:
        """和 HeuristicAI 保持接口一致（界面那边会先调一次）。"""
        self.helper._ensure(game, seat)

    def observe(self, game, seat, cards, lead) -> None:
        self.helper.observe(game, seat, cards, lead)

    def note_buried(self, seat, cards) -> None:
        self.helper.note_buried(seat, cards)

    def bid(self, game: TractorGame, seat: int) -> Optional[Bid]:
        return self.helper.bid(game, seat)

    def bury(self, game: TractorGame, seat: int) -> List[Card]:
        return self.helper.bury(game, seat)

    def play(self, game: TractorGame, seat: int) -> List[Card]:
        real = FastState.from_game(game)
        self.helper.sync_bottom(real, seat)

        # **不能直接用手牌全知的 state 算特征**：先抽样若干个与已知信息一致的世界
        worlds = [determinize(real, seat, self.rng, self.tracker)
                  for _ in range(self.samples)]
        cands = legal_moves(worlds[0], seat)
        if not cands:
            return self.helper.play(game, seat)
        if len(cands) == 1:
            return cands[0]

        scores = [0.0] * len(cands)
        for world in worlds:
            team = world.team(seat)
            sf = value_net._features_team(world, team)
            for i, cards in enumerate(cands):
                x = sf + value_net.action_features(world, seat, cards)
                scores[i] += self.net.predict_features(x)

        best_i = max(range(len(cands)), key=lambda i: scores[i])
        return cands[best_i]
