# -*- coding: utf-8 -*-
"""小状态版 6 Nimmt 的真 minimax：零和博弈 + 混合策略

和 small_game_solver.py 的区别只有一处：
    那里假设对手「均匀随机」→ 期望是 (1/|O|)Σ_b ，所以是 MDP；
    这里假设对手「也会打」  → 每个局面解一个 k×k 的矩阵博弈，所以是零和博弈。

零和化方式：付 u = 我的罚分 − 对手的罚分（谁小谁赢），这样 u_我 + u_对手 = 0。
注意这不等于「各自最少牛头」——两人各自最小化自己罚分的博弈不是零和，没有单一"最优"。

矩阵博弈的解法：
    先查纯策略鞍点（min_i max_j == max_j min_i），有就直接用；
    没有就解线性规划（scipy linprog，highs）。没有 scipy 时退回虚构对局（近似）。

用法（建议用带 scipy 的解释器）：
    python minimax_small_game.py              # 一副牌，详细
    python minimax_small_game.py deals 20     # 20 副牌平均
    python minimax_small_game.py sym 40       # 对称性 + 抽样检验
"""

import random
import sys
import time
from functools import lru_cache

import small_game_solver as sg

ME, OPP = sg.ME, sg.OPP

try:
    from scipy.optimize import linprog
    _HAVE_SCIPY = True
except Exception:                                    # 没有 scipy 也能跑，只是近似
    _HAVE_SCIPY = False

LP_CALLS = [0]          # 统计有多少个局面真的需要解 LP


# ---------------- 矩阵博弈 ----------------
def game_value(M):
    """返回 (v, x)：v = min_x max_y x^T M y；x 是我方的最优混合策略

    M 是 n×m 的收益矩阵（对「我方」而言，越小越好）。
    """
    n, m = len(M), len(M[0])
    # 行玩家（最小化）能保证的上界：min_i max_j M[i][j]
    row_guarantee = min(max(row) for row in M)
    # 列玩家（最大化）能保证的下界：max_j min_i M[i][j]
    col_guarantee = max(min(M[i][j] for i in range(n)) for j in range(m))
    if abs(row_guarantee - col_guarantee) < 1e-12:       # 纯策略鞍点存在
        i = min(range(n), key=lambda i: max(M[i]))       # 最小化自己最坏情况的那一行
        x = [0.0] * n
        x[i] = 1.0
        return row_guarantee, x

    if not _HAVE_SCIPY:
        return _fictitious_play(M)

    LP_CALLS[0] += 1
    c = [0.0] * n + [1.0]                                # 变量：x_0..x_{n-1}, v
    a_ub = [[M[i][j] for i in range(n)] + [-1.0] for j in range(m)]
    b_ub = [0.0] * m
    a_eq = [[1.0] * n + [0.0]]
    b_eq = [1.0]
    bounds = [(0.0, None)] * n + [(None, None)]
    res = linprog(c, A_ub=a_ub, b_ub=b_ub, A_eq=a_eq, b_eq=b_eq,
                  bounds=bounds, method="highs")
    if not res.success:
        print("  [warn] linprog 失败，退回虚构对局", file=sys.stderr)
        return _fictitious_play(M)
    return float(res.fun), [float(v) for v in res.x[:n]]


def _fictitious_play(M, iters=20000):
    """没有 scipy 时的近似解：Brown-Robinson 虚构对局"""
    n, m = len(M), len(M[0])
    cnt_a = [0] * n
    cnt_b = [0] * m
    for _ in range(iters):
        # 对手按当前经验分布出招，我选最优纯策略
        col = [sum(M[i][j] * cnt_b[j] for j in range(m)) for i in range(n)]
        ia = min(range(n), key=lambda i: col[i])
        row = [sum(M[i][j] * cnt_a[i] for i in range(n)) for j in range(m)]
        ib = max(range(m), key=lambda j: row[j])
        cnt_a[ia] += 1
        cnt_b[ib] += 1
    v = sum(M[i][j] * cnt_a[i] * cnt_b[j] for i in range(n) for j in range(m)) / (iters * iters)
    x = [c / float(iters) for c in cnt_a]
    return v, x


# ---------------- minimax 的 Bellman ----------------
def _resolve_mm(rows, plays, own_after, other_after, own):
    """一回合结算的值（双方都最优）：own 视角的 u = 自己罚分 − 对手罚分"""
    if not plays:
        return VM(rows, own_after, other_after)
    (card, owner), rest = plays[0], plays[1:]
    kind, opts = sg.place_options(rows, card)
    if kind == "place":
        return _resolve_mm(opts[0][0], rest, own_after, other_after, own)
    if kind == "take":
        r2, taken = opts[0]
        return (sg._delta(owner, taken, own, True)
                + _resolve_mm(r2, rest, own_after, other_after, own))
    vals = [sg._delta(owner, taken, own, True)
            + _resolve_mm(r2, rest, own_after, other_after, own)
            for r2, taken in opts]
    return min(vals) if owner == own else max(vals)


