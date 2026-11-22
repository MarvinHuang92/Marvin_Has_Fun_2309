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
    """包装启发式 AI（`ai_heuristic.py`）。`opts` 控制中前盘的各个开关。"""

    def __init__(self, name: str = "heuristic", seed: int = 20261121, opts=None):
        from .ai_heuristic import HeuristicAI

        self.ai = HeuristicAI(rng=random.Random(seed), opts=opts)
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


class AdvantagePolicy(HeuristicPolicy):
    """优势网络直接选牌：枚举所有合法走法，取「(局面,动作) -> 优势」最高的一手。

    亮主/埋底/记牌沿用启发式（优势网络只负责出牌）。
    """

    def __init__(self, name: str = "adv", seed: int = 20261124,
                 model: str = "models/adv_v1.json", samples: int = 1,
                 waste_filter: bool = True) -> None:
        from pathlib import Path

        from .ai_advantage import AdvantageAI

        path = Path(model)
        if not path.is_absolute():
            path = Path(__file__).resolve().parents[2] / path
        self.ai = AdvantageAI(str(path), seed=seed, samples=samples,
                              waste_filter=waste_filter)
        self.name = name


class SearchPolicy(Policy):
    """阶段 3：亮主/埋底沿用启发式，出牌换成限深度搜索。"""

    def __init__(self, name: str = "search", seed: int = 20261122,
                 depth: int = 10, time_limit: float = 0.05,
                 eval_kind: str = "control", follow_variants: int = 2):
        from .ai_heuristic import HeuristicAI
        from .ai_search import SearchAI

        self.ai = HeuristicAI(rng=random.Random(seed))
        self.brain = SearchAI(depth=depth, time_limit=time_limit, seed=seed,
                              eval_kind=eval_kind,
                              follow_variants=follow_variants)
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

        st = FastState.from_game(game)
        self.ai._ensure(game, seat)
        self.ai.sync_bottom(st, seat)
        return self.brain.choose(st, seat, tracker=self.ai.tracker)


class PIMCPolicy(Policy):
    """阶段 3-②：多世界采样 + 限深度搜索。

    亮主/埋底沿用启发式；出牌时按缺门约束采样 N 个世界，搜索后按根节点估值平均。
    """

    def __init__(self, name: str = "pimc", seed: int = 20261122,
                 depth: int = 40, time_limit: float = 0.03, samples: int = 4,
                 eval_kind: str = "control", follow_variants: int = 2):
        from .ai_heuristic import HeuristicAI
        from .ai_pimc import PIMCAI

        self.ai = HeuristicAI(rng=random.Random(seed))
        self.brain = PIMCAI(depth=depth, time_limit=time_limit,
                            samples=samples, seed=seed, eval_kind=eval_kind,
                            follow_variants=follow_variants)
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

        st = FastState.from_game(game)
        self.ai._ensure(game, seat)
        self.ai.sync_bottom(st, seat)
        return self.brain.choose(st, seat, tracker=self.ai.tracker)


