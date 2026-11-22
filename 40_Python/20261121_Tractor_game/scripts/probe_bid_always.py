# -*- coding: utf-8 -*-
"""「能反必反」到底改变了多少行为：反主次数分布 + 连环反主。

统计每局的埋底次数（= 1 + 反主次数），以及"反 2 次以上"的比例。
"""
import sys
from collections import Counter

sys.path.insert(0, r"D:\Programming\Marvin_Has_Fun_2309\40_Python\20261121_Tractor_game\scripts")

from tractor.ai_heuristic import HeuristicAI  # noqa: E402
from tractor.engine import TractorGame  # noqa: E402


def run(mode, deals=120):
    opts = {} if mode is None else {"bid_always": mode}
    ai = HeuristicAI(opts=opts)
    c = Counter()
    for d in range(deals):
        g = TractorGame(700000 + d)
        g.start_match()
        ai.begin_deal(g)
        for _ in range(800):
            if g.phase == "play":
                break
            seat = g.acting_seat()
            if seat is None:
                break
            if g.phase in ("bid_initial", "bid_extra"):
                g.submit_bid(seat, ai.bid(g, seat))
            elif g.phase in ("bury_initial", "bury_extra"):
                cards = ai.bury(g, seat)
                ok, _ = g.submit_bury(seat, cards)
                if ok:
                    ai.note_buried(seat, cards)
        if g.phase != "play":
            continue
        c["deals"] += 1
        n = len(g.bottom_history)
        c["埋底总数"] += n
        c["反主次数_%d" % (n - 1)] += 1
        # 换过的不同主牌花色数（庄家会被反复换花色）
        c["不同主牌色"] += len({g.trump_suit})
    return c


def main():
    deals = int(sys.argv[1]) if len(sys.argv) > 1 else 120
    print("=" * 68)
    print("「能反必反」的行为影响（%d 局/组）" % deals)
    print("=" * 68)
    for label, mode in (("基线（按手牌强度）", None),
                        ("能反必反 · 最强", "max"),
                        ("能反必反 · 最弱", "min")):
        c = run(mode, deals)
        n = max(1, c["deals"])
        dist = "  ".join("%d次:%d" % (k, c["反主次数_%d" % k])
                         for k in range(5) if c["反主次数_%d" % k])
        print("%-16s 平均埋底 %.2f 次/局；反主次数分布 %s"
              % (label, c["埋底总数"] / n, dist))
    return 0


if __name__ == "__main__":
    sys.exit(main())
