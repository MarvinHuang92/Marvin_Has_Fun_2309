# -*- coding: utf-8 -*-
"""按级数分桶：游戏本身平衡吗？AI 在每个级数下一样强吗？

两件事分开看：

1. **游戏平衡**：同一套 AI 自我对弈，看每个级数下闲家得分 / 庄家守住率。
   如果某个级数下闲家明显更容易拿分，说明是**规则本身**偏向闲家。
2. **AI 能力**：强 AI vs 弱 AI，看每个级数下的差距。
   如果某个级数下差距变小/变大，说明 AI 在该级数下更弱/更强。

跑法::

    python scripts/eval_by_level.py self 60      # 自我对弈，看游戏平衡
    python scripts/eval_by_level.py skill 60     # adv vs heuristic，看 AI 差距
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from tractor.ai_select import AiEngine  # noqa: E402
from tractor.engine import TractorGame  # noqa: E402
from tractor.fast_state import FastState  # noqa: E402
from tractor.rules import rank_label  # noqa: E402

LEVELS = list(range(2, 15))          # 2 3 ... 10 J Q K A


def play_one(seed, level, ai0, ai1, a_team: int = 0):
    game = TractorGame(seed)
    game.start_match()
    game.levels = {0: level, 1: level}
    game.start_deal()
    ai0.begin_deal(game)
    ai1.begin_deal(game)

    for _ in range(800):
        if game.phase == "play":
            break
        seat = game.acting_seat()
        if seat is None:
            return None
        ai = ai0 if game.team(seat) == a_team else ai1
        if game.phase in ("bid_initial", "bid_extra"):
            game.submit_bid(seat, ai.bid(game, seat))
        elif game.phase in ("bury_initial", "bury_extra"):
            cards = ai.bury(game, seat)
            ok, _ = game.submit_bury(seat, cards)
            if ok:
                ai.note_buried(seat, cards)
        else:
            return None
    if game.phase != "play":
        return None

    state = FastState.from_game(game)
    for _ in range(600):
        if state.is_terminal():
            break
        seat = state.current_player
        ai = ai0 if state.team(seat) == a_team else ai1
        lead = game.trick.lead if (game.trick and game.trick.lead) else None
        cards = ai.play(game, seat)
        ok, msg = (game.play_follow(seat, cards) if lead is not None
                   else game.play_lead(seat, cards))
        if not ok:
            return None
        ai.observe(game, seat, cards, lead)
        state.play(seat, cards)
    else:
        return None

    r = game.deal_result or {}
    zt = r.get("zhuang_team", 0)
    side = r.get("side", "zhuang")
    win_team = zt if side == "zhuang" else 1 - zt
    delta = r.get("delta", 0)
    # team0 视角的净增量（team0 = mode=="skill" 时的 adv）
    a_delta = delta if win_team == a_team else -delta
    return {"def_pts": game.defender_points, "decl_pts": game.declarer_points,
            "kind": r.get("kind", ""), "a_delta": a_delta,
            "defender_up": r.get("kind", "") == "闲家上台"}


def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else "self"
    per = int(sys.argv[2]) if len(sys.argv) > 2 else 60

    if mode == "skill":
        ai0, ai1 = AiEngine("adv"), AiEngine("heuristic")
        title = "adv（庄闲都它） vs heuristic"
    else:
        ai0 = ai1 = AiEngine("heuristic")
        title = "自我对弈（同一套 AI）"

    print("=" * 76)
    print("按级数分桶：%s，每级 %d 局" % (title, per))
    print("=" * 76)
    print("  %-4s %6s %10s %10s %8s %10s" %
          ("级牌", "局数", "闲家得分", "庄家得分", "闲家上台", "team0净增量"))
    rows = {}
    for lv in LEVELS:
        got = []
        for i in range(per):
            # 逐局交换阵营，消掉"team0 永远坐南北"的固定偏置
            swap = (i % 2 == 1)
            at = 1 if swap else 0
            r = play_one(700000 + i * 7 + lv, lv, ai0, ai1, at)
            if r is not None:
                got.append(r)
        if not got:
            continue
        n = len(got)
        dp = sum(r["def_pts"] for r in got) / n
        cp = sum(r["decl_pts"] for r in got) / n
        up = sum(1 for r in got if r["defender_up"]) / n * 100
        dl = sum(r["a_delta"] for r in got) / n
        rows[lv] = (n, dp, cp, up, dl)
        print("  %-4s %6d %10.1f %10.1f %7.0f%% %+8.2f"
              % (rank_label(lv), n, dp, cp, up, dl))

    print("-" * 76)
    # 按"是不是分牌"分组
    point_levels = [lv for lv in rows if lv in (5, 10, 13)]
    ace = [lv for lv in rows if lv == 14]
    other = [lv for lv in rows if lv not in (5, 10, 13, 14)]

    def avg(group, idx):
        vals = [rows[lv][idx] for lv in group]
        return sum(vals) / len(vals) if vals else 0.0

    for name, group in (("分牌级（5/10/K）", point_levels),
                        ("A 级", ace),
                        ("其它级", other)):
        if group:
            print("  %-14s 闲家得分 %6.1f   闲家上台 %5.1f%%   team0净增量 %+.2f"
                  % (name, avg(group, 1), avg(group, 3), avg(group, 4)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
