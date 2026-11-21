"""阶段 0：对局评测台（先把尺子钉死）。

为什么需要它：这个游戏的单局方差极大（闲家得分 0~200，还有 ×64 抠底），
而且庄/闲两种角色的目标相反。没有固定口径的话，任何"改进了"的结论都是噪声
——这是 6 Nimmt 那个项目花六轮才学到的教训。

口径：

  - **同一副牌、两队对战、庄闲天然轮换**（谁亮主谁当庄，不人为指定）
  - 每个数据点 = 一局，指标 = **A 队的升级增量**（`a_delta`）
      赢下这一局（庄家守住 或 闲家上台）记 +delta，输记 -delta
  - 报 95% 区间

用法::

    python -m tractor.eval_harness --a rule --b heuristic --deals 200
    python -m tractor.eval_harness --a heuristic --b heuristic --deals 200 --self-check
"""
from __future__ import annotations

import argparse
import math
import random
import sys
from typing import Dict, List, Optional, Sequence

from . import ai as rule_ai
from .engine import TractorGame
from .moves import legal_moves


# ---------------------------------------------------------------------------
# 策略接口
# ---------------------------------------------------------------------------

class Policy:
    name = "policy"

    def begin_deal(self, game: TractorGame) -> None:      # 可选
        pass

    def observe(self, game, seat, cards, lead) -> None:   # 可选
        pass

    def bid(self, game: TractorGame, seat: int):
        raise NotImplementedError

    def bury(self, game: TractorGame, seat: int) -> List:
        raise NotImplementedError

    def play(self, game: TractorGame, seat: int) -> List:
        raise NotImplementedError


class RulePolicy(Policy):
    """包装原有的规则型 AI（`ai.py`）。"""

    def __init__(self, name: str = "rule"):
        self.name = name

    def bid(self, game, seat):
        return rule_ai.choose_bid(game, seat)

    def bury(self, game, seat):
        return rule_ai.choose_bury(game, seat)

    def play(self, game, seat):
        return rule_ai.choose_play(game, seat)


class HeuristicPolicy(Policy):
    """包装新的启发式 AI（`ai_heuristic.py`）。"""

    def __init__(self, name: str = "heuristic", seed: int = 20261121):
        from .ai_heuristic import HeuristicAI

        self.ai = HeuristicAI(rng=random.Random(seed))
        self.name = name

    def begin_deal(self, game):
        self.ai.begin_deal(game)

    def observe(self, game, seat, cards, lead):
        self.ai.observe(game, seat, cards, lead)

    def bid(self, game, seat):
        return self.ai.bid(game, seat)

    def bury(self, game, seat):
        return self.ai.bury(game, seat)

    def play(self, game, seat):
        return self.ai.play(game, seat)


class SearchPolicy(Policy):
    """阶段 3：亮主/埋底沿用启发式，出牌换成限深度搜索。"""

    def __init__(self, name: str = "search", seed: int = 20261122,
                 depth: int = 10, time_limit: float = 0.05):
        from .ai_heuristic import HeuristicAI
        from .ai_search import SearchAI

        self.ai = HeuristicAI(rng=random.Random(seed))
        self.brain = SearchAI(depth=depth, time_limit=time_limit, seed=seed)
        self.name = name

    def begin_deal(self, game):
        self.ai.begin_deal(game)

    def observe(self, game, seat, cards, lead):
        self.ai.observe(game, seat, cards, lead)

    def bid(self, game, seat):
        return self.ai.bid(game, seat)

    def bury(self, game, seat):
        return self.ai.bury(game, seat)

    def play(self, game, seat):
        from .fast_state import FastState

        return self.brain.choose(FastState.from_game(game), seat)


REGISTRY = {
    "rule": RulePolicy,
    "heuristic": HeuristicPolicy,
    "search": SearchPolicy,
}


# ---------------------------------------------------------------------------
# 单局
# ---------------------------------------------------------------------------

def _submit(game: TractorGame, seat: int, cards: Sequence) -> bool:
    """把选好的牌交给引擎，失败时用合法枚举兜底。"""
    if game.trick is None or game.trick.lead is None:
        ok, _ = game.play_lead(seat, cards)
    else:
        ok, _ = game.play_follow(seat, cards)
    if ok:
        return True

    # 兜底：从合法动作里挑一个
    from .fast_state import FastState

    st = FastState.from_game(game)
    fallback = legal_moves(st, seat, max_moves=32)
    for mv in fallback:
        if game.trick is None or game.trick.lead is None:
            ok, _ = game.play_lead(seat, mv)
        else:
            ok, _ = game.play_follow(seat, mv)
        if ok:
            return True
    raise RuntimeError("座位 %d 找不到任何合法出牌（引擎状态可能不一致）" % seat)


