# -*- coding: utf-8 -*-
"""防御性埋底的风险有多常真的发生？

场景：庄家把某门埋断 → 某个对手用**同一门**的级牌对反主（换底）→ 庄家刚埋掉的
那门牌白送（还被换底的人拿走）。

这里统计：
  1. 庄家埋断的这门，两张级牌是不是"我一张都没有"（= 有被反主风险）
  2. 之后真的发生了换底吗？换的主牌是不是正好是那门？
"""
import sys
from collections import Counter

sys.path.insert(0, r"D:\Programming\Marvin_Has_Fun_2309\40_Python\20261121_Tractor_game\scripts")

from tractor.ai_select import AiEngine  # noqa: E402
from tractor.cards import is_trump  # noqa: E402
from tractor.engine import TractorGame  # noqa: E402


def main():
    ai = AiEngine("heuristic")
    helper = ai._brain
    c = Counter()
    for d in range(200):
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
        if not hist:
            continue
        first = hist[0]
        burier = first["burier"]
        level = g.level
        # 第一次埋底后：庄家在哪门断了？（第一次埋底时 trump 还可能是原来的）
        by_suit = {}
        for card in first["cards"]:
            if is_trump(card, level, g.trump_suit):
                continue
            by_suit.setdefault(card.suit, []).append(card)
        # 先把"第一次埋底前的 25 张"还原出来不容易，退一步：
        # 只看「第一次埋的牌里有没有整门」是不可能的（没有原始手牌）。
        # 改用：统计换底次数 + 换的主牌花色，和第一次埋掉的牌的花色分布
        if len(hist) > 1:
            c["换底"] += 1
            # 换底后的主牌花色
            for h in hist[1:]:
                pass
            # 挖一下：换底者的主牌花色 = 最终 trump
            buried_suits = Counter(card.suit for card in first["cards"]
                                   if not is_trump(card, level, g.trump_suit))
            if g.trump_suit in buried_suits:
                c["换的主牌正好是第一次埋掉的某门"] += 1
            if buried_suits and g.trump_suit == buried_suits.most_common(1)[0][0]:
                c["换的主牌正好是埋得最多的那门"] += 1
    n = max(1, c["deals"])
    print("对局 %d 局" % c["deals"])
    print("  发生换底：%d 局（%.0f%%）" % (c["换底"], 100.0 * c["换底"] / n))
    print("  换的主牌正好是第一次埋掉的某一门：%d 局（%.0f%%）"
          % (c["换的主牌正好是第一次埋掉的某门"],
             100.0 * c["换的主牌正好是第一次埋掉的某门"] / n))
    print("  换的主牌正好是埋得最多的那门：%d 局（%.0f%%）"
          % (c["换的主牌正好是埋得最多的那门"],
             100.0 * c["换的主牌正好是埋得最多的那门"] / n))
    return 0


if __name__ == "__main__":
    sys.exit(main())
