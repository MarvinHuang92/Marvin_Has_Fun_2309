# -*- coding: utf-8 -*-
"""自对弈产生「优势」样本：A(s,a) = 这一手的实际结果 − V(s)。

和之前的价值网络数据（学"这局值多少分"）不同，这里学的是
**"这一手比平均水平好多少"** —— 把信用分配落在"决策"而不是"局面"上。

跑法::

    python scripts/selfplay_adv.py 4000 game_log/adv_train.csv models/value_v4.json
"""
from __future__ import annotations

import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from tractor import value_net  # noqa: E402
from tractor.ai_select import AiEngine  # noqa: E402
from tractor.engine import TractorGame  # noqa: E402
from tractor.fast_state import FastState  # noqa: E402


def play_one(seed, ai, net):
    game = TractorGame(seed)
    game.start_match()
    ai.begin_deal(game)

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

        cards = ai.play(game, seat)
        # 先记下"这个局面 + 这一手"，再出牌
        sf = value_net._features_team(state, team)
        af = value_net.action_features(state, seat, cards)
        rows.append((sf, af, team, state.points[zt], state.points[1 - zt]))

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

    final = {zt: game.declarer_points, 1 - zt: game.defender_points}
    out = []
    for sf, af, team, p_me, p_them in rows:
        r = (final[team] - p_me) - (final[1 - team] - p_them)
        v = net.predict_features(sf)
        out.append((sf, af, r - v, r))
    return out


def main():
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 4000
    out_path = sys.argv[2] if len(sys.argv) > 2 else "game_log/adv_train.csv"
    model = sys.argv[3] if len(sys.argv) > 3 else "models/value_v4.json"
    seed0 = int(sys.argv[4]) if len(sys.argv) > 4 else 930000

    net = value_net.ValueNet.load(model)
    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
    policy = sys.argv[5] if len(sys.argv) > 5 else "heuristic"
    if policy.startswith("adv:"):
        from tractor.ai_advantage import AdvantageAI

        adv_model = policy[4:]
        if not os.path.isabs(adv_model):
            adv_model = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                     "..", "models", adv_model)
        ai = AdvantageAI(adv_model, samples=4)
        print("用优势 AI 产数据：%s" % adv_model)
    else:
        ai = AiEngine("heuristic")

    t0 = time.time()
    written = 0
    with open(out_path, "w", encoding="utf-8") as f:
        for i in range(n):
            rows = play_one(seed0 + i, ai, net)
            for sf, af, a, r in rows:
                f.write(",".join("%.3f" % v for v in list(sf) + list(af)))
                f.write(",%.3f,%.3f\n" % (a, r))
                written += 1
            if (i + 1) % 500 == 0:
                print("  %d/%d 局，%d 条（%.0fs）"
                      % (i + 1, n, written, time.time() - t0), file=sys.stderr)
    print("完成：%d 局，%d 条 -> %s（%.0fs）"
          % (n, written, out_path, time.time() - t0))
    return 0


if __name__ == "__main__":
    sys.exit(main())