REGISTRY = {
    "rule": RulePolicy,
    "heuristic": HeuristicPolicy,
    "adv": AdvantagePolicy,
    "search": SearchPolicy,
    "pimc": PIMCPolicy,
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


def _note_buried(pol: Policy, seat: int, cards) -> None:
    """把"这一手埋底是我埋的"告诉策略（只有真的提交了才调）。

    策略不一定是启发式（rule 没有记牌器），所以用鸭子类型。
    """
    ai = getattr(pol, "ai", None)
    if ai is not None and hasattr(ai, "note_buried"):
        ai.note_buried(seat, cards)


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
            buried = pol.bury(game, seat)
            ok, _ = game.submit_bury(seat, buried)
            if ok:
                _note_buried(pol, seat, buried)
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


def deal_outcome(result: dict, a_team: int = 0) -> Dict[str, object]:
    """把 deal_result 归一化成"a_team 视角"。

    `a_team` 不一定是 0：为了消掉座位顺序带来的固定偏置，评测时两局交换阵营。
    """
    zt = result["zhuang_team"]
    side = result["side"]
    delta = result["delta"]
    win_team = zt if side == "zhuang" else 1 - zt
    return {
        "score": result["score"],
        "zhuang_team": zt,
        "win_team": win_team,
        "a_delta": delta if win_team == a_team else -delta,
        "a_is_zhuang": zt == a_team,
        "kind": result["kind"],
    }


def compare(p0: Policy, p1: Policy, deals: int, seed_base: int = 700000) -> Dict[str, object]:
    deltas: List[float] = []
    scores_as_dealer: List[int] = []      # team0 当庄家时，闲家（对手）拿到的分
    scores_as_defender: List[int] = []    # team0 当闲家时，自己拿到的分
    kinds: Dict[str, int] = {}

    for i in range(deals):
        # 逐局交换阵营：A 一半的局坐 team 1，抵消座位顺序的不对称
        swap = (i % 2 == 1)
        p_team0, p_team1 = (p1, p0) if swap else (p0, p1)
        a_team = 1 if swap else 0
        g = play_deal(seed_base + i, p_team0, p_team1)
        if g.deal_result is None:
            continue
        out = deal_outcome(g.deal_result, a_team)
        deltas.append(out["a_delta"])
        if out["a_is_zhuang"]:
            scores_as_dealer.append(out["score"])
        else:
            scores_as_defender.append(out["score"])
        kinds[out["kind"]] = kinds.get(out["kind"], 0) + 1

    m, ci = mean_ci(deltas)
    return {
        "deals": len(deltas),
        "per_deal": deltas,
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
    ap.add_argument("--time", type=float, default=0.05, help="A 方每个世界的时间预算（秒）")
    ap.add_argument("--time-b", type=float, default=None, help="B 方的时间预算（默认同 --time）")
    ap.add_argument("--samples", type=int, default=4, help="PIMC 采样的世界数（A 方）")
    ap.add_argument("--samples-b", type=int, default=None, help="B 方的世界数")
    ap.add_argument("--a-eval", default="control",
                    choices=["rank", "control", "value"],
                    help="A 方搜索用的估价模型")
    ap.add_argument("--b-eval", default="control",
                    choices=["rank", "control", "value"],
                    help="B 方搜索用的估价模型")
    ap.add_argument("--a-follow", type=int, default=2,
                    help="A 方搜索内部节点的跟牌候选数（2 或 4）")
    ap.add_argument("--b-follow", type=int, default=2,
                    help="B 方搜索内部节点的跟牌候选数（2 或 4）")
    ap.add_argument("--a-adv-model", default="", help="A 方 adv 策略用的模型")
    ap.add_argument("--b-adv-model", default="", help="B 方 adv 策略用的模型")
    ap.add_argument("--adv-waste", type=int, default=1,
                    help="adv 策略是否启用「本墩已定只出废牌」过滤器")
    ap.add_argument("--a-adv-waste", type=int, default=None,
                    help="A 方 adv 是否启用废牌过滤器（覆盖 --adv-waste）")
    ap.add_argument("--b-adv-waste", type=int, default=None,
                    help="B 方 adv 是否启用废牌过滤器")
    ap.add_argument("--adv-samples", type=int, default=1,
                    help="adv 策略每次决策抽样几个世界做平均")
    ap.add_argument("--adv-model", default="models/adv_v1.json",
                    help="adv 策略用的优势网络")
    ap.add_argument("--dump", default="", help="把逐局 a_delta 写到这个文件（做配对比较）")
    ap.add_argument("--value-model", default="models/value_v4.json",
                    help="eval=value 时加载的价值网络")
    ap.add_argument("--a-opts", default="", help="A 方启发式开关，如 bury_void=1,lead_master=1")
    ap.add_argument("--b-opts", default="", help="B 方启发式开关")
    args = ap.parse_args(argv)
    t_b = args.time if args.time_b is None else args.time_b
    s_b = args.samples if args.samples_b is None else args.samples_b

    def parse_opts(text):
        """把 "k=v,k2=v2" 解析成 dict。

        注意**要保留数值类型**：早期版本把每个值都转成布尔，
        `bid_min=32` 会变成 True，导致两个不同阈值的实验跑出完全一样的结果。
        """
        opts = {}
        for part in filter(None, text.split(",")):
            k, _, v = part.partition("=")
            k, v = k.strip(), v.strip()
            if v in ("", "0", "false", "False"):
                opts[k] = False
                continue
            if v in ("1", "true", "True"):
                opts[k] = True
                continue
            try:
                opts[k] = int(v)
                continue
            except ValueError:
                pass
            try:
                opts[k] = float(v)
                continue
            except ValueError:
                pass
            opts[k] = v
        return opts

    def make(name, budget, samples, opts_text="", eval_kind="control",
             follow_variants=2, adv_model="", adv_waste=None):
        if name == "adv":
            return AdvantagePolicy(name=name, model=adv_model or args.adv_model,
                                   samples=args.adv_samples,
                                   waste_filter=bool(args.adv_waste
                                                     if adv_waste is None
                                                     else adv_waste))
        if name == "search":
            return SearchPolicy(name=name, depth=args.depth, time_limit=budget,
                                eval_kind=eval_kind,
                                follow_variants=follow_variants)
        if name == "pimc":
            return PIMCPolicy(name=name, depth=args.depth, time_limit=budget,
                              samples=samples, eval_kind=eval_kind,
                              follow_variants=follow_variants)
        if name in ("heuristic", "heuristic2"):
            return HeuristicPolicy(name=name, opts=parse_opts(opts_text))
        return REGISTRY[name]()

    if "value" in (args.a_eval, args.b_eval):
        from pathlib import Path

        from . import value_net

        model_path = Path(args.value_model)
        if not model_path.is_absolute():
            model_path = Path(__file__).resolve().parents[2] / model_path
        value_net.load_active(str(model_path))
        print("已加载价值网络：%s" % model_path)

    pa = make(args.a, args.time, args.samples, args.a_opts, args.a_eval,
              args.a_follow, args.a_adv_model, args.a_adv_waste)
    pb = make(args.b, t_b, s_b, args.b_opts, args.b_eval, args.b_follow,
              args.b_adv_model, args.b_adv_waste)
    if args.self_check:
        pb = make(args.a, args.time, args.samples, args.a_opts)

    stats = compare(pa, pb, args.deals, args.seed)
    report(pa, pb, stats)
    if args.dump:
        with open(args.dump, "w", encoding="utf-8") as f:
            for i, d in enumerate(stats["per_deal"]):
                f.write("%d,%.4f\n" % (i, d))
        print("逐局结果已写入：%s" % args.dump)
    return 0


if __name__ == "__main__":
    sys.exit(main())