def build_matrix(rows, own, other):
    """我出 a、对手出 b 时的收益矩阵 M[a][b]（own 视角）"""
    M = []
    for a in own:
        own2 = sg.without(own, a)
        row = []
        for b in other:
            other2 = sg.without(other, b)
            plays = ((a, ME), (b, OPP)) if a < b else ((b, OPP), (a, ME))
            row.append(_resolve_mm(rows, plays, own2, other2, ME))
        M.append(row)
    return M


@lru_cache(maxsize=None)
def VM(rows, me, opp):
    """博弈值：双方都最优时，「我的手牌是 me」这一方的期望 u = 自己 − 对手"""
    if not me:
        return 0.0
    v, _x = game_value(build_matrix(rows, me, opp))
    return v


# ---------------- minimax 策略 ----------------
def mm_card(rows, own, other):
    """最优混合出牌"""
    _v, x = game_value(build_matrix(rows, own, other))
    out = []
    for card, p in zip(own, x):
        if p > 1e-12:
            out.append((card, p))
    s = sum(p for _c, p in out)
    return [(c, p / s) for c, p in out]


def mm_row(rows, opts, rest, own_after, other_after, own=ME):
    """被追吃行时挑一行（这一步是顺序决策，纯策略就够）

    own 必须是「选行的人」在那副 plays 里的标记（evaluate 会把它传进来），
    否则就是把对手的罚分算到了自己头上。
    """
    best_i, best_v = 0, float("inf")
    for i, (r2, taken) in enumerate(opts):
        v = taken + _resolve_mm(r2, rest, own_after, other_after, own)
        if v < best_v:
            best_v, best_i = v, i
    return [(best_i, 1.0)]


POL_MM = {"card": mm_card, "row": mm_row}


# ---------------- 报告 ----------------
def showcase():
    deal = ((1, 4, 6, 9, 11), (2, 5, 7, 10, 12), sg.canon([(3,), (8,)]))
    me, opp, rows = deal
    print("=" * 78)
    print("真 minimax（双方都最优，混合策略）")
    print("=" * 78)
    print("P1 手牌 %-20s P2 手牌 %-20s 桌面 %s" % (list(me), list(opp), [list(r) for r in rows]))
    print("scipy: %s" % _HAVE_SCIPY)

    t0 = time.time()
    VM.cache_clear()
    v = VM(rows, me, opp)
    t1 = time.time()
    print()
    print("博弈值 VM(开局) = %.4f   （我 − 对手 的期望罚分差，负数对我有利）" % v)
    print("算 VM 用了 %.2f 秒，其中真的解 LP 的局面 %d 个" % (t1 - t0, LP_CALLS[0]))
    print()

    mix = mm_card(rows, me, opp)
    print("首手最优混合策略：%s" % ", ".join(
        "%d 号牌 %.0f%%" % (c, 100 * p) for c, p in mix))
    print()

    print("对局结果（精确枚举，不是采样）：")
    print("  %-26s %10s %10s %8s" % ("对局", "我罚分", "对手罚分", "我胜率"))
    for name, a, b in MATCHUPS:
        s = sg.summarize(sg.evaluate(rows, me, opp, a, b))
        print("  %-26s %10.4f %10.4f %7.2f%%" % (name, s["e_me"], s["e_op"], 100 * s["win"]))
    print()


MATCHUPS = (
    ("最优(vs随机) vs 随机", sg.POL_OPT, sg.POL_RANDOM),
    ("minimax     vs 随机", POL_MM, sg.POL_RANDOM),
    ("最优(vs随机) vs minimax", sg.POL_OPT, POL_MM),
    ("minimax     vs 最优(vs随机)", POL_MM, sg.POL_OPT),
    ("minimax     vs minimax", POL_MM, POL_MM),
)


def aggregate(n_deals=20):
    rnd = random.Random(20231120)
    acc = {name: {"e_me": 0.0, "e_op": 0.0, "win": 0.0} for name, _a, _b in MATCHUPS}
    vm_sum = 0.0
    t0 = time.time()
    for i in range(n_deals):
        me, opp, rows = sg.random_deal(rnd)
        VM.cache_clear()
        vm = VM(rows, me, opp)
        vm_sum += vm
        for name, a, b in MATCHUPS:
            s = sg.summarize(sg.evaluate(rows, me, opp, a, b))
            acc[name]["e_me"] += s["e_me"]
            acc[name]["e_op"] += s["e_op"]
            acc[name]["win"] += s["win"]
        if (i + 1) % 5 == 0:
            print("  ... %d 副（%.0f 秒）" % (i + 1, time.time() - t0), file=sys.stderr)

    print()
    print("=" * 78)
    print("随机抽 %d 副牌的平均（每副都精确求解 minimax）" % n_deals)
    print("=" * 78)
    print("平均博弈值 VM = %+.4f  （对随机牌局取平均应接近 0；单副能从 -7 摆到 +6）"
          % (vm_sum / n_deals))
    print()
    print("  %-28s %9s %9s %9s %9s" % ("对局", "我罚分", "对手罚分", "我-对手", "我胜率"))
    for name, a, b in MATCHUPS:
        x = acc[name]
        print("  %-28s %9.4f %9.4f %+9.4f %8.2f%%" % (
            name, x["e_me"] / n_deals, x["e_op"] / n_deals,
            (x["e_me"] - x["e_op"]) / n_deals, 100 * x["win"] / n_deals))
    print()


