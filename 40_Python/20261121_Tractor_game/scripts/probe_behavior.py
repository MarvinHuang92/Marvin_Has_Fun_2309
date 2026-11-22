# -*- coding: utf-8 -*-
"""行为探针 v4：找和"废牌"同类的其它行为漏洞。

量三件事（都是"明显不合理"的候选）：

1. **抢队友的牌**：队友已经赢着，我还出一张能盖过他的牌（除非我有明确理由）
2. **白毙**：本墩一分没有、对方赢着，我却用主牌毙（应该丢副牌）
3. **该兑现不兑现**：我领出、手里有确定最大的牌，却不出它

跑法::

    python scripts/probe_behavior.py 60
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from tractor.ai_select import AiEngine  # noqa: E402
from tractor.cards import is_trump  # noqa: E402
from tractor.engine import TractorGame  # noqa: E402
from tractor.fast_state import FastState  # noqa: E402
from tractor.moves import legal_moves  # noqa: E402
from tractor.rules import build_category  # noqa: E402


def card_power(state, c):
    if is_trump(c, state.level, state.trump_suit):
        cat = build_category(state.level, state.trump_suit, None)
    else:
        cat = build_category(state.level, state.trump_suit, c.suit)
    return cat.power_of(c) or 0


def probe(kind, deals):
    ai = AiEngine(kind)
    st = {"dec": 0,
          "partner_win_n": 0, "overtake_n": 0, "overtake_pow": 0,
          "void_zero_n": 0, "ruff_zero_n": 0, "ruff_zero_pow": 0}

    for d in range(deals):
        game = TractorGame(610000 + d)
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
            lead = game.trick.lead if (game.trick and game.trick.lead) else None

            cards = ai.play(game, seat)
            st["dec"] += 1

            if state.plays:
                winner = state.winner_so_far()
                lead_cat = state.lead.category
                cur = 0
                if winner is not None:
                    for s_, played in state.plays:
                        for c in played:
                            cur = max(cur, lead_cat.power_of(c) or 0)
                my_best = max((lead_cat.power_of(c) or 0) for c in cards)

                # 1) 队友赢着，我这手盖过了他
                if winner is not None and state.team(winner) == my_team and winner != seat:
                    if my_best > cur:
                        st["partner_win_n"] += 1
                        st["overtake_n"] += 1
                        st["overtake_pow"] += my_best - cur
                    else:
                        st["partner_win_n"] += 1

                # 2) 本墩没分、对方赢着、我缺门却用主牌毙
                if (winner is not None and state.team(winner) != my_team
                        and state.points_on_table() == 0
                        and not lead_cat.is_trump):
                    hand_cat = [c for c in state.hands[seat] if lead_cat.contains(c)]
                    if not hand_cat:                      # 缺门，可以选择毙或垫
                        st["void_zero_n"] += 1
                        if all(is_trump(c, state.level, state.trump_suit) for c in cards):
                            st["ruff_zero_n"] += 1
                            st["ruff_zero_pow"] += sum(card_power(state, c) for c in cards)

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
    print("行为探针 v4：%d 局" % deals)
    print("=" * 72)
    for kind in ("heuristic", "adv", "rule"):
        s = probe(kind, deals)
        pw = max(1, s["partner_win_n"])
        vz = max(1, s["void_zero_n"])
        print("%-10s（%d 个决策）" % (kind, s["dec"]))
        print("   队友赢着时我还盖过他：%5d/%5d = %5.1f%%（平均多花牌力 %.1f）"
              % (s["overtake_n"], s["partner_win_n"],
                 100.0 * s["overtake_n"] / pw, s["overtake_pow"] / max(1, s["overtake_n"])))
        print("   零分墩且缺门时白毙主牌：%5d/%5d = %5.1f%%（平均牌力 %.0f）"
              % (s["ruff_zero_n"], s["void_zero_n"],
                 100.0 * s["ruff_zero_n"] / vz,
                 s["ruff_zero_pow"] / max(1, s["ruff_zero_n"])))
    return 0


if __name__ == "__main__":
    sys.exit(main())
