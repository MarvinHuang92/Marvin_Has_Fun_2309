# -*- coding: utf-8 -*-
"""安全检查：搜索里跳过合法性校验（validate=False）不能改变结果。

搜索用的动作全部来自 `moves.legal_moves*`，理论上合法；但"理论上"靠不住，
所以这里用同一局面分别跑 `validate=True` 和 `validate=False`，比较
「选出的动作」和「根节点估值」是否完全一致。
"""
from __future__ import annotations

import os
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
    checked = 0
    for d in range(6):
        game = TractorGame(4000 + d * 7)
        game.start_match()
        drive_to_play(game)
        state = FastState.from_game(game)
        # 打到剩 6 墩，逐墩检查
        while sum(len(state.hands[s]) for s in range(4)) > 24:
            seat = state.current_player
            mv = rule_ai.choose_play(game, seat)
            if game.trick is None or game.trick.lead is None:
                game.play_lead(seat, mv)
            else:
                game.play_follow(seat, mv)
            state.play(seat, mv)

        for _ in range(6):
            if state.is_terminal():
                break
            seat = state.current_player
            world = determinize(state, seat, random.Random(99 + checked))

            a = Searcher(depth=4, time_limit=5.0, node_limit=500000, validate=False)
            mv_a, val_a = a.choose(world.clone(), seat)
            b = Searcher(depth=4, time_limit=5.0, node_limit=500000, validate=True)
            mv_b, val_b = b.choose(world.clone(), seat)

            assert (mv_a is None) == (mv_b is None)
            if mv_a is not None:
                assert sorted(mv_a) == sorted(mv_b), (
                    "跳过校验改变了选出的动作：%s vs %s"
                    % ([c.label for c in mv_a], [c.label for c in mv_b]))
            assert abs(val_a - val_b) < 1e-6, "跳过校验改变了估值"
            checked += 1

            mv = mv_a
            if state.lead is None:
                ok, msg, _ = state.play(seat, mv)
            else:
                ok, msg, _ = state.play(seat, mv)
            if not ok:
                raise RuntimeError(msg)

    print("=" * 60)
    print("跳过合法性校验的一致性检查：%d 个决策，动作与估值完全一致 ✓" % checked)
    return 0


if __name__ == "__main__":
    sys.exit(main())
