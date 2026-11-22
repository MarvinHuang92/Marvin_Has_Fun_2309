# -*- coding: utf-8 -*-
"""量一下三种估价模型的单次开销（搜索节点里的热路径）。"""
import os
import random
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from tractor import ai as rule_ai  # noqa: E402
from tractor.engine import TractorGame  # noqa: E402
from tractor.fast_state import FastState  # noqa: E402
from tractor.search import evaluate  # noqa: E402
from tractor import value_net  # noqa: E402


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


game = TractorGame(31415)
game.start_match()
drive_to_play(game)
state = FastState.from_game(game)
while sum(len(state.hands[s]) for s in range(4)) > 32:
    seat = state.current_player
    mv = rule_ai.choose_play(game, seat)
    if game.trick is None or game.trick.lead is None:
        game.play_lead(seat, mv)
    else:
        game.play_follow(seat, mv)
    state.play(seat, mv)

net_path = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                        "..", "models", "value_v2.json")
value_net.load_active(net_path)

N = 3000
print("=" * 56)
print("单次估价的耗时（%d 次）" % N)
print("=" * 56)
for kind in ("control", "rank", "value"):
    t0 = time.perf_counter()
    for _ in range(N):
        evaluate(state, 0, kind)
    dt = (time.perf_counter() - t0) / N * 1e6
    print("  %-8s %7.1f 微秒/次" % (kind, dt))