def symmetry_check(n_deals=40):
    """检验两件事：

    ① 精确恒等式：把「手牌对调 + 策略座位对调」之后，应该是同一局。
          A(d) = 在 (H1,H2) 上让 π* 坐 P1、minimax 坐 P2
          C(d) = 在 (H2,H1) 上让 minimax 坐 P1、π* 坐 P2
       按对称性必须 A(d)[π*] == C(d)[π*]、A(d)[mm] == C(d)[mm]。
       这个恒等式如果成立，说明实现没有座位偏置。

    ② 抽样：既然发牌对两个座位是对称的，
          E[π* 在 A 里的分] 应该等于 E[π* 在 B 里的分]。
       给出逐副差值和标准误，看 20 副观察到的差是不是噪声。
    """
    print("=" * 78)
    print("① 精确恒等式：A(d) 与 C(d)（手牌对调 + 策略座位对调）")
    print("=" * 78)
    rnd = random.Random(7)
    max_err = 0.0
    for i in range(5):
        me, opp, rows = sg.random_deal(rnd)
        VM.cache_clear()
        A = sg.summarize(sg.evaluate(rows, me, opp, sg.POL_OPT, POL_MM))
        C = sg.summarize(sg.evaluate(rows, opp, me, POL_MM, sg.POL_OPT))
        e1 = abs(A["e_me"] - C["e_op"])          # π* 在两边拿到的分
        e2 = abs(A["e_op"] - C["e_me"])          # minimax 在两边拿到的分
        max_err = max(max_err, e1, e2)
        print("  第 %d 副: π* %.6f / %.6f   minimax %.6f / %.6f   误差 %.1e"
              % (i + 1, A["e_me"], C["e_op"], A["e_op"], C["e_me"], max(e1, e2)))
    print("  最大误差 %.2e  ->  %s" % (max_err, "恒等式成立" if max_err < 1e-9 else "有座位偏置！"))
    print()

    print("=" * 78)
    print("② 抽样波动：%d 副牌里 π* 在两个座位上的得分" % n_deals)
    print("=" * 78)
    rnd = random.Random(20231120)
    diffs, a_vals, b_vals = [], [], []
    t0 = time.time()
    for i in range(n_deals):
        me, opp, rows = sg.random_deal(rnd)
        VM.cache_clear()
        A = sg.summarize(sg.evaluate(rows, me, opp, sg.POL_OPT, POL_MM))   # π* 坐 P1
        B = sg.summarize(sg.evaluate(rows, me, opp, POL_MM, sg.POL_OPT))   # π* 坐 P2
        a_vals.append(A["e_me"])
        b_vals.append(B["e_op"])
        diffs.append(A["e_me"] - B["e_op"])
        if (i + 1) % 10 == 0:
            print("  ... %d 副（%.0f 秒）" % (i + 1, time.time() - t0), file=sys.stderr)

    n = len(diffs)
    mean_a = sum(a_vals) / n
    mean_b = sum(b_vals) / n
    mean_d = sum(diffs) / n
    sd_d = (sum((d - mean_d) ** 2 for d in diffs) / (n - 1)) ** 0.5
    se = sd_d / (n ** 0.5)
    print()
    print("  π* 坐 P1（对手 minimax）: 平均 %.4f" % mean_a)
    print("  π* 坐 P2（对手 minimax）: 平均 %.4f" % mean_b)
    print("  平均差 %.4f，标准差 %.4f，标准误 %.4f" % (mean_d, sd_d, se))
    print("  95%% 置信区间: [%.4f, %.4f]" % (mean_d - 1.96 * se, mean_d + 1.96 * se))
    print("  结论: %s" % ("差值在噪声范围内（区间跨 0）" if abs(mean_d) < 1.96 * se
                        else "差值统计显著，需要找原因"))
    print()
    print("  逐副差值（前 12 个）: %s" % ", ".join("%+.2f" % d for d in diffs[:12]))
    print()


if __name__ == "__main__":
    if len(sys.argv) >= 2 and sys.argv[1] == "deals":
        aggregate(int(sys.argv[2]) if len(sys.argv) > 2 else 20)
    elif len(sys.argv) >= 2 and sys.argv[1] == "sym":
        symmetry_check(int(sys.argv[2]) if len(sys.argv) > 2 else 40)
    else:
        showcase()
