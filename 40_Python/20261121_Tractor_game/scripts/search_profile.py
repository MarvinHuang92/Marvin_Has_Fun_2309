# -*- coding: utf-8 -*-
"""profile 搜索节点的耗时分布（开发用）。

跑法::

    python scripts/search_profile.py            # 默认 8 墩中盘、300ms 预算
    python scripts/search_profile.py 12 500     # 剩 12 墩、500ms
"""
from __future__ import annotations

import cProfile
import os
import pstats
import random
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from tractor import ai as rule_ai  # noqa: E402
from tractor.engine import TractorGame  # noqa: E402
from tractor.fast_state import FastState  # noqa: E402
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
    tricks = int(sys.argv[1]) if len(sys.argv) > 1 else 8
    budget_ms = int(sys.argv[2]) if len(sys.argv) > 2 else 300

    game = TractorGame(31415)
    game.start_match()
    drive_to_play(game)
    state = FastState.from_game(game)
    stop = tricks * 4
    while sum(len(state.hands[s]) for s in range(4)) > stop:
        seat = state.current_player
        mv = rule_ai.choose_play(game, seat)
        if game.trick is None or game.trick.lead is None:
            game.play_lead(seat, mv)
        else:
            game.play_follow(seat, mv)
        state.play(seat, mv)

    seat = state.current_player
    world = determinize(state, seat, random.Random(1))
    searcher = Searcher(depth=40, time_limit=budget_ms / 1000.0, node_limit=5000000)

    prof = cProfile.Profile()
    prof.enable()
    searcher.choose(world, seat)
    prof.disable()

    print("剩余 %d 墩  预算 %d ms  节点 %d  完成深度 %d"
          % (tricks, budget_ms, searcher.nodes, searcher.depth_done))
    pstats.Stats(prof).sort_stats("cumulative").print_stats(12)
    return 0


if __name__ == "__main__":
    sys.exit(main())
