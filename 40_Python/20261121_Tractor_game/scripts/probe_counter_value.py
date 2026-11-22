# -*- coding: utf-8 -*-
"""反主的**单次决策反事实**：同一局、同一时刻，只改"反 / 不反"，然后两条时间线各自打完。

和之前那种"两个策略对打"的区别：

- 策略 A/B：两条时间线从第一局第一手就分叉，测的是"策略好不好"；
- 这里：两条时间线**只在反主那一刻分叉**，之前所有决策完全一样（同一个种子、同一套 AI），
  之后也用同一套 AI 打完 → 差值可以归因到"这一次反主"。

## 怎么分叉

同一个种子重放两遍：在"目标步"上，一遍强制反主、一遍强制过。
之前的步数完全一致（AI 是确定性的），所以分叉点精确。

统计量：**反主方那一队**在两条时间线上的得分差（分 / 升级增量）。

跑法：python scripts/probe_counter_value.py 200
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from tractor.ai_heuristic import HeuristicAI  # noqa: E402
from tractor.engine import TractorGame  # noqa: E402
from tractor.fast_state import FastState  # noqa: E402


def drive(seed: int, force_step: int = -1, force_action: str = "", verbose=False):
    """打完一局。`force_step` 处强制"反主 / 过"。

    返回 dict（含结局、以及分叉点的信息）；无效局返回 None。
    """
    ai = HeuristicAI()
    game = TractorGame(seed)
    game.start_match()
    ai.begin_deal(game)

    step = 0
    fork_info = None
    for _ in range(900):
        if game.phase == "play":
            break
        seat = game.acting_seat()
        if seat is None:
            return None
        if game.phase in ("bid_initial", "bid_extra"):
            cur = game.declaration
            bids = game.legal_bids(seat)
            counters = [b for b in bids if cur is None or b.level > cur.level]
            if step == force_step:
                if force_action == "counter" and counters:
                    bid = counters[0]
                    fork_info = (seat, game.team(seat), bid)
                else:
                    bid = None
                    fork_info = (seat, game.team(seat), None)
            else:
                bid = ai.bid(game, seat)
                # 记录第一次"能反且是对方亮的主"的机会
                if (force_step == -1 and fork_info is None and cur is not None
                        and game.phase == FORK_PHASE       # 在哪一阶段分叉
                        and game.team(cur.seat) != game.team(seat) and counters):
                    took = bid is not None and bid.level > cur.level
                    want = "ai_counter" if took else "ai_pass"
                    if want == WHICH:
                        fork_info = ("opportunity", seat, game.team(seat), step)
            ok, _ = game.submit_bid(seat, bid)
            if not ok:
                return None
            step += 1
        elif game.phase in ("bury_initial", "bury_extra"):
            cards = ai.bury(game, seat)
            ok, _ = game.submit_bury(seat, cards)
            if not ok:
                return None
            ai.note_buried(seat, cards)
            step += 1
        else:
            return None

    if game.phase != "play":
        return None

    state = FastState.from_game(game)
    for _ in range(700):
        if state.is_terminal():
            break
        seat = state.current_player
        lead = game.trick.lead if (game.trick and game.trick.lead) else None
        cards = ai.play(game, seat)
        ok, msg = (game.play_follow(seat, cards) if lead is not None
                   else game.play_lead(seat, cards))
        if not ok:
            return None
        ai.observe(game, seat, cards, lead)
        state.play(seat, cards)
    else:
        return None

    zt = game.team(game.zhuang)
    pts = {zt: game.declarer_points, 1 - zt: game.defender_points}
    r = game.deal_result or {}
    win_team = r.get("zhuang_team", zt) if r.get("side") == "zhuang" else 1 - r.get("zhuang_team", zt)
    return {"pts": pts, "win_team": win_team, "delta": r.get("delta", 0),
            "fork": fork_info, "zhuang_team": zt}


WHICH = "ai_counter"
FORK_PHASE = "bid_extra"


def main():
    global WHICH, FORK_PHASE
    WHICH = sys.argv[2] if len(sys.argv) > 2 else "ai_counter"
    FORK_PHASE = sys.argv[3] if len(sys.argv) > 3 else "bid_extra"
    deals = int(sys.argv[1]) if len(sys.argv) > 1 else 200
    diffs_pts = []
    diffs_delta = []
    used = 0
    for d in range(deals * 3):
        if used >= deals:
            break
        seed = 700000 + d
        base = drive(seed)
        if base is None or base["fork"] is None:
            continue
        fork = base["fork"]
        if not (isinstance(fork, tuple) and fork[0] == "opportunity"):
            continue
        _, seat, team, step = fork

        a = drive(seed, step, "counter")
        b = drive(seed, step, "pass")
        if a is None or b is None:
            continue
        used += 1
        diffs_pts.append(a["pts"][team] - b["pts"][team])
        da = a["delta"] if a["win_team"] == team else -a["delta"]
        db = b["delta"] if b["win_team"] == team else -b["delta"]
        diffs_delta.append(da - db)

    if not diffs_pts:
        print("没有找到可用的反主机会")
        return 1
    import statistics as st
    n = len(diffs_pts)
    m = st.mean(diffs_pts)
    ci = 1.96 * st.pstdev(diffs_pts) / (n ** 0.5)
    md = st.mean(diffs_delta)
    cid = 1.96 * st.pstdev(diffs_delta) / (n ** 0.5)
    pos = sum(1 for x in diffs_pts if x > 0)
    neg = sum(1 for x in diffs_pts if x < 0)
    print("=" * 70)
    label = ("AI 本来就会反" if WHICH == "ai_counter" else "AI 本来会放弃")
    if FORK_PHASE == "bid_initial":
        label += " · bid_initial（只换主牌色、**不换底**）"
    else:
        label += " · bid_extra（反主 + **换底**）"
    print("反主的单次决策反事实 —— %s（%d 局）" % (label, n))
    print("=" * 70)
    print("  反主方那一队的得分差：%+.1f 分 ±%.1f（正 = 反了更好）" % (m, ci))
    print("  反主方那一队的升级增量差：%+.3f ±%.3f" % (md, cid))
    print("  反了更好 %d 局，更差 %d 局，持平 %d 局" % (pos, neg, n - pos - neg))
    return 0


if __name__ == "__main__":
    sys.exit(main())
