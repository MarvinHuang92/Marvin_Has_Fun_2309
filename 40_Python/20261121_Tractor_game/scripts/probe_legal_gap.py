# -*- coding: utf-8 -*-
"""定位：修正"必须跟对子"之后，哪些局面枚举器找不到合法出牌。

跑法：python scripts/probe_legal_gap.py 20
"""
import sys

sys.path.insert(0, r"D:\Programming\Marvin_Has_Fun_2309\40_Python\20261121_Tractor_game\scripts")

from tractor.ai_select import AiEngine  # noqa: E402
from tractor.engine import TractorGame  # noqa: E402
from tractor.fast_state import FastState  # noqa: E402
from tractor.moves import legal_moves, legal_moves_fast  # noqa: E402
from tractor.rules import is_legal_follow, pair_count, match_slots  # noqa: E402


def main():
    deals = int(sys.argv[1]) if len(sys.argv) > 1 else 20
    kind = sys.argv[2] if len(sys.argv) > 2 else "adv"
    ai = AiEngine(kind)
    bad = 0
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
                cc = ai.bury(g, seat)
                ok, _ = g.submit_bury(seat, cc)
                if ok:
                    ai.note_buried(seat, cc)
        if g.phase != "play":
            continue
        st = FastState.from_game(g)
        for step in range(700):
            if st.is_terminal():
                break
            seat = st.current_player
            if st.lead is not None:
                cands_f = legal_moves_fast(st, seat, 12)
                legal_f = [mv for mv in cands_f
                           if is_legal_follow(st.hands[seat], mv, st.lead,
                                              st.level, st.trump_suit)[0]]
                cands_s = legal_moves(st, seat, max_moves=120)
                legal_s = [mv for mv in cands_s
                           if is_legal_follow(st.hands[seat], mv, st.lead,
                                              st.level, st.trump_suit)[0]]
                legal = legal_f and legal_s
                cands = cands_f
                if not legal:
                    bad += 1
                    lead = st.lead
                    cat = lead.category
                    hand_cat = [c for c in st.hands[seat] if cat.contains(c)]
                    print("=" * 70)
                    print("第%d局 第%d墩 座位%d：快速枚举 %d 个/合法 %d，"
                          "完整枚举 %d 个/合法 %d  **有死角**"
                          % (d, st.trick_no, seat, len(cands_f), len(legal_f),
                             len(cands_s), len(legal_s)))
                    print("  领出：%s  [%s]"
                          % (",".join(c.short for c in lead.cards),
                             ",".join("%s(%s)" % (s.kind, s.length)
                                      for s in lead.slots)))
                    print("  领出类别：%s，需要 %d 张" % (cat.name, len(lead.cards)))
                    print("  手上：(%d 张) %s"
                          % (len(st.hands[seat]),
                             " ".join(c.short for c in st.hands[seat])))
                    print("  该门手牌 %d 张：%s"
                          % (len(hand_cat), " ".join(c.short for c in hand_cat)))
                    print("  该门对子数：%d" % pair_count(hand_cat, cat))
                    req = match_slots(hand_cat, lead.slots, cat,
                                      require_all=False, allow_partial=True)
                    print("  match_slots: %s"
                          % (["-" if r is None else r.label() for r in (req or [])]))
                    for mv in cands[:4]:
                        ok, why = is_legal_follow(st.hands[seat], mv, st.lead,
                                                  st.level, st.trump_suit)
                        print("    候选 %s -> %s"
                              % (",".join(c.short for c in mv), why or "ok"))
                    if bad >= 3:
                        return 1
            cards = ai.play(g, seat)
            lead = g.trick.lead if (g.trick and g.trick.lead) else None
            ok, msg = (g.play_follow(seat, cards) if lead is not None
                       else g.play_lead(seat, cards))
            if not ok:
                print("!! 引擎拒绝：%s" % msg)
                return 1
            ai.observe(g, seat, cards, lead)
            st.play(seat, cards)
    print("检查完毕，0 个死角" if bad == 0 else "共 %d 个死角" % bad)
    return 0


if __name__ == "__main__":
    sys.exit(main())
