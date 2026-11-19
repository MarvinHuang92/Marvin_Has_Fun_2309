# -*- coding: utf-8 -*-
"""小状态版 6 Nimmt! 精确求解器（值迭代 / 动态规划）

只改四个参数，规则与 2023 年的 game_6nimmt.py 完全一致：
    牌堆 1~12（2 人 × 5 张手牌 + 2 张底牌）
    桌面 2 行 × 3 列（放第 4 张时吃行）
    每人 5 张手牌，每局 5 回合
牛头：5→2，10→3，11→5，其余 1（与 cardBullheads 一致）

两个目标函数（对应优化记录第十二轮发现的 self / diff）：
    V  : 最小化「自己的期望罚分」
    VD : 最小化「自己 − 对手 的期望罚分差」（更接近"赢"）

用法：
    python small_game_solver.py              # 完整报告
    python small_game_solver.py deals 40     # 指定聚合用的牌局数
    python verify_small_game.py              # 与旧引擎做规则对照
"""

import random
import sys
from functools import lru_cache
from math import comb

# ---------------- 规则参数（全部可调） ----------------
N_PLAYERS = 2
HAND = 5                 # 每人手牌数 = 回合数
CAP = 3                  # 每行最多几张；放第 CAP+1 张时吃行
N_ROWS = 2               # 桌面行数
DECK = N_PLAYERS * HAND + N_ROWS    # 12

ME, OPP = 0, 1
SEEN = set()             # 记录算过哪些局面，用来报"可达局面数"


def bullheads(v):
    """与 game_6nimmt.cardBullheads 完全一致（判断顺序也一致：55 最先）"""
    if v == 55:
        return 7
    if v % 10 == 5:
        return 2
    if v % 10 == 0:
        return 3
    if v % 11 == 0:
        return 5
    return 1


BH = {v: bullheads(v) for v in range(1, DECK + 1)}
BH_TOTAL = sum(BH.values())          # 1..12 的总牛头 = 19


def row_bh(row, table=None):
    table = BH if table is None else table
    return sum(table[c] for c in row)


def canon(rows):
    """行与行可以交换，排序后同一个局面只有一种表示（状态数差不多减半）"""
    return tuple(sorted(tuple(r) for r in rows))


def without(cards, x):
    return tuple(v for v in cards if v != x)


# ---------------- 单张牌的放置规则 ----------------
def place_options(rows, card, cap=None, table=None):
    """把一张牌按规则处理，返回 (kind, options)

    kind == "place"  : options = [(new_rows, 0)]                安全接到行尾
    kind == "take"   : options = [(new_rows, taken)]            该行已满，被迫吃
    kind == "choose" : options = [(new_rows, taken), ...]       比所有行尾都小，出牌者自选吃哪行

    判定顺序与 game_6nimmt.placeCard 一致：
      1. 差值全为负        -> 出牌者选一行吃掉（这张牌成为该行新的第一张）
      2. 否则取最小正差值那行
      3. 该行已有 cap 张   -> 吃
    """
    cap = CAP if cap is None else cap
    table = BH if table is None else table
    ends = [r[-1] for r in rows]
    diffs = [card - e for e in ends]
    if max(diffs) < 0:
        opts = []
        for i, r in enumerate(rows):
            nr = list(rows)
            nr[i] = (card,)
            opts.append((canon(nr), row_bh(r, table)))
        return "choose", opts
    pos = [i for i, d in enumerate(diffs) if d > 0]
    if not pos:                      # 正常不会发生：牌面互不相同
        raise ValueError("坏局面 rows=%r card=%r" % (rows, card))
    target = min(pos, key=lambda i: diffs[i])
    if len(rows[target]) >= cap:
        nr = list(rows)
        nr[target] = (card,)
        return "take", [(canon(nr), row_bh(rows[target], table))]
    nr = list(rows)
    nr[target] = tuple(rows[target]) + (card,)
    return "place", [(canon(nr), 0)]


