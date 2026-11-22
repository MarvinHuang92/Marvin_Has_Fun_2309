# -*- coding: utf-8 -*-
"""行为探针 v5：领出时会不会把牌送到"已知缺门"的对手嘴里。

优势网络的状态特征是**按队**的缺门标记（`_features_team` 只到队一级），
分不清是哪个对手缺门；而记牌器里是有按座位的缺门信息的。
所以很可能出现"明知某家缺这门还领这门，被毙"的情况。

跑法：python scripts/probe_behavior2.py 50
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from tractor.ai_select import AiEngine  # noqa: E402
from tractor.engine import TractorGame  # noqa: E402
from tractor.fast_state import FastState  # noqa: E402


def probe(kind, deals):
    ai = AiEngine(kind)
    st = {"lead_n": 0, "into_void_n": 0, "into_void_trump_n": 0}

    for d in range(deals):
        game = TractorGame(620000 + d)
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
        tracker = getattr(ai._brain, "tracker", None)
        for _ in range(400):
            if state.is_terminal():
                break
            seat = state.current_player
            is_lead = not state.plays
            cards = ai.play(game, seat)
            lead = game.trick.lead if (game.trick and game.trick.lead) else None

            if is_lead and tracker is not None and cards:
                # 领出的这门
                from tractor.cards import is_trump as _it
                if _it(cards[0], state.level, state.trump_suit):
                    suit_kind = "T"
                else:
                    suit_kind = cards[0].suit
                st["lead_n"] += 1
                my_team = state.team(seat)
                hit = False
                hit_trump = False
                for other in range(4):
                    if state.team(other) == my_team:
                        continue
                    if tracker.is_void(other, suit_kind):
                        hit = True
                        # 他还有没有主牌
                        if any(_it(c, state.level, state.trump_suit)
                               for c in state.hands[other]):
                            hit_trump = True
                if hit:
                    st["into_void_n"] += 1
                if hit_trump:
                    st["into_void_trump_n"] += 1

            if lead is not None:
                game.play_follow(seat, cards)
            else:
                game.play_lead(seat, cards)
            ai.observe(game, seat, cards, lead)
            state.play(seat, cards)
    return st


def main():
    deals = int(sys.argv[1]) if len(sys.argv) > 1 else 50
    print("=" * 70)
    print("行为探针 v5：领出时是否送到已知缺门的对手嘴里（%d 局）" % deals)
    print("=" * 70)
    for kind in ("heuristic", "adv", "rule"):
        s = probe(kind, deals)
        n = max(1, s["lead_n"])
        print("%-10s 领出 %5d 次：领到对手已知缺门 %5d 次 = %5.1f%%"
              "（其中对手还有主牌 %5d 次 = %5.1f%%）"
              % (kind, s["lead_n"], s["into_void_n"],
                 100.0 * s["into_void_n"] / n,
                 s["into_void_trump_n"],
                 100.0 * s["into_void_trump_n"] / n))
    return 0


if __name__ == "__main__":
    sys.exit(main())
