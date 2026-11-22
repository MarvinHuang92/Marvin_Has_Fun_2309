# -*- coding: utf-8 -*-
"""甩牌现状：AI 会甩吗？甩了之后被毙/被压的比例多大？"""
import sys
from collections import Counter

sys.path.insert(0, r"D:\Programming\Marvin_Has_Fun_2309\40_Python\20261121_Tractor_game\scripts")

from tractor.ai_select import AiEngine  # noqa: E402
from tractor.engine import TractorGame  # noqa: E402
from tractor.fast_state import FastState  # noqa: E402


def probe(kind, deals):
    ai = AiEngine(kind)
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

        st = FastState.from_game(g)
        for _ in range(600):
            if st.is_terminal():
                break
            seat = st.current_player
            is_lead = not st.plays
            lead = g.trick.lead if (g.trick and g.trick.lead) else None
            cards = ai.play(g, seat)

            if is_lead:
                c["leads"] += 1
                n = len(cards)
                if n == 1:
                    c["单张"] += 1
                elif n == 2:
                    c["对子"] += 1
                else:
                    # 连对（拖拉机）vs 甩牌
                    ranks = sorted({x.rank for x in cards})
                    consec = all(ranks[i + 1] == ranks[i] + 1
                                 for i in range(len(ranks) - 1))
                    kinds = {x.suit for x in cards}
                    if consec and len(kinds) <= 1 and n == 2 * len(ranks):
                        c["拖拉机"] += 1
                    else:
                        c["甩牌"] += 1
                        c["甩牌张数"] += n
                        # 这手甩牌最后被谁赢走了
                        c.setdefault("_throw_marks", [])
                        c["_throw_marks"].append((g.trick_no, seat))

            ok, msg = (g.play_follow(seat, cards) if lead is not None
                       else g.play_lead(seat, cards))
            if not ok:
                break
            ai.observe(g, seat, cards, lead)
            st.play(seat, cards)

            # 一墩结束：检查最近一次甩牌是不是被对方赢走了
            if len(st.plays) == 0 and c.get("_throw_marks"):
                tn, ts = c["_throw_marks"][-1]
                if tn == st.trick_no - 1 or tn == st.trick_no:
                    winner = st.last_winner if hasattr(st, "last_winner") else None
                    if winner is not None:
                        if st.team(winner) != st.team(ts):
                            c["甩牌被对方赢走"] += 1
                        else:
                            c["甩牌我方赢下"] += 1
                    c["_throw_marks"].pop()
    return c


def main():
    deals = int(sys.argv[1]) if len(sys.argv) > 1 else 60
    print("=" * 64)
    print("甩牌现状：%d 局" % deals)
    print("=" * 64)
    for kind in ("adv", "heuristic"):
        c = probe(kind, deals)
        leads = max(1, c["leads"])
        th = c.get("甩牌", 0)
        print("%-10s 领出 %d 次：单张 %d（%.0f%%）、对子 %d（%.0f%%）、"
              "拖拉机 %d（%.0f%%）、甩牌 %d（%.1f%%）"
              % (kind, c["leads"], c["单张"], 100.0 * c["单张"] / leads,
                 c["对子"], 100.0 * c["对子"] / leads,
                 c["拖拉机"], 100.0 * c["拖拉机"] / leads,
                 th, 100.0 * th / leads))
        if th:
            print("           甩牌平均 %.1f 张；我方赢下 %d、被对方赢走 %d"
                  % (c["甩牌张数"] / th, c.get("甩牌我方赢下", 0),
                     c.get("甩牌被对方赢走", 0)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
