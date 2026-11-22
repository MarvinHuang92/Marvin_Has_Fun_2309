# -*- coding: utf-8 -*-
"""行为探针 v3：量任何一档 AI 在"本墩已定"时浪费了多少。

用法::

    python scripts/probe_waste2.py                      # 启发式 + 优势网络 + 规则
    python scripts/probe_waste2.py 80                   # 只跑 80 局
"""
from __future__ import annotations

import os
import sys
from collections import Counter

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


def points_of(cards):
    return sum(5 if c.rank == 5 else (10 if c.rank in (10, 13) else 0) for c in cards)


def pairs_broken(state, seat, cards):
    hand = state.hands[seat]
    before = Counter(c.rank for c in hand)
    after = Counter(c.rank for c in hand if c not in cards)
    return sum(1 for r, n in before.items() if n >= 2 and after.get(r, 0) < 2)


def probe(kind, deals):
    ai = AiEngine(kind)
    st = {"lost_n": 0, "lost_waste": 0.0, "lost_combo": 0.0, "lost_pts": 0.0,
          "lost_brk": 0, "wp_n": 0, "wp_waste": 0.0, "wp_combo": 0.0,
          "wp_pts": 0.0, "all": 0}

    for d in range(deals):
        game = TractorGame(600000 + d)
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
            winner = state.winner_so_far() if state.plays else None
            lead = game.trick.lead if (game.trick and game.trick.lead) else None

            cards = ai.play(game, seat)
            st["all"] += 1

            if winner is not None:
                cands = legal_moves(state, seat)
                can_win = False
                for mv in cands:
                    tmp = state.clone()
                    ok, _, res = tmp.play(seat, mv)
                    if ok and (res is not None and state.team(res.winner) == my_team):
                        can_win = True
                        break
                    if ok and res is None and tmp.winner_so_far() == seat:
                        can_win = True
                        break
                if not can_win:
                    my_pow = sum(card_power(state, c) for c in cards)
                    min_pow = min(sum(card_power(state, c) for c in mv) for mv in cands)
                    # 综合指标：牌力 + 9x拆对（拆对本身就有代价，不算"浪费"）
                    def combo(mv):
                        return (sum(card_power(state, c) for c in mv)
                                + 9.0 * pairs_broken(state, seat, mv))
                    my_combo = combo(cards)
                    min_combo = min(combo(mv) for mv in cands)
                    if state.team(winner) != my_team:
                        st["lost_n"] += 1
                        st["lost_waste"] += my_pow - min_pow
                        st["lost_combo"] += my_combo - min_combo
                        st["lost_pts"] += points_of(cards)
                        st["lost_brk"] += pairs_broken(state, seat, cards)
                    else:
                        st["wp_n"] += 1
                        st["wp_waste"] += my_pow - min_pow
                        st["wp_combo"] += my_combo - min_combo
                        st["wp_pts"] += points_of(cards)

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
    print("行为探针 v3：%d 局（waste = 比最便宜合法选项多用的牌力）" % deals)
    print("=" * 72)
    for kind in ("heuristic", "adv", "rule"):
        s = probe(kind, deals)
        n = max(1, s["lost_n"])
        m = max(1, s["wp_n"])
        print("%-10s（共 %d 个决策）" % (kind, s["all"]))
        print("   本墩已输 %5d 次：浪费牌力 %5.1f（综合 %5.1f），送分 %.2f，拆对 %.2f"
              % (s["lost_n"], s["lost_waste"] / n, s["lost_combo"] / n,
                 s["lost_pts"] / n, s["lost_brk"] / n))
        print("   队友已赢 %5d 次：浪费牌力 %5.1f（综合 %5.1f），送分 %.2f"
              % (s["wp_n"], s["wp_waste"] / m, s["wp_combo"] / m, s["wp_pts"] / m))
    return 0


if __name__ == "__main__":
    sys.exit(main())
