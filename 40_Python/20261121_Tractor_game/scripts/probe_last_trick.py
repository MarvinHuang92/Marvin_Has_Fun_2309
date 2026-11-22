# -*- coding: utf-8 -*-
"""为什么最后一墩的倍数永远是 ×1？

关键猜想：25 张牌打 25 墩，如果前面都是单张领出，**最后一墩每人手里只剩 1 张**，
根本不可能领对子。这里直接量。

统计：最后一墩领出时，领出者手里有几张牌。
"""
import sys
from collections import Counter

sys.path.insert(0, r"D:\Programming\Marvin_Has_Fun_2309\40_Python\20261121_Tractor_game\scripts")

from tractor.ai_heuristic import HeuristicAI  # noqa: E402
from tractor.engine import TractorGame  # noqa: E402
from tractor.fast_state import FastState  # noqa: E402


def main():
    deals = int(sys.argv[1]) if len(sys.argv) > 1 else 150
    ai = HeuristicAI()
    c = Counter()
    for d in range(deals):
        g = TractorGame(700000 + d)
        g.start_match()
        ai.begin_deal(g)
        for _ in range(900):
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
        st = FastState.from_game(g)
        for _ in range(700):
            if st.is_terminal():
                break
            seat = st.current_player
            lead = g.trick.lead if (g.trick and g.trick.lead) else None
            if lead is None:
                others = max((len(st.hands[x]) for x in range(4) if x != seat),
                             default=0)
                is_last = others <= 1 or (others <= 2 and len(st.hands[seat]) <= 2)
            else:
                is_last = False
            if lead is None and is_last and st.trick_no >= (0 if True else 24):
                n = len(st.hands[seat])
                c["最后一墩领出手牌数_%d" % n] += 1
                if n >= 2:
                    c["有机会领多张"] += 1
                    if st.team(st.zhuang) != st.team(seat):
                        c["闲家有牌可领多张"] += 1
            cards = ai.play(g, seat)
            ok, _ = (g.play_follow(seat, cards) if lead is not None
                     else g.play_lead(seat, cards))
            if not ok:
                break
            ai.observe(g, seat, cards, lead)
            st.play(seat, cards)

    total = sum(v for k, v in c.items() if k.startswith("最后一墩"))
    print("=" * 62)
    print("最后一墩领出时，领出者手里有几张（%d 局）" % deals)
    print("=" * 62)
    for n in sorted(int(k.split("_")[-1]) for k in c if k.startswith("最后一墩")):
        v = c["最后一墩领出手牌数_%d" % n]
        print("  手里 %d 张：%3d 次（%4.0f%%）" % (n, v, 100.0 * v / max(1, total)))
    print("  有可能领出多张（≥2 张）：%d 次（%.0f%%）"
          % (c["有机会领多张"], 100.0 * c["有机会领多张"] / max(1, total)))
    print("  其中是闲家：%d 次" % c["闲家有牌可领多张"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
