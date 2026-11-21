# -*- coding: utf-8 -*-
"""诊断：限时搜索实际能搜多深、每步花多久。"""
from __future__ import annotations

import os
import random
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from tractor import ai as rule_ai  # noqa: E402
from tractor.ai_heuristic import HeuristicAI  # noqa: E402
from tractor.dds import DoubleDummySolver  # noqa: E402
from tractor.engine import TractorGame  # noqa: E402
from tractor.fast_state import FastState  # noqa: E402
from tractor.memory import CardTracker  # noqa: E402
from tractor.search import Searcher, determinize  # noqa: E402


def drive_to_play(game):
    for _ in range(500):
        if game.phase == "play":
            return
        seat = game.acting_seat()
        if seat is None:
            return
        if game.phase in ("bid_initial", "bid_extra"):
            game.submit_bid(seat, rule_ai.choose_bid(game, seat))
        elif game.phase in ("bury_initial", "bury_extra"):
            game.submit_bury(seat, rule_ai.choose_bury(game, seat))
        else:
            return


def main():
    rng = random.Random(1)
    print("=" * 66)
    print("限时搜索能搜多深（各预算下、各阶段的实测）")
    print("=" * 66)
    print("  %8s %8s %8s %8s" % ("时间预算", "阶段", "搜到深度", "用时ms"))
    for budget in (0.02, 0.05, 0.1, 0.2):
        depths, elapsed = [], []
        for d in range(4):
            game = TractorGame(9000 + d)
            game.start_match()
            drive_to_play(game)
            state = FastState.from_game(game)
            ai = HeuristicAI()
            tracker = CardTracker(game.level, game.trump_suit, my_seat=-1)
            # 打到还剩 8 墩（中盘）
            while sum(len(state.hands[s]) for s in range(4)) > 32:
                seat = state.current_player
                lead = state.lead
                mv = ai.choose(state, seat)
                state.play(seat, mv)
                tracker.observe_play(seat, mv, lead)
            seat = state.current_player
            world = determinize(state, seat, rng)
            searcher = Searcher(depth=40, time_limit=budget, node_limit=2000000)
            t0 = time.perf_counter()
            searcher.choose(world, seat)
            dt = time.perf_counter() - t0
            depths.append(searcher.depth_done)
            elapsed.append(dt * 1000)
        print("  %8.2f %8s %8.1f %8.0f" % (
            budget, "8墩", sum(depths) / len(depths), sum(elapsed) / len(elapsed)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
