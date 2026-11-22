# -*- coding: utf-8 -*-
"""神谕测试：V 网络对"埋哪 8 张"的判断，和**真的打到底**的结果对不对得上？

做法（同一局的几种埋法互为对照，消除牌运）：
  1. 打到庄家埋底那一刻，拿到 33 张的池子
  2. 生成 5 种候选埋法（启发式 + 4 种"换掉 1~2 张"的扰动）
  3. 每种埋法：用同一个种子**从头重放**，在埋底那一步强制用这个方案，然后打到底
  4. 同时记下 V 网络对这 5 种埋法的打分
  5. 比较：V 认为最好的那个，是不是真的打得最好？

如果 V 的排序和真实结果对不上 → 说明"用 V 当埋底评估器"这条路本身就不成立，
不是搜索空间或参数的问题。
"""
from __future__ import annotations

import os
import random
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from tractor import value_net  # noqa: E402
from tractor.ai_heuristic import HeuristicAI  # noqa: E402
from tractor.engine import TractorGame  # noqa: E402
from tractor.fast_state import FastState  # noqa: E402


def play_with_bury(seed: int, bury_cards):
    """从头重放；轮到庄家埋底时用 `bury_cards`（None = 用 AI 自己的选择）。"""
    ai = HeuristicAI()
    g = TractorGame(seed)
    g.start_match()
    ai.begin_deal(g)
    used = False
    for _ in range(900):
        if g.phase == "play":
            break
        seat = g.acting_seat()
        if seat is None:
            return None
        if g.phase in ("bid_initial", "bid_extra"):
            ok, _ = g.submit_bid(seat, ai.bid(g, seat))
            if not ok:
                return None
        elif g.phase in ("bury_initial", "bury_extra"):
            if bury_cards is not None and not used and seat == g.zhuang:
                cards = list(bury_cards)
                used = True
            else:
                cards = ai.bury(g, seat)
            if sort_ok(g, seat, cards) is False:
                return None
            ok, _ = g.submit_bury(seat, cards)
            if not ok:
                return None
            ai.note_buried(seat, cards)
        else:
            return None
    if g.phase != "play":
        return None

    state = FastState.from_game(g)
    for _ in range(700):
        if state.is_terminal():
            break
        seat = state.current_player
        lead = g.trick.lead if (g.trick and g.trick.lead) else None
        cards = ai.play(g, seat)
        ok, _ = (g.play_follow(seat, cards) if lead is not None
                 else g.play_lead(seat, cards))
        if not ok:
            return None
        ai.observe(g, seat, cards, lead)
        state.play(seat, cards)
    else:
        return None
    zt = g.team(g.zhuang)
    return {zt: g.declarer_points, 1 - zt: g.defender_points}


def sort_ok(g, seat, cards):
    return True


def main():
    value_net.load_active(str(os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "models", "value_v4.json")))
    deals = int(sys.argv[1]) if len(sys.argv) > 1 else 40
    rng = random.Random(20261123)

    hit_best = 0
    hit_worst = 0
    total = 0
    pairs = []          # (V 差, 真实分差)

    for d in range(deals * 2):
        if total >= deals:
            break
        seed = 700000 + d
        g = TractorGame(seed)
        g.start_match()
        ai = HeuristicAI()
        ai.begin_deal(g)
        for _ in range(300):
            if g.phase in ("bury_initial", "bury_extra"):
                break
            if g.phase == "play":
                break
            seat = g.acting_seat()
            if seat is None:
                break
            if g.phase in ("bid_initial", "bid_extra"):
                g.submit_bid(seat, ai.bid(g, seat))
            else:
                break
        if g.phase not in ("bury_initial", "bury_extra"):
            continue
        seat = g.pending_bury_by
        if seat != g.zhuang:
            continue
        pool = list(g.hands[seat]) + list(g.bottom)
        if len(pool) != 33:
            continue
        base = ai.bury(g, seat)

        # 5 种候选：启发式 + 4 种扰动
        cands = [tuple(sorted(base, key=lambda c: (c.suit, c.rank)))]
        for _ in range(4):
            alt = list(base)
            for _ in range(rng.randint(1, 2)):
                i = rng.randrange(8)
                pool_rest = [c for c in pool if c not in alt]
                if not pool_rest:
                    break
                alt[i] = rng.choice(pool_rest)
            cands.append(tuple(sorted(alt, key=lambda c: (c.suit, c.rank))))
        cands = list(dict.fromkeys(cands))
        if len(cands) < 3:
            continue

        # V 打分（同一批定约采样）
        team = g.team(seat)
        st = FastState.from_game(g)
        v_scores = []
        for c in cands:
            rest = [x for x in pool if x not in c]
            st.hands[seat] = rest
            st.bottom = list(c)
            v_scores.append(sum(value_net.active().predict(st, team) for _ in range(3)) / 3.0)

        # 真实结果
        true_pts = []
        for c in cands:
            r = play_with_bury(seed, c)
            if r is None:
                true_pts = []
                break
            true_pts.append(r[team])
        if len(true_pts) != len(cands):
            continue

        total += 1
        v_best = v_scores.index(max(v_scores))
        t_best = true_pts.index(max(true_pts))
        t_worst = true_pts.index(min(true_pts))
        if v_best == t_best:
            hit_best += 1
        if v_best == t_worst:
            hit_worst += 1
        for i in range(len(cands)):
            for j in range(len(cands)):
                if i < j:
                    pairs.append((v_scores[i] - v_scores[j],
                                  true_pts[i] - true_pts[j]))

    if not total:
        print("没有可用样本")
        return 1
    import statistics as st_
    n = len(pairs)
    mv = sum(p[0] for p in pairs) / n
    mt = sum(p[1] for p in pairs) / n
    cov = sum((p[0] - mv) * (p[1] - mt) for p in pairs) / n
    sv = (sum((p[0] - mv) ** 2 for p in pairs) / n) ** 0.5
    stt = (sum((p[1] - mt) ** 2 for p in pairs) / n) ** 0.5
    corr = cov / (sv * stt) if sv and stt else 0.0
    print("=" * 66)
    print("神谕测试：V 排序 vs 真实打到底（%d 局，每局 %d 种埋法）"
          % (total, len(cands)))
    print("=" * 66)
    print("  V 选中的那个埋法，真的是这几种里最好的：%d 次（%.0f%%）"
          % (hit_best, 100.0 * hit_best / total))
    print("  V 选中的那个，反而是最差的：          %d 次（%.0f%%）"
          % (hit_worst, 100.0 * hit_worst / total))
    print("  随机瞎选的期望：最好约 %.0f%%，最差约 %.0f%%"
          % (100.0 / len(cands), 100.0 / len(cands)))
    print("  两两比较的相关系数（V 差 vs 真实分差）：%+.3f（%d 对）"
          % (corr, n))
    return 0


if __name__ == "__main__":
    sys.exit(main())
