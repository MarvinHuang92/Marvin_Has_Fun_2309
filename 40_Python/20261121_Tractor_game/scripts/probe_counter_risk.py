# -*- coding: utf-8 -*-
"""换底风险的真实发生率（修正版）。

## 上一版的两个错误

1. **循环论证**：先用"最终主牌"把埋掉的牌里的主牌排除，再问"最终主牌是不是
   在埋掉的牌里" —— 永远为假。所以那个 0% 是假象。
2. **跑的是带防御的配置**（默认 `bury_defense_penalty=6`），测的本来就不是
   "有风险时会发生什么"。

## 这一版测什么

- 庄家第一次埋的 8 张里，有没有"最终被别人拿去当主牌的那门"的牌
  → 有 = 那次换底直接从庄家手里收走了他埋掉的牌（用户说的"白送"）
- 分别跑防御惩罚 0 / 6，看防御规则把这件事降低了多少
"""
import sys
from collections import Counter

sys.path.insert(0, r"D:\Programming\Marvin_Has_Fun_2309\40_Python\20261121_Tractor_game\scripts")

from tractor.ai_heuristic import HeuristicAI  # noqa: E402
from tractor.engine import TractorGame  # noqa: E402


def run(penalty: int, deals: int = 200):
    ai = HeuristicAI(opts={"bury_defense_penalty": penalty})
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
        hist = g.bottom_history
        if len(hist) < 2:
            continue
        c["换底"] += 1
        buried = hist[0]["cards"]
        suits = Counter(card.suit for card in buried)
        # **不排除任何牌**：直接看最终主牌是不是庄家埋过的那门
        if g.trump_suit in suits:
            c["换的主牌在第一次埋掉的牌里"] += 1
            c["被收走的张数"] += suits[g.trump_suit]
    return c


def main():
    deals = int(sys.argv[1]) if len(sys.argv) > 1 else 200
    print("=" * 66)
    print("换底风险的真实发生率（%d 局/组）" % deals)
    print("=" * 66)
    for penalty in (0, 6):
        c = run(penalty, deals)
        n = max(1, c["deals"])
        s = max(1, c["换底"])
        print("防御惩罚 %d：" % penalty)
        print("   换底 %d 局（%.0f%%）" % (c["换底"], 100.0 * c["换底"] / n))
        print("   其中换的主牌正好是庄家埋过的那门：%d 局（占换底的 %.0f%%，占总局 %.0f%%）"
              % (c["换的主牌在第一次埋掉的牌里"],
                 100.0 * c["换的主牌在第一次埋掉的牌里"] / s,
                 100.0 * c["换的主牌在第一次埋掉的牌里"] / n))
        if c["换的主牌在第一次埋掉的牌里"]:
            print("   平均被收走 %.1f 张" % (c["被收走的张数"]
                                          / c["换的主牌在第一次埋掉的牌里"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
