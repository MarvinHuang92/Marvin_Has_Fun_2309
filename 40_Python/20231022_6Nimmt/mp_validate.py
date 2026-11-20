# -*- coding: utf-8 -*-
"""在 5 人局里配对比较两个模型（或两套搜索参数）

同一局里 A、B 同时上桌（座位轮换、对手一样、牌局一样），所以是**配对比较**，
比"各打各的副本"灵敏得多。

用法：
    python mp_validate.py model_a.pth model_b.pth [局数] [--mode hybrid|scorepolicy]
    # 搜索参数也可以各给各的：
    python mp_validate.py model_a.pth model_b.pth 800 --a-m 24 --b-m 48
    python mp_validate.py model_a.pth model_b.pth 800 --a-k 3 --b-k 6
    python mp_validate.py model_a.pth model_b.pth 800 --a-crit diff --b-crit max
"""

import argparse
import contextlib
import io
import random
import sys
import time

import game_6nimmt as g

N = 5
BASE = ["human", "advanced_ai", "A", "B", "simple_ai"]


def make_smallest(p):
    def choose(game, deck):
        return p.handCards[0], 0, [{"reward": 0.0}] * len(p.handCards)
    return choose


def play_one(roster, models, params, seed, mode="hybrid"):
    players = [g.Player("P%d" % (i + 1)) for i in range(N)]
    game = g.Game(N, 10)
    game.playerList = players

    random.seed(seed)
    deck = g.CardDeck(players=N)
    random.shuffle(deck)
    for p in players:
        for _ in range(10):
            p.handCards.append(deck.pop(0))
    for i in range(4):
        game.table[i][0] = deck.pop(0)
    game.played_cards = [game.table[i][0].value for i in range(4)]
    game.played_bullheads = sum(game.table[i][0].bullheads for i in range(4))
    game.deck_total_bullheads = sum(c.bullheads for c in deck.shadow)

    for p, t in zip(players, roster):
        if t == "human":
            p.intellegence = "human"
            p.handCards.sort()
            p.chooseCardToPlay = make_smallest(p)
            p.chooseRowWhenSmallest = lambda gp, c: 1
        elif t in ("A", "B"):
            p.intellegence = mode          # hybrid（剪枝+搜索）或 scorepolicy（纯网络）
            p.NN_model = models[t]
            p.rollout_count = params[t]["m"]
            p.hybrid_k = params[t]["k"]
            p.search_criterion = params[t]["crit"]
            p.opp_teacher = (params[t]["opp"] == "teacher")
            p.screen_m = params[t]["screen"]
            p.search_depth = 0
        else:
            p.intellegence = t

    for rnd in range(10):
        game.left_round = 9 - rnd
        game.stash = []
        for p in players:
            p.playCard(game, deck)
        game.arrangeCard()
        game.stash = []
        for p in players:
            p.showPenaltyCards()
    return [p.bullheads for p in players]


def mean_ci(vals):
    n = len(vals)
    m = sum(vals) / n
    if n < 2:
        return m, 0.0
    sd = (sum((v - m) ** 2 for v in vals) / (n - 1)) ** 0.5
    return m, 1.96 * sd / (n ** 0.5)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("model_a")
    ap.add_argument("model_b")
    ap.add_argument("games", nargs="?", type=int, default=400)
    ap.add_argument("--mode", default="hybrid")
    ap.add_argument("--a-m", type=int, default=24)
    ap.add_argument("--b-m", type=int, default=24)
    ap.add_argument("--a-k", type=int, default=3)
    ap.add_argument("--b-k", type=int, default=3)
    ap.add_argument("--a-crit", default="diff")
    ap.add_argument("--b-crit", default="diff")
    ap.add_argument("--a-opp", default="random")   # rollout 里对手的出牌策略
    ap.add_argument("--b-opp", default="random")
    ap.add_argument("--a-screen", type=int, default=0)   # 两阶段粗筛次数（0=关闭）
    ap.add_argument("--b-screen", type=int, default=0)
    args = ap.parse_args()

    g.extra_feature_mode = "teacher_scores"
    g.normalize_state = False
    g.policy_sample = False
    with contextlib.redirect_stdout(io.StringIO()):
        models = {"A": g.load_model(args.model_a), "B": g.load_model(args.model_b)}
    params = {
        "A": {"m": args.a_m, "k": args.a_k, "crit": args.a_crit, "opp": args.a_opp,
              "screen": args.a_screen},
        "B": {"m": args.b_m, "k": args.b_k, "crit": args.b_crit, "opp": args.b_opp,
              "screen": args.b_screen},
    }

    a_pts, b_pts, diffs, a_first, b_first = [], [], [], 0, 0
    t0 = time.time()
    with contextlib.redirect_stdout(io.StringIO()):
        for i in range(args.games):
            off = i % N
            roster = BASE[off:] + BASE[:off]
            bull = play_one(roster, models, params, 960000 + i, args.mode)
            ia, ib = roster.index("A"), roster.index("B")
            pa, pb = bull[ia], bull[ib]
            a_pts.append(pa)
            b_pts.append(pb)
            diffs.append(pa - pb)
            if pa == min(bull):
                a_first += 1
            if pb == min(bull):
                b_first += 1
            if (i + 1) % 200 == 0:
                print("  ... %d/%d 局（%.0fs）" % (i + 1, args.games, time.time() - t0),
                      file=sys.stderr)

    ma, ca = mean_ci(a_pts)
    mb, cb = mean_ci(b_pts)
    md, cd = mean_ci(diffs)
    wins = sum(1 for d in diffs if d < 0)
    ties = sum(1 for d in diffs if d == 0)
    print("5 人局配对比较（%s，%d 局）" % (args.mode, args.games))
    print("  A: %s  m=%d k=%d crit=%s opp=%s screen=%d"
          % (args.model_a, args.a_m, args.a_k, args.a_crit, args.a_opp, args.a_screen))
    print("  B: %s  m=%d k=%d crit=%s opp=%s screen=%d"
          % (args.model_b, args.b_m, args.b_k, args.b_crit, args.b_opp, args.b_screen))
    print("  A 平均罚分 %6.2f ±%.2f      B 平均罚分 %6.2f ±%.2f" % (ma, ca, mb, cb))
    print("  配对差 (A−B) %+.2f ±%.2f   -> %s" % (
        md, cd, "A 更好" if md + cd < 0 else ("B 更好" if md - cd > 0 else "打平（区间跨 0）")))
    print("  逐局胜负：A 赢 %d、平 %d、B 赢 %d（%.1f%% / %.1f%%）"
          % (wins, ties, args.games - wins - ties,
             100.0 * wins / args.games, 100.0 * (args.games - wins - ties) / args.games))
    print("  拿全场第一的次数：A %d、B %d" % (a_first, b_first))
    return 0


if __name__ == "__main__":
    sys.exit(main())