# ---------------- 一回合的结算（带概率，给精确评估用） ----------------
def resolve_round(rows, plays, choose_me, choose_opp):
    """plays: ((card, owner), ...)，已按牌面升序

    返回 [(rows_after, d_me, d_opp, prob)]：本回合结束后的所有可能。
    唯一的随机/决策源是「比所有行尾都小、要自己选吃哪行」。
    """
    if not plays:
        return [(rows, 0, 0, 1.0)]
    (card, owner), rest = plays[0], plays[1:]
    kind, opts = place_options(rows, card)
    if kind == "place":
        return resolve_round(opts[0][0], rest, choose_me, choose_opp)
    if kind == "take":
        r2, taken = opts[0]
        out = []
        for (r3, dm, do, p) in resolve_round(r2, rest, choose_me, choose_opp):
            out.append((r3, dm + (taken if owner == ME else 0),
                        do + (taken if owner == OPP else 0), p))
        return out
    # kind == "choose"
    choose = choose_me if owner == ME else choose_opp
    out = []
    for idx, prob in choose(rows, opts, owner, rest):
        if prob <= 0.0:
            continue
        r2, taken = opts[idx]
        for (r3, dm, do, p) in resolve_round(r2, rest, choose_me, choose_opp):
            out.append((r3, dm + (taken if owner == ME else 0),
                        do + (taken if owner == OPP else 0), p * prob))
    return out


# ---------------- 值迭代 ----------------
def _bellman(rows, me, opp, vf, diff):
    """V(s) = min_a (1/|O|) * sum_b resolve(s, a, b)

    5 回合是有限期，按回合倒推就是精确解（不需要迭代到收敛）。
    """
    if not me:
        return 0.0
    n = len(opp)
    best = float("inf")
    for a in me:
        me2 = without(me, a)
        s = 0.0
        for b in opp:
            opp2 = without(opp, b)
            plays = ((a, ME), (b, OPP)) if a < b else ((b, OPP), (a, ME))
            s += _resolve_value(rows, plays, me2, opp2, ME, vf, diff)
        val = s / n
        if val < best:
            best = val
    return best


def _delta(owner, taken, own, diff):
    """这一手吃到的牛头记到「我方价值」上是多少

    diff=False（只算自己的罚分）：只有 own 吃才算
    diff=True （算罚分差）       ：own 吃加分、对手吃减分
    """
    if owner == own:
        return taken
    return -taken if diff else 0


def _resolve_value(rows, plays, own_after, other_after, own, vf, diff):
    """一回合结算的值：own 这方最优出牌，另一方随机。
    own 用来把「谁吃」翻译成「谁的罚分」，同一套代码既能算我方也能算对手。
    """
    if not plays:
        return vf(rows, own_after, other_after)
    (card, owner), rest = plays[0], plays[1:]
    kind, opts = place_options(rows, card)
    if kind == "place":
        return _resolve_value(opts[0][0], rest, own_after, other_after, own, vf, diff)
    if kind == "take":
        r2, taken = opts[0]
        return (_delta(owner, taken, own, diff)
                + _resolve_value(r2, rest, own_after, other_after, own, vf, diff))
    if owner == own:                       # 自己挑最省的一行
        return min(_delta(owner, taken, own, diff)
                   + _resolve_value(r2, rest, own_after, other_after, own, vf, diff)
                   for r2, taken in opts)
    # 随机对手：每行等概率；他吃的牛头是否影响我，取决于目标函数
    return sum(_delta(owner, taken, own, diff)
               + _resolve_value(r2, rest, own_after, other_after, own, vf, diff)
               for r2, taken in opts) / len(opts)


@lru_cache(maxsize=None)
def V(rows, me, opp):
    """目标 A：最小化自己的期望罚分"""
    SEEN.add((rows, me, opp))
    return _bellman(rows, me, opp, V, False)


@lru_cache(maxsize=None)
def VD(rows, me, opp):
    """目标 B：最小化「自己 − 对手」的期望罚分差"""
    SEEN.add((rows, me, opp))
    return _bellman(rows, me, opp, VD, True)


# ---------------- 策略 ----------------
# 策略 = 两个函数，全部以「用这个策略的人」为第一视角：
#   card(rows, own, other)                       -> [(card, prob)]
#   row(rows, opts, rest, own_after, other_after, own) -> [(idx, prob)]

