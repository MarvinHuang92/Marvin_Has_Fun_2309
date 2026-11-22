# -*- coding: utf-8 -*-
"""统计「换底推理」到底多常用：known_bottom / stale_kitty 各占多少局。"""
import sys
from collections import Counter

sys.path.insert(0, r"D:\Programming\Marvin_Has_Fun_2309\40_Python\20261121_Tractor_game\scripts")

from tractor.ai_select import AiEngine  # noqa: E402
from tractor.engine import TractorGame  # noqa: E402
from tractor.fast_state import FastState  # noqa: E402


def main():
    ai = AiEngine("adv")
    helper = ai._brain.helper
    c = Counter()
    for d in range(80):
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
        c["deals"] += 1
        c["burials"] += len(st.buriers)
        if len(set(st.buriers)) > 1:
            c["多人都埋过"] += 1
        for seat in range(4):
            helper.sync_bottom(st, seat)
            tr = helper.tracker
            if tr.known_bottom:
                c["seat知道底牌"] += 1
            if getattr(tr, "stale_kitty", None):
                c["seat有换底信息"] += 1
    n = max(1, c["deals"])
    print("对局 %d 局，平均埋底次数 %.2f，出现「多人都埋过」%d 局"
          % (c["deals"], c["burials"] / n, c["多人都埋过"]))
    print("  按座位统计（每局 4 个视角，共 %d 个）：" % (c["deals"] * 4))
    print("    知道最终底牌：%d（%.0f%%）"
          % (c["seat知道底牌"], 100.0 * c["seat知道底牌"] / (n * 4)))
    print("    有「换底后谁可能持有」信息：%d（%.0f%%）"
          % (c["seat有换底信息"], 100.0 * c["seat有换底信息"] / (n * 4)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
