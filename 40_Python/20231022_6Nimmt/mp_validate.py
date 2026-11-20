# -*- coding: utf-8 -*-
"""在 5 人局里配对比较两个模型

同一局里 A、B 同时上桌（座位轮换、对手一样、牌局一样），所以是**配对比较**，
比"各打各的副本"灵敏得多。

用法：
    python mp_validate.py model_a.pth model_b.pth [局数]
"""

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


def play_one(roster, models, seed, mode="hybrid"):
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
            p.intellegence = mode          # hybrid（网络剪枝+搜索）或 scorepolicy（纯网络）
            p.NN_model = models[t]
            p.rollout_count = 24
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
    path_a = sys.argv[1] if len(sys.argv) > 1 else "model_a.pth"
    path_b = sys.argv[2] if len(sys.argv) > 2 else "model_b.pth"
    games = int(sys.argv[3]) if len(sys.argv) > 3 else 400
    mode = sys.argv[4] if len(sys.argv) > 4 else "hybrid"

    g.extra_feature_mode = "teacher_scores"
    g.normalize_state = False
    g.policy_sample = False
    g.HYBRID_TOP_K = 3
    g.SEARCH_ROLLOUTS = 8
    with contextlib.redirect_stdout(io.StringIO()):
        models = {"A": g.load_model(path_a), "B": g.load_model(path_b)}

    a_pts, b_pts, diffs, a_first, b_first = [], [], [], 0, 0
    t0 = time.time()
    with contextlib.redirect_stdout(io.StringIO()):
        for i in range(games):
            off = i % N
            roster = BASE[off:] + BASE[:off]
            bull = play_one(roster, models, 960000 + i, mode)
            ia, ib = roster.index("A"), roster.index("B")
            pa, pb = bull[ia], bull[ib]
            a_pts.append(pa)
            b_pts.append(pb)
            diffs.append(pa - pb)
            # 谁是全场最少？
            if pa == min(bull):
                a_first += 1
            if pb == min(bull):
                b_first += 1
            if (i + 1) % 100 == 0:
                print("  ... %d/%d 局（%.0fs）" % (i + 1, games, time.time() - t0),
                      file=sys.stderr)

    ma, ca = mean_ci(a_pts)
    mb, cb = mean_ci(b_pts)
    md, cd = mean_ci(diffs)
    wins = sum(1 for d in diffs if d < 0)
    ties = sum(1 for d in diffs if d == 0)
    print("5 人局配对比较（%s）：A=%s  B=%s  （%d 局，座位轮换）"
          % (mode, path_a, path_b, games))
    print("  A 平均罚分 %6.2f ±%.2f      B 平均罚分 %6.2f ±%.2f" % (ma, ca, mb, cb))
    print("  配对差 (A−B) %+.2f ±%.2f   -> %s" % (
        md, cd, "A 更好" if md + cd < 0 else ("B 更好" if md - cd > 0 else "打平（区间跨 0）")))
    print("  逐局胜负：A 赢 %d、平 %d、B 赢 %d（%.1f%% / %.1f%%）"
          % (wins, ties, games - wins - ties,
             100.0 * wins / games, 100.0 * (games - wins - ties) / games))
    print("  拿全场第一的次数：A %d、B %d" % (a_first, b_first))
    return 0


if __name__ == "__main__":
    sys.exit(main())
