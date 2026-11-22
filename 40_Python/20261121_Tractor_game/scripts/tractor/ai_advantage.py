"""优势网络驱动的出牌 AI：枚举所有合法走法，选优势最高的一手。

和搜索的区别：搜索是"往后推演 + 用价值网络估价"，这里是
**直接问"这一手比平均好多少"**（优势是训练时从真实对局结果里学出来的）。

局面特征用 v1 布局（60 维，按队），动作特征 15 维，拼起来 75 维。
"""
from __future__ import annotations

import random
from collections import Counter
from typing import List, Optional

from .cards import Card
from .engine import Bid, TractorGame
from .fast_state import FastState
from .moves import legal_moves
from .search import determinize
from . import value_net
from .cards import make_deck as _make_deck
from .memory import card_id as _cid

_DECK = _make_deck()


class AdvantageAI:
    def __init__(self, model_path: str, seed: int = 20261124,
                 samples: int = 1, waste_filter: bool = True,
                 no_ruff_zero: bool = True, tempo: float = 5.0,
                 risk: float = 0.0) -> None:
        self.opts = {"waste_filter": waste_filter, "no_ruff_zero": no_ruff_zero,
                     "tempo": tempo, "risk": risk}
        self.net = value_net.ValueNet.load(model_path)
        self.rng = random.Random(seed)
        self.samples = max(1, samples)
        # 动作特征版本由权重维度推断：75 = 60+15(v1)，80 = 60+20(v2)
        self.action_version = 2 if (len(self.net.w1[0]) - 60) == 20 else 1
        self.helper = None
        self._build_helper()

    def _build_helper(self) -> None:
        """亮主/埋底/记牌沿用启发式那一套（优势网络只管出牌）。"""
        from .ai_heuristic import HeuristicAI

        self.helper = HeuristicAI(rng=self.rng)

    @property
    def tracker(self):
        """记牌器是 `begin_deal` 时才建的，所以这里必须每次现取。

        早先写成 `self.tracker = self.helper.tracker`（构造时取），拿到的是 None，
        导致 determinize **一直没用缺门约束** —— 相当于把记牌信息白扔了。
        """
        return self.helper.tracker

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

    def _can_win(self, world, seat, cands) -> bool:
        """这一墩我还可能赢吗（只看桌面上已经亮出来的牌）。"""
        my_team = world.team(seat)
        for mv in cands:
            tmp = world.clone()
            ok, _, res = tmp.play(seat, mv)
            if not ok:
                continue
            if res is not None:
                if world.team(res.winner) == my_team:
                    return True
            elif tmp.winner_so_far() == seat:
                return True
        return False

    def _filter_waste(self, world, seat, cands):
        """本墩结果已经不受我影响时，把候选缩到"最废的几张"。

        只在这种情况下动手，其余局面完全交给网络，所以不会把 AI 写死。
        """
        if not world.plays:
            return cands
        winner = world.winner_so_far()
        if winner is None:
            return cands
        my_team = world.team(seat)

        # 零分墩别用主牌毙：赢了也没有收益，只是白烧一张主牌。
        # 只有"我缺门、还有副牌能垫"时才这么限制。
        if self.opts.get("no_ruff_zero", True):
            from .cards import is_trump

            lead_cat = world.lead.category
            if (not lead_cat.is_trump and world.points_on_table() == 0
                    and world.team(winner) != my_team):
                if not any(lead_cat.contains(c) for c in world.hands[seat]):
                    non_trump = [mv for mv in cands
                                 if not all(is_trump(c, world.level, world.trump_suit)
                                            for c in mv)]
                    if non_trump:
                        cands = non_trump

        if self._can_win(world, seat, cands):
            return cands                      # 还可能赢，交给网络

        partner_winning = world.team(winner) == my_team
        from .cards import is_trump
        from .rules import build_category

        def card_power(c):
            if is_trump(c, world.level, world.trump_suit):
                cat = build_category(world.level, world.trump_suit, None)
            else:
                cat = build_category(world.level, world.trump_suit, c.suit)
            return cat.power_of(c) or 0

        def broken_pairs(mv) -> int:
            hand = world.hands[seat]
            before = Counter(c.rank for c in hand)
            after = Counter(c.rank for c in hand if c not in mv)
            return sum(1 for r, n in before.items()
                       if n >= 2 and after.get(r, 0) < 2)

        def waste(mv) -> float:
            # 直接按**牌力**算，不用 _cost（那里牌力权重只有 0.05，容差会漏掉 10 点牌力差）
            pw = sum(card_power(c) for c in mv)
            brk = broken_pairs(mv)
            pts = sum(5 if c.rank == 5 else (10 if c.rank in (10, 13) else 0)
                      for c in mv)
            # 队友赢着 -> 垫分是好事（减分）；本墩已输 -> 送分是纯亏（加分）
            return pw + 9.0 * brk + (-3.0 if partner_winning else 4.0) * pts

        vals = [waste(mv) for mv in cands]
        best = min(vals)
        short = [mv for mv, v in zip(cands, vals) if v <= best + 0.2]
        return short or cands

    def _lead_risk(self, world, seat, mv) -> float:
        """领出这一手的风险（0~1 的"被打回来"概率 × 代价）。"""
        from bisect import bisect_right

        from .cards import is_trump
        from .rules import build_category

        level, trump = world.level, world.trump_suit
        kind = "T" if is_trump(mv[0], level, trump) else mv[0].suit
        cat = build_category(level, trump, None if kind == "T" else kind)
        top = max(cat.power_of(c) or 0 for c in mv)
        pts = sum(5 if c.rank == 5 else (10 if c.rank in (10, 13) else 0) for c in mv)
        cost = sum((cat.power_of(c) or 0) for c in mv) / 1000.0

        tr = self.tracker
        if tr is None:
            return 0.0

        # 未见牌里这一门的牌力分布（每次决策缓存一次）
        cache = getattr(self, "_risk_cache", None)
        key = (id(world), kind)
        if cache is None or cache.get("key") != id(world):
            cache = {"key": id(world)}
            unseen = tr.unseen_ids()
            by_kind = {}
            for c in _DECK:
                if _cid(c) in unseen:
                    k = "T" if is_trump(c, level, trump) else c.suit
                    by_kind.setdefault(k, []).append(
                        build_category(level, trump,
                                       None if k == "T" else k).power_of(c) or 0)
            for k in by_kind:
                by_kind[k].sort()
            cache["kinds"] = by_kind
            self._risk_cache = cache
        powers = cache["kinds"].get(kind, [])
        n = len(powers)
        k_beat = n - bisect_right(powers, top)

        p_total = 1.0
        my_team = world.team(seat)
        for other in range(4):
            if world.team(other) == my_team:
                continue
            h = len(world.hands[other])
            if tr.is_void(other, kind):
                # 缺门：有主牌就能毙（主牌还剩多少不知道，给个保守概率）
                p = 0.7 if tr.trumps_remaining_upper() > 0 else 0.0
            elif n <= 0:
                p = 0.0
            else:
                p = min(1.0, k_beat * h / n)
            p_total *= (1.0 - p)
        p_beat = 1.0 - p_total
        return p_beat * (pts + cost)

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

        if self.opts.get("waste_filter", True):
            cands = self._filter_waste(worlds[0], seat, cands)

        # 「牌权」软奖励：从对方手里抢到领先，额外给分（和启发式那条同一个思路）
        tempo = self.opts.get("tempo", 0.0)
        lead_bonus = [0.0] * len(cands)
        if tempo:
            w0 = worlds[0]
            prev = w0.winner_so_far() if w0.plays else None
            if prev is not None and w0.team(prev) != w0.team(seat):
                for i, mv in enumerate(cands):
                    tmp = w0.clone()
                    ok, _, res = tmp.play(seat, mv)
                    if not ok:
                        continue
                    took = ((res is not None and w0.team(res.winner) == w0.team(seat))
                            or (res is None and tmp.winner_so_far() == seat))
                    if took:
                        lead_bonus[i] = tempo

        # 「优势 − λ·风险」：只在领出时算风险
        risk_lam = self.opts.get("risk", 0.0)
        risk_pen = [0.0] * len(cands)
        if risk_lam and not worlds[0].plays:
            self._risk_cache = None
            for i, mv in enumerate(cands):
                if len(mv) >= 2:
                    risk_pen[i] = risk_lam * self._lead_risk(worlds[0], seat, mv)

        scores = [0.0] * len(cands)
        for world in worlds:
            team = world.team(seat)
            sf = value_net._features_team(world, team)
            for i, cards in enumerate(cands):
                x = sf + value_net.action_features(world, seat, cards,
                                                   self.action_version)
                scores[i] += self.net.predict_features(x) + lead_bonus[i] - risk_pen[i]

        best_i = max(range(len(cands)), key=lambda i: scores[i])
        return cands[best_i]