def make_opt_policy(diff):
    vf = VD if diff else V

    def card(rows, own, other):
        best_card, best_val = None, float("inf")
        for a in own:
            own2 = without(own, a)
            s = 0.0
            for b in other:
                other2 = without(other, b)
                plays = ((a, ME), (b, OPP)) if a < b else ((b, OPP), (a, ME))
                s += _resolve_value(rows, plays, own2, other2, ME, vf, diff)
            val = s / len(other)
            if val < best_val:
                best_val, best_card = val, a
        return [(best_card, 1.0)]

    def row(rows, opts, rest, own_after, other_after, own=ME):
        best_i, best_v = 0, float("inf")
        for i, (r2, taken) in enumerate(opts):
            v = (_delta(own, taken, own, diff)
                 + _resolve_value(r2, rest, own_after, other_after, own, vf, diff))
            if v < best_v:
                best_v, best_i = v, i
        return [(best_i, 1.0)]

    return {"card": card, "row": row}


def random_card(rows, own, other):
    p = 1.0 / len(own)
    return [(c, p) for c in own]


def random_row(rows, opts, rest, own_after, other_after, own=ME):
    p = 1.0 / len(opts)
    return [(i, p) for i in range(len(opts))]


def bh_between(lo, hi):
    return sum(BH[v] for v in range(max(1, lo), min(DECK, hi) + 1))


def teacher_scores(rows, hand):
    """advanced_ai 的估值公式（照 teacherPick 的写法，CAP 换成 3、牌堆换成 12）"""
    ends = [r[-1] for r in rows]
    blanks = [CAP - len(r) for r in rows]
    rb = [row_bh(r) for r in rows]
    out = {}
    for card in hand:
        positives = [(card - e, i) for i, e in enumerate(ends) if card - e > 0]
        if not positives:
            val = float(min(rb))
        else:
            diff, i = min(positives)
            if diff <= blanks[i]:
                val = 0.0
            else:
                val = rb[i] + blanks[i] * bh_between(ends[i] + 1, card - 1) / float(DECK)
        out[card] = val
    return out


def greedy_card(rows, own, other):
    sc = teacher_scores(rows, own)
    return [(min(own, key=lambda c: (sc[c], c)), 1.0)]


def greedy_row(rows, opts, rest, own_after, other_after, own=ME):
    best_i = min(range(len(opts)), key=lambda i: (opts[i][1], i))
    return [(best_i, 1.0)]


def smallest_card(rows, own, other):
    return [(min(own), 1.0)]


def largest_card(rows, own, other):
    return [(max(own), 1.0)]


POL_OPT = make_opt_policy(False)
POL_OPTD = make_opt_policy(True)
POL_GREEDY = {"card": greedy_card, "row": greedy_row}
POL_RANDOM = {"card": random_card, "row": random_row}
POL_SMALL = {"card": smallest_card, "row": greedy_row}
POL_LARGE = {"card": largest_card, "row": greedy_row}


# ---------------- 精确评估（枚举整棵树，不用采样） ----------------
def evaluate(rows, me, opp, pol_me, pol_opp):
    """返回 {(我的总分, 对手总分): 概率}，精确值"""
    dist = {}

    def walk(rows, me, opp, mine, theirs, p):
        if not me:
            dist[(mine, theirs)] = dist.get((mine, theirs), 0.0) + p
            return
        me_choices = pol_me["card"](rows, me, opp)
        opp_choices = pol_opp["card"](rows, opp, me)
        for a, pa in me_choices:
            me2 = without(me, a)
            for b, pb in opp_choices:
                opp2 = without(opp, b)
                plays = ((a, ME), (b, OPP)) if a < b else ((b, OPP), (a, ME))

                def ch_me(r, opts, owner, rest, me2=me2, opp2=opp2):
                    return pol_me["row"](r, opts, rest, me2, opp2, owner)

                def ch_opp(r, opts, owner, rest, me2=me2, opp2=opp2):
                    return pol_opp["row"](r, opts, rest, opp2, me2, owner)

                for (r2, dm, do, pr) in resolve_round(rows, plays, ch_me, ch_opp):
                    walk(r2, me2, opp2, mine + dm, theirs + do, p * pa * pb * pr)

    walk(rows, me, opp, 0, 0, 1.0)
    return dist


def summarize(dist):
    e_me = sum(k[0] * p for k, p in dist.items())
    e_op = sum(k[1] * p for k, p in dist.items())
    win = sum(p for (a, b), p in dist.items() if a < b)
    draw = sum(p for (a, b), p in dist.items() if a == b)
    loss = sum(p for (a, b), p in dist.items() if a > b)
    return {"e_me": e_me, "e_op": e_op, "win": win, "draw": draw, "loss": loss}