def play_deal(seed: int, p0: Policy, p1: Policy, max_steps: int = 20000) -> TractorGame:
    """打一局（从 3 打起、单局、不跨局升级）。"""
    game = TractorGame(seed)
    game.start_match()
    p0.begin_deal(game)
    p1.begin_deal(game)

    for _ in range(max_steps):
        phase = game.phase
        seat = game.acting_seat()
        if seat is None:
            break
        pol = p0 if game.team(seat) == 0 else p1
        if phase in ("bid_initial", "bid_extra"):
            game.submit_bid(seat, pol.bid(game, seat))
        elif phase in ("bury_initial", "bury_extra"):
            game.submit_bury(seat, pol.bury(game, seat))
        elif phase == "play":
            cards = pol.play(game, seat)
            lead_before = game.trick.lead if game.trick else None
            if _submit(game, seat, cards):
                p0.observe(game, seat, list(cards), lead_before)
                p1.observe(game, seat, list(cards), lead_before)
        else:
            break
    return game


# ---------------------------------------------------------------------------
# 统计
# ---------------------------------------------------------------------------

def mean_ci(values: Sequence[float]) -> tuple:
    n = len(values)
    if n == 0:
        return 0.0, 0.0
    m = sum(values) / n
    if n < 2:
        return m, 0.0
    sd = math.sqrt(sum((v - m) ** 2 for v in values) / (n - 1))
    return m, 1.96 * sd / math.sqrt(n)


def deal_outcome(result: dict) -> Dict[str, object]:
    """把 deal_result 归一化成"team0 视角"。"""
    zt = result["zhuang_team"]
    side = result["side"]
    delta = result["delta"]
    win_team = zt if side == "zhuang" else 1 - zt
    return {
        "score": result["score"],
        "zhuang_team": zt,
        "win_team": win_team,
        "a_delta": delta if win_team == 0 else -delta,
        "a_is_zhuang": zt == 0,
        "kind": result["kind"],
    }


def compare(p0: Policy, p1: Policy, deals: int, seed_base: int = 700000) -> Dict[str, object]:
    deltas: List[float] = []
    scores_as_dealer: List[int] = []      # team0 当庄家时，闲家（对手）拿到的分
    scores_as_defender: List[int] = []    # team0 当闲家时，自己拿到的分
    kinds: Dict[str, int] = {}

    for i in range(deals):
        g = play_deal(seed_base + i, p0, p1)
        if g.deal_result is None:
            continue
        out = deal_outcome(g.deal_result)
        deltas.append(out["a_delta"])
        if out["a_is_zhuang"]:
            scores_as_dealer.append(out["score"])
        else:
            scores_as_defender.append(out["score"])
        kinds[out["kind"]] = kinds.get(out["kind"], 0) + 1

    m, ci = mean_ci(deltas)
    return {
        "deals": len(deltas),
        "a_delta": (m, ci),
        "as_dealer": mean_ci(scores_as_dealer) if scores_as_dealer else (0.0, 0.0),
        "as_dealer_n": len(scores_as_dealer),
        "as_defender": mean_ci(scores_as_defender) if scores_as_defender else (0.0, 0.0),
        "as_defender_n": len(scores_as_defender),
        "kinds": kinds,
    }


def report(p0: Policy, p1: Policy, stats: Dict[str, object]) -> None:
    m, ci = stats["a_delta"]
    print("=" * 66)
    print("A = %-12s   B = %-12s   %d 局" % (p0.name, p1.name, stats["deals"]))
    print("=" * 66)
    print("  A 队平均升级增量 %+0.3f ±%.3f   (正数 = A 赢)" % (m, ci))
    dm, dci = stats["as_dealer"]
    print("  A 当庄家 %3d 局：闲家得分 %6.2f ±%.2f（越低越好）"
          % (stats["as_dealer_n"], dm, dci))
    fm, fci = stats["as_defender"]
    print("  A 当闲家 %3d 局：自己得分 %6.2f ±%.2f（越高越好）"
          % (stats["as_defender_n"], fm, fci))
    print("  结局分布：" + "，".join("%s %d" % (k, v) for k, v in sorted(stats["kinds"].items())))


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="拖拉机 AI 评测台（阶段 0）")
    ap.add_argument("--a", default="rule", choices=sorted(REGISTRY))
    ap.add_argument("--b", default="heuristic", choices=sorted(REGISTRY))
    ap.add_argument("--deals", type=int, default=100)
    ap.add_argument("--seed", type=int, default=700000)
    ap.add_argument("--self-check", action="store_true", help="A 和 B 用同一策略，验证评测台本身无偏")
    ap.add_argument("--depth", type=int, default=10, help="搜索最大深度（手牌数）")
    ap.add_argument("--time", type=float, default=0.05, help="每步搜索的时间预算（秒）")
    args = ap.parse_args(argv)

    def make(name):
        if name == "search":
            return SearchPolicy(name=name, depth=args.depth, time_limit=args.time)
        return REGISTRY[name]()

    pa = make(args.a)
    pb = make(args.b)
    if args.self_check:
        pb = make(args.a)

    stats = compare(pa, pb, args.deals, args.seed)
    report(pa, pb, stats)
    return 0


if __name__ == "__main__":
    sys.exit(main())
