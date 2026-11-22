# -*- coding: utf-8 -*-
"""收敛探针：固定局面，逐步加大搜索预算，看决策和根估值什么时候不再变。

如果 0.1 秒和 10 秒选出同一手牌、根估值也基本不动，
那"给搜索更多时间"就是无效的 —— 它早就饱和了。

跑法::

    python scripts/conv_probe.py            # 默认 20 个局面
    python scripts/conv_probe.py 30
"""
from __future__ import annotations

import os
import random
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from tractor import value_net  # noqa: E402
from tractor import ai as rule_ai  # noqa: E402
from tractor.engine import TractorGame  # noqa: E402
from tractor.fast_state import FastState  # noqa: E402
from tractor.search import Searcher, determinize  # noqa: E402

BUDGETS = (0.05, 0.1, 0.2, 0.5, 1.0, 2.0, 5.0, 10.0)


def drive_to_play(game):
    for _ in range(500):
        if game.phase == "play":
            return True
        seat = game.acting_seat()
        if seat is None:
            return False
        if game.phase in ("bid_initial", "bid_extra"):
            game.submit_bid(seat, rule_ai.choose_bid(game, seat))
        elif game.phase in ("bury_initial", "bury_extra"):
            game.submit_bury(seat, rule_ai.choose_bury(game, seat))
        else:
            return False
    return True


def make_positions(count: int):
    """取若干中盘局面（剩 8/12/16 墩）。"""
    out = []
    seed = 500000
    while len(out) < count:
        game = TractorGame(seed)
        game.start_match()
        seed += 17
        if not drive_to_play(game):
            continue
        state = FastState.from_game(game)
        for stop in (32, 48, 64):
            while sum(len(state.hands[s]) for s in range(4)) > stop:
                if state.is_terminal():
                    break
                seat = state.current_player
                mv = rule_ai.choose_play(game, seat)
                if game.trick is None or game.trick.lead is None:
                    game.play_lead(seat, mv)
                else:
                    game.play_follow(seat, mv)
                state.play(seat, mv)
            if state.is_terminal():
                continue
            out.append(state.clone())
            if len(out) >= count:
                break
    return out[:count]


def main():
    count = int(sys.argv[1]) if len(sys.argv) > 1 else 20
    model = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                         "..", "models", "value_v4.json")
    value_net.load_active(model)

    positions = make_positions(count)
    print("=" * 74)
    print("收敛探针：%d 个中盘局面，预算 %s" % (len(positions), list(BUDGETS)))
    print("=" * 74)

    stable_at = []          # 决策从多小的预算开始就不再变
    drift = []              # 0.1s -> 10s 的根估值变化（相对 10s 的幅度）
    changed = 0

    for i, pos in enumerate(positions):
        seat = pos.current_player
        world = determinize(pos, seat, random.Random(777 + i), tracker=None)
        moves, values, nodes = [], [], []
        for b in BUDGETS:
            s = Searcher(depth=40, time_limit=b, node_limit=10 ** 7,
                         eval_kind="value")
            mv, val = s.choose(world.clone(), seat)
            moves.append(None if mv is None else tuple(sorted(c.short for c in mv)))
            values.append(val if val is not None else float("nan"))
            nodes.append(s.nodes)

        # 决策稳定点：从最后一个预算往回找，第一次和最深层不一致的位置
        deep = moves[-1]
        st = BUDGETS[-1]
        for b, mv in zip(BUDGETS, moves):
            if mv == deep:
                st = b
                break
        stable_at.append(st)
        if moves[0] != deep:
            changed += 1
        v0, vdeep = values[1], values[-1]
        drift.append(abs(vdeep - v0) / (abs(vdeep) + 1e-6))

        print("  局面%2d 剩%2d墩 节点 %s  0.1s->10s 估值 %.1f -> %.1f"
              % (i, len(pos.hands[seat]), "/".join(str(n) for n in nodes),
                 v0, vdeep))

    print("-" * 74)
    import statistics as st_
    print("决策稳定所需预算：中位数 %.2f 秒，均值 %.2f 秒"
          % (st_.median(stable_at), st_.mean(stable_at)))
    print("  在 0.1 秒就已经选对最终决策的局面：%d/%d"
          % (sum(1 for b in stable_at if b <= 0.1), len(stable_at)))
    print("  0.1s 与 10s 选出不同走法的局面：%d/%d（50 倍预算换来 %.0f%% 的决策改变）"
          % (changed, len(positions), 100.0 * changed / len(positions)))
    print("根估值 0.1s -> 10s 的相对变化：中位数 %.1f%%"
          % (100.0 * st_.median(drift)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
