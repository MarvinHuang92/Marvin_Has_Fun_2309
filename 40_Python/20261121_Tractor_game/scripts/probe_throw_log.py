# -*- coding: utf-8 -*-
"""验证：甩牌被卡时，对局记录里同时出现"想甩什么"和"改出什么"。"""
import sys

sys.path.insert(0, r"D:\Programming\Marvin_Has_Fun_2309\40_Python\20261121_Tractor_game\scripts")

from tractor.ai_select import AiEngine  # noqa: E402
from tractor.engine import TractorGame  # noqa: E402


def main():
    ai = AiEngine(sys.argv[1] if len(sys.argv) > 1 else "heuristic")
    found = 0
    for d in range(120):
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
                c = ai.bury(g, seat)
                ok, _ = g.submit_bury(seat, c)
                if ok:
                    ai.note_buried(seat, c)
        if g.phase != "play":
            continue
        for _ in range(700):
            if g.phase != "play":
                break
            seat = g.current_player
            lead = g.trick.lead if (g.trick and g.trick.lead) else None
            cards = ai.play(g, seat)
            ok, msg = (g.play_follow(seat, cards) if lead is not None
                       else g.play_lead(seat, cards))
            if not ok:
                break
            ai.observe(g, seat, cards, lead)
            for line in g.log:
                if "想甩" in line and found < 3:
                    print("  记录：%s" % line)
                    found += 1
            if found >= 3:
                return 0
    print("120 局里没遇到甩牌被卡（可能这档 AI 很少甩牌）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