# ---------------- 状态空间大小 ----------------
def count_row_configs(m, cap=None):
    """从 m 张牌里给 2 行各取 1~cap 张（行有标号；行内只能递增，取集合即确定序列）"""
    cap = CAP if cap is None else cap
    s = 0
    for a in range(1, cap + 1):
        for b in range(1, cap + 1):
            if a + b <= m:
                s += comb(m, a) * comb(m - a, b)
    return s


def count_full_states():
    total, detail = 0, []
    for k in range(HAND + 1):
        m = DECK - 2 * k
        n = comb(DECK, k) * comb(DECK - k, k) * count_row_configs(m)
        detail.append((k, m, n))
        total += n
    return total, detail


def count_variant(deck, cap=CAP, n_rows=N_ROWS):
    """同样规则、不同牌数时的全量局面数（每人 (deck-n_rows)/n_rows 张，回合数相同）"""
    hand = (deck - n_rows) // n_rows
    total = 0
    for k in range(hand + 1):
        m = deck - 2 * k
        total += comb(deck, k) * comb(deck - k, k) * count_row_configs(m, cap)
    return hand, total


def random_deal(rnd):
    cards = list(range(1, DECK + 1))
    rnd.shuffle(cards)
    me = tuple(sorted(cards[:HAND]))
    opp = tuple(sorted(cards[HAND:2 * HAND]))
    rows = canon([(cards[2 * HAND],), (cards[2 * HAND + 1],)])
    return me, opp, rows


