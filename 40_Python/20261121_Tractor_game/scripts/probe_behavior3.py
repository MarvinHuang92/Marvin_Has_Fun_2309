# -*- coding: utf-8 -*-
"""行为探针 v6：最后一个出牌、能赢这一墩、而且台面上有分 —— 却没赢。

这是最没有争议的错误：我打完这墩就结束了，只要盖过当前最大就能拿分，
没有任何"留牌"的理由。

跑法：python scripts/probe_behavior3.py 60
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from tractor.ai_select import AiEngine  # noqa: E402
from tractor.engine import TractorGame  # noqa: E402
from tractor.fast_state import FastState  # noqa: E402
from tractor.moves import legal_moves  # noqa: E402


def probe(kind, deals):
    ai = AiEngine(kind)
    st = {"last_n": 0, "could_win_pot_n": 0, "missed_n": 0, "missed_pts": 0}

    for d in range(deals):
        game = TractorGame(630000 + d)
        game.start_match()
        ai.begin_deal(game)
        for _ in range(600):
            if game.phase == "play":
                break
            seat = game.acting_seat()
            if seat is None:
                break
            if game.phase in ("bid_initial", "bid_extra"):
                game.submit_bid(seat, ai.bid(game, seat))
            elif game.phase in ("bury_initial", "bury_extra"):
                cards = ai.bury(game, seat)
                ok, _ = game.submit_bury(seat, cards)
                if ok:
                    ai.note_buried(seat, cards)
        if game.phase != "play":
            continue

        state = FastState.from_game(game)
        for _ in range(400):
            if state.is_terminal():
                break
            seat = state.current_player
            my_team = state.team(seat)
            is_last = len(state.plays) == 3
            pot = state.points_on_table() if state.plays else 0

            cards = ai.play(game, seat)
            lead = game.trick.lead if (game.trick and game.trick.lead) else None

            if is_last and pot > 0:
                st["last_n"] += 1
                # 我这一手能不能赢
                tmp = state.clone()
                ok, _, res = tmp.play(seat, cards)
                won = False
                if ok:
                    won = (res is not None and state.team(res.winner) == my_team)
                # 有没有别的合法牌能赢
                can = False
                for mv in legal_moves(state, seat):
                    t2 = state.clone()
                    ok2, _, r2 = t2.play(seat, mv)
                    if ok2 and r2 is not None and state.team(r2.winner) == my_team:
                        can = True
                        break
                if can:
                    st["could_win_pot_n"] += 1
                    if not won:
                        st["missed_n"] += 1
                        st["missed_pts"] += pot

            if lead is not None:
                game.play_follow(seat, cards)
            else:
                game.play_lead(seat, cards)
            ai.observe(game, seat, cards, lead)
            state.play(seat, cards)
    return st


def main():
    deals = int(sys.argv[1]) if len(sys.argv) > 1 else 60
    print("=" * 72)
    print("行为探针 v6：最后一手能赢有分的墩却没赢（%d 局）" % deals)
    print("=" * 72)
    for kind in ("heuristic", "adv", "rule"):
        s = probe(kind, deals)
        c = max(1, s["could_win_pot_n"])
        print("%-10s 有分且能赢 %5d 次：放过 %4d 次 = %5.1f%%，白丢 %d 分"
              % (kind, s["could_win_pot_n"], s["missed_n"],
                 100.0 * s["missed_n"] / c, s["missed_pts"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
