# -*- coding: utf-8 -*-
"""底牌信息在对局中的价值上限：抠底到底影响多少分？

V 网络从来不看底牌（`_features_seat` 不读 `state.bottom`）。这是"安全但有损"的：
  - 安全：不会偷看自己不该知道的底牌（否则就是作弊）
  - 有损：自己是最后埋底者时，那 8 张是确凿信息，却没用上

这里量两个数：
  1. 抠底多常发生、平均乘数多少、转移多少分
  2. 底牌里平均有多少分
"""
import sys
from collections import Counter

sys.path.insert(0, r"D:\Programming\Marvin_Has_Fun_2309\40_Python\20261121_Tractor_game\scripts")

from tractor.ai_select import AiEngine  # noqa: E402
from tractor.cards import card_points  # noqa: E402
from tractor.engine import TractorGame  # noqa: E402
from tractor.fast_state import FastState  # noqa: E402


def main():
    deals = int(sys.argv[1]) if len(sys.argv) > 1 else 200
    ai = AiEngine("adv")
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
        c["deals"] += 1
        # 最终底牌的分
        c["底牌分"] += sum(card_points(x) for x in g.bottom)
        st = FastState.from_game(g)
        for _ in range(700):
            if st.is_terminal():
                break
            seat = st.current_player
            lead = g.trick.lead if (g.trick and g.trick.lead) else None
            cards = ai.play(g, seat)
            ok, _ = (g.play_follow(seat, cards) if lead is not None
                     else g.play_lead(seat, cards))
            if not ok:
                break
            ai.observe(g, seat, cards, lead)
            st.play(seat, cards)
        r = g.deal_result or {}
        mult = r.get("bottom_multiplier") or r.get("multiplier") or 0
        if mult:
            c["抠底次数"] += 1
            c["乘数和"] += mult
            pts = sum(card_points(x) for x in g.bottom)
            c["抠底转移分"] += pts * mult
            if mult > 1:
                c["倍数>1"] += 1
    n = max(1, c["deals"])
    print("=" * 66)
    print("底牌信息的价值上限（%d 局，会推理 AI 自对弈）" % c["deals"])
    print("=" * 66)
    print("  底牌平均分：%.2f 分" % (c["底牌分"] / n))
    print("  抠底发生：%d 局（%.0f%%），其中倍数>1：%d 局（%.0f%%）"
          % (c["抠底次数"], 100.0 * c["抠底次数"] / n,
             c["倍数>1"], 100.0 * c["倍数>1"] / n))
    if c["抠底次数"]:
        print("  平均乘数：%.2f；平均转移 %.1f 分"
              % (c["乘数和"] / c["抠底次数"], c["抠底转移分"] / c["抠底次数"]))
        print("  每局平均因抠底转移：%.1f 分" % (c["抠底转移分"] / n))
    return 0


if __name__ == "__main__":
    sys.exit(main())
