# -*- coding: utf-8 -*-
"""等级阶梯：5 人局（人类代打 + Lv0~Lv3）跑 N 局，看各自成绩

人类在 GUI 的 --selftest 里是这样打的（不是人操作，是脚本代打）：
    ask_card() 直接返回 0  ——  手牌开局排过序，所以永远是「最小那张」
    _human_row_choice() 返回 1 ——  被迫吃行时永远吃第 1 行
这个脚本完全复刻这套代打策略，所以数字和你在界面上看到的 selftest 同源。

为了公平，每局把 5 个策略在 5 个座位上轮换，避免「P1 的牌总是好一点」。

用法：
    python level_ladder.py            # 500 局
    python level_ladder.py 2000       # 2000 局
"""

import contextlib
import io
import random
import sys
import time

import game_6nimmt as engine

MODEL = "model_searchc_25k400_ts.pth"
HYBRID_M = 24
SEED0 = 950000
N_PLAYERS = 5

# 座位上的"策略"（human = selftest 里的代打：总出最小）
STRATS = ["human", "simple_ai", "advanced_ai", "scorepolicy", "hybrid"]
LABEL = {
    "human": "人类代打(总出最小)",
    "simple_ai": "Lv0 随机",
    "advanced_ai": "Lv1 启发式",
    "scorepolicy": "Lv2 神经网络",
    "hybrid": "Lv3 网络+搜索",
}


def make_smallest(player):
    """复刻 selftest：手牌升序，永远出第 0 张"""
    def choose(game, deck):
        return player.handCards[0], 0, [{"reward": 0.0}] * len(player.handCards)
    return choose


def play_one(roster, model, seed):
    players = [engine.Player("P%d" % (i + 1)) for i in range(N_PLAYERS)]
    game = engine.Game(N_PLAYERS, 10)
    game.playerList = players

    random.seed(seed)
    deck = engine.CardDeck(players=N_PLAYERS)
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
        p.intellegence = t if t != "human" else "human"
        if t == "human":
            p.handCards.sort()
            p.chooseCardToPlay = make_smallest(p)
            p.chooseRowWhenSmallest = lambda g, c: 1
        else:
            if t in ("scorepolicy", "hybrid"):
                p.NN_model = model
            p.rollout_count = HYBRID_M
            p.search_depth = 0

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


def main():
    n_games = int(sys.argv[1]) if len(sys.argv) > 1 else 500
    seed0 = int(sys.argv[2]) if len(sys.argv) > 2 else SEED0
    engine.extra_feature_mode = "teacher_scores"
    engine.normalize_state = False
    engine.policy_sample = False
    engine.HYBRID_TOP_K = 3
    engine.SEARCH_ROLLOUTS = 8

    with contextlib.redirect_stdout(io.StringIO()):
        model = engine.load_model(MODEL)

    stats = {s: {"pts": [], "rank": [], "first": 0, "last": 0} for s in STRATS}
    t0 = time.time()
    for g in range(n_games):
        off = g % N_PLAYERS
        roster = STRATS[off:] + STRATS[:off]        # 每局轮换座位
        bull = play_one(roster, model, seed0 + g)
        for i, t in enumerate(roster):
            mine = bull[i]
            rank = 1 + sum(1 for j, b in enumerate(bull) if j != i and b < mine)
            st = stats[t]
            st["pts"].append(mine)
            st["rank"].append(rank)
            if rank == 1:
                st["first"] += 1
            if rank == N_PLAYERS:
                st["last"] += 1
        if (g + 1) % 100 == 0:
            print("  ... %d/%d 局（%.0fs）" % (g + 1, n_games, time.time() - t0), file=sys.stderr)

    print("5 人局 × %d 局（每局座位轮换），用时 %.0fs" % (n_games, time.time() - t0))
    print()
    print("  %-20s %8s %8s %8s %8s" % ("策略", "平均罚分", "平均名次", "第一", "最后"))
    for s in STRATS:
        st = stats[s]
        n = len(st["pts"])
        print("  %-20s %8.2f %8.2f %7.1f%% %7.1f%%" % (
            LABEL[s], sum(st["pts"]) / n, sum(st["rank"]) / n,
            100.0 * st["first"] / n, 100.0 * st["last"] / n))
    print()

    hp = stats["human"]["pts"]
    hist = {}
    for v in hp:
        hist[v] = hist.get(v, 0) + 1
    print("人类代打（总出最小）的罚分分布（前 10 个值）：")
    for v in sorted(hist)[:10]:
        print("    %3d 分 : %5.1f%%  (%d 局)" % (v, 100.0 * hist[v] / len(hp), hist[v]))
    print("    <=2 分的比例: %.1f%%" % (100.0 * sum(1 for v in hp if v <= 2) / len(hp)))
    print("    拿第一的比例: %.1f%%" % (100.0 * stats["human"]["first"] / len(hp)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