# ---------------- 报告 ----------------
def print_state_space():
    total, detail = count_full_states()
    print("=" * 80)
    print("一、状态空间有多大")
    print("=" * 80)
    print("局面 = (我的手牌, 对手手牌, 桌面两行)；k = 已打完的回合数，每人剩 5-k 张")
    print()
    print("  k   不在我俩手里的牌        局面数")
    for k, m, n in detail:
        print("  %d   %2d 张            %s" % (k, m, format(n, ",").rjust(14)))
    print("  合计                  %s" % format(total, ",").rjust(14))
    print()
    print("  行与行可交换 -> 去重后约 %s" % format(total // 2, ","))
    print()
    print("  换牌数会怎样（同样 2 行 × 3 列，每人牌数 = (牌数-2)/2）：")
    print("    牌数   每人手牌        全量局面数")
    for deck in (8, 10, 12, 14):
        hand, n = count_variant(deck)
        mark = "  <-- 本文件用的" if deck == DECK else ""
        print("    %4d   %6d      %s%s" % (deck, hand, format(n, ",").rjust(16), mark))
    print()


def solve_deal(deal):
    me, opp, rows = deal
    V.cache_clear()
    VD.cache_clear()
    SEEN.clear()
    v_opt = V(rows, me, opp)
    v_diff = VD(rows, me, opp)
    res = {"v_opt": v_opt, "v_diff": v_diff, "states": len(SEEN)}

    table = {}
    for name, pol in (("最优A(自己罚分)", POL_OPT),
                      ("最优B(罚分差)", POL_OPTD),
                      ("贪心启发式", POL_GREEDY),
                      ("随机", POL_RANDOM),
                      ("总出最小", POL_SMALL),
                      ("总出最大", POL_LARGE)):
        table[name] = summarize(evaluate(rows, me, opp, pol, POL_RANDOM))
    res["vs_random"] = table

    # 交叉验算：DP 算出来的 V* 应该等于「用这个策略走完」的精确期望
    assert abs(table["最优A(自己罚分)"]["e_me"] - v_opt) < 1e-9, (
        "DP 与精确枚举对不上: %r vs %r" % (table["最优A(自己罚分)"]["e_me"], v_opt))

    # 只有两条：确定性策略互打是「一条线」，只有对随机的那些格才是期望
    pairs = {}
    for na, pa, nb, pb in (("最优A", POL_OPT, "贪心", POL_GREEDY),
                           ("贪心", POL_GREEDY, "最优A", POL_OPT),
                           ("最优A", POL_OPT, "最优A", POL_OPT)):
        pairs[(na, nb)] = summarize(evaluate(rows, me, opp, pa, pb))
    res["pairs"] = pairs
    return res


def main():
    n_deals = 40
    if len(sys.argv) >= 3 and sys.argv[1] == "deals":
        n_deals = int(sys.argv[2])

    print_state_space()

    deal = ((1, 4, 6, 9, 11), (2, 5, 7, 10, 12), canon([(3,), (8,)]))
    print("=" * 80)
    print("二、一副具体的牌：完整求最优")
    print("=" * 80)
    me, opp, rows = deal
    print("P1 手牌 %-20s P2 手牌 %-20s 桌面 %s" % (list(me), list(opp), [list(r) for r in rows]))
    print()
    r = solve_deal(deal)
    print("从这副牌出发可达的局面数（实际要算的 V）: %s" % format(r["states"], ","))
    print("目标 A：最优策略的期望自己的罚分       V*(开局)  = %.4f" % r["v_opt"])
    print("目标 B：最优策略的期望罚分差(我-对手)  VD*(开局) = %.4f" % r["v_diff"])
    print("（1~12 号牌的总牛头是 %d，即一局全部被吃也只有 %d 分）" % (BH_TOTAL, BH_TOTAL))
    print()
    print("各策略 vs 随机对手（精确值，不是采样）：")
    print("  %-18s %8s %8s %8s %8s %8s" % ("策略", "我罚分", "对手罚分", "胜", "平", "负"))
    for name, s in r["vs_random"].items():
        print("  %-18s %8.4f %8.4f %7.2f%% %7.2f%% %7.2f%%" % (
            name, s["e_me"], s["e_op"], 100 * s["win"], 100 * s["draw"], 100 * s["loss"]))
    print()
    print("（\"我罚分\" 是精确期望；最优A 那一行必然等于 V*，可用来交叉验算）")
    print()
    print("确定性策略互打（只有一条对局线，所以给的是双方那一条的分数）：")
    for (na, nb), s in r["pairs"].items():
        print("  %-6s vs %-6s : 我 %5.2f : 对手 %5.2f" % (na, nb, s["e_me"], s["e_op"]))
    print()
    print("首手对比：")
    a_opt = POL_OPT["card"](rows, me, opp)[0][0]
    a_gre = POL_GREEDY["card"](rows, me, opp)[0][0]
    a_dif = POL_OPTD["card"](rows, me, opp)[0][0]
    print("  最优A 出 %2d 号牌（期望罚分 %.4f）" % (a_opt, r["v_opt"]))
    print("  最优B 出 %2d 号牌（期望罚分差 %.4f）" % (a_dif, r["v_diff"]))
    print("  贪心  出 %2d 号牌（期望罚分 %.4f）" % (a_gre, r["vs_random"]["贪心启发式"]["e_me"]))
    print()

    # ---- 聚合 ----
    print("=" * 80)
    print("三、随机抽 %d 副牌的平均值（每副都精确求解）" % n_deals)
    print("=" * 80)
    rnd = random.Random(20231120)
    acc = {}
    pair_acc = {}
    tot_states = 0
    for i in range(n_deals):
        d = random_deal(rnd)
        rr = solve_deal(d)
        tot_states += rr["states"]
        for name, s in rr["vs_random"].items():
            a = acc.setdefault(name, {"e_me": 0.0, "e_op": 0.0, "win": 0.0, "draw": 0.0})
            a["e_me"] += s["e_me"]
            a["e_op"] += s["e_op"]
            a["win"] += s["win"]
            a["draw"] += s["draw"]
        for k, s in rr["pairs"].items():
            a = pair_acc.setdefault(k, {"e_me": 0.0, "e_op": 0.0})
            a["e_me"] += s["e_me"]
            a["e_op"] += s["e_op"]
    print("平均每副牌可达局面数: %s" % format(tot_states // n_deals, ","))
    print()
    print("  %-18s %11s %11s %9s %9s" % ("策略", "平均我罚分", "平均对手罚分", "平均胜率", "平均平局"))
    for name, a in acc.items():
        print("  %-18s %11.4f %11.4f %8.2f%% %8.2f%%" % (
            name, a["e_me"] / n_deals, a["e_op"] / n_deals,
            100 * a["win"] / n_deals, 100 * a["draw"] / n_deals))
    print()
    print("确定性对局（每副牌一条线，这里是 %d 副牌的平均）：" % n_deals)
    for (na, nb), a in pair_acc.items():
        print("  %-6s vs %-6s : 我 %5.3f : 对手 %5.3f" % (
            na, nb, a["e_me"] / n_deals, a["e_op"] / n_deals))
    print()


if __name__ == "__main__":
    main()
