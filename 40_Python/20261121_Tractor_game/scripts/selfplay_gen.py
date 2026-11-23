# -*- coding: utf-8 -*-
"""自对弈产生「局面 → 这局最终净得分」的数据。

这是自对弈路线的第一步：**第一次用"真实结果"当标签**，
而不是手写启发式或搜索给的单步估值。

跑法::

    python scripts/selfplay_gen.py 1500 game_log/value_train.csv

每局产出约 100 条（每个决策点一条），标签是"从这个局面到我方局末"的净得分。
"""
from __future__ import annotations

import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from tractor.ai_select import AiEngine  # noqa: E402
from tractor.engine import TractorGame  # noqa: E402
from tractor.fast_state import FastState  # noqa: E402
from tractor.value_net import (state_features,  # noqa: E402
                               state_features_with_bottom)


def play_one(seed: int, ai: AiEngine, use_bottom: bool = False):
    """自对弈一局，返回 [(features, label)]。"""
    game = TractorGame(seed)
    game.start_match()
    ai.begin_deal(game)

    # 亮主 / 埋底
    for _ in range(600):
        if game.phase == "play":
            break
        seat = game.acting_seat()
        if seat is None:
            return []
        if game.phase in ("bid_initial", "bid_extra"):
            game.submit_bid(seat, ai.bid(game, seat))
        elif game.phase in ("bury_initial", "bury_extra"):
            cards = ai.bury(game, seat)
            ok, _ = game.submit_bury(seat, cards)
            if ok:
                ai.note_buried(seat, cards)
        else:
            return []

    state = FastState.from_game(game)
    zt = state.team(state.zhuang)
    rows = []

    for _ in range(400):
        if state.is_terminal():
            break
        seat = state.current_player
        team = state.team(seat)
        # **门控**：只有"我是最后埋底的人"时，底牌才是我的合法信息。
        # 其他人（包括一直没埋过的对手）一律传 None -> 那 9 维全 0。
        known = None
        if use_bottom:
            mine = getattr(ai, "_brain", None)
            mine = getattr(mine, "_my_buried", {}).get(seat) if mine else None
            if mine and state.last_burier == seat:
                known = list(mine)
        feats = (state_features_with_bottom(state, team, known)
                 if use_bottom else state_features(state, team))
        rows.append((feats,
                     team,
                     state.points[zt],
                     state.points[1 - zt]))

        cards = ai.play(game, seat)
        lead = game.trick.lead if (game.trick and game.trick.lead) else None
        if lead is not None:
            ok, msg = game.play_follow(seat, cards)
        else:
            ok, msg = game.play_lead(seat, cards)
        if not ok:
            return []
        ai.observe(game, seat, cards, lead)
        if not state.play(seat, cards)[0]:
            return []
    else:
        return []

    # 局末（含抠底）的真实比分
    final = {zt: game.declarer_points, 1 - zt: game.defender_points}
    out = []
    for feats, team, p_me, p_them in rows:
        delta = ((final[team] - p_me) - (final[1 - team] - p_them))
        out.append((feats, delta))
    return out


def main():
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 1500
    out_path = sys.argv[2] if len(sys.argv) > 2 else "game_log/value_train.csv"
    seed0 = int(sys.argv[3]) if len(sys.argv) > 3 else 880000
    # 第 4 个参数传 bottom 时，特征里带上"门控的底牌"9 维（共 142 维）
    use_bottom = len(sys.argv) > 4 and sys.argv[4] == "bottom"

    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
    ai = AiEngine("heuristic")

    t0 = time.time()
    written = 0
    with open(out_path, "w", encoding="utf-8") as f:
        for i in range(n):
            rows = play_one(seed0 + i, ai, use_bottom)
            for feats, label in rows:
                f.write(",".join("%.3f" % v for v in feats))
                f.write(",%.1f\n" % label)
                written += 1
            if (i + 1) % 200 == 0:
                print("  %d/%d 局，%d 条（%.0fs）"
                      % (i + 1, n, written, time.time() - t0), file=sys.stderr)
    print("完成：%d 局，%d 条样本（%s）-> %s（%.0fs）"
          % (n, written, "带门控底牌 142 维" if use_bottom else "133 维",
             out_path, time.time() - t0))
    return 0


if __name__ == "__main__":
    sys.exit(main())
