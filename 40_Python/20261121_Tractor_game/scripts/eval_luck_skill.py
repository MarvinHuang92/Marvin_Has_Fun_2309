# -*- coding: utf-8 -*-
"""运气 vs 会打：按开局牌力分桶，看 AI 到底是"牌好"还是"会打"。

## 三个量

对每一局，在**底牌扣好、开打的那一刻**算：

- **牌力差 `edge`**：两队手牌的静态强度之差（可解释的手写指标，正数=我方牌好）
- **期望差 `expected`**：价值网络对这个局面的预测（我队 − 对方，单位是分）
- **实际差 `actual`**：这局打完的真实分差

于是：

```
residual = actual − expected      # 超出"牌力应有表现"的部分 = 会不会打
```

按 `edge` 分桶就能看出：
- 顺风局（edge 大）打得怎么样
- 逆风局（edge 小）能不能翻
- 平均 residual 为正 = 超出牌力预期（会打）；为负 = 低于预期

跑法::

    python scripts/eval_luck_skill.py                       # 会记牌 vs 会推理
    python scripts/eval_luck_skill.py adv heuristic 200     # 指定双方和局数
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from tractor import value_net  # noqa: E402
from tractor.ai_select import AiEngine  # noqa: E402
from tractor.cards import is_trump  # noqa: E402
from tractor.engine import TractorGame  # noqa: E402
from tractor.fast_state import FastState  # noqa: E402


def hand_score(state, team):
    """静态牌力：可解释的手写指标（不含任何 AI 判断）。"""
    total = 0.0
    for seat in range(4):
        if state.team(seat) != team:
            continue
        for c in state.hands[seat]:
            if is_trump(c, state.level, state.trump_suit):
                total += 2.0
                if c.rank == 16:
                    total += 6.0
                elif c.rank == 15:
                    total += 5.0
                elif c.rank == state.level:
                    total += 4.0
                elif c.rank == 2:
                    total += 3.0
            else:
                if c.rank == 14:
                    total += 3.0
                elif c.rank == 13:
                    total += 2.0
            if c.rank == 5:
                total += 0.5
            elif c.rank in (10, 13):
                total += 1.0
    return total


def drive_to_play(game, ai0, ai1):
    for _ in range(600):
        if game.phase == "play":
            return True
        seat = game.acting_seat()
        if seat is None:
            return False
        ai = ai0 if game.team(seat) == 0 else ai1
        if game.phase in ("bid_initial", "bid_extra"):
            game.submit_bid(seat, ai.bid(game, seat))
        elif game.phase in ("bury_initial", "bury_extra"):
            cards = ai.bury(game, seat)
            ok, _ = game.submit_bury(seat, cards)
            if ok:
                ai.note_buried(seat, cards)
        else:
            return False
    return True


def play_deal(seed, ai0, ai1):
    game = TractorGame(seed)
    game.start_match()
    ai0.begin_deal(game)
    ai1.begin_deal(game)
    if not drive_to_play(game, ai0, ai1):
        return None

    state = FastState.from_game(game)
    edge = hand_score(state, 0) - hand_score(state, 1)
    net = value_net.active()
    expected = (net.predict(state, 0) - net.predict(state, 1)) if net else 0.0

    for _ in range(500):
        if state.is_terminal():
            break
        seat = state.current_player
        ai = ai0 if state.team(seat) == 0 else ai1
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

    zt = state.team(state.zhuang)
    pts = {zt: game.declarer_points, 1 - zt: game.defender_points}
    actual = pts[0] - pts[1]
    return {"edge": edge, "expected": expected, "actual": actual,
            "zhuang": zt, "kind": game.deal_result.get("kind", "") if game.deal_result else ""}


def main():
    a = sys.argv[1] if len(sys.argv) > 1 else "heuristic"
    b = sys.argv[2] if len(sys.argv) > 2 else "adv"
    deals = int(sys.argv[3]) if len(sys.argv) > 3 else 150

    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    value_net.load_active(os.path.join(root, "models", "value_v4.json"))

    ai0 = AiEngine(a)
    ai1 = AiEngine(b)
    rows = []
    for i in range(deals):
        r = play_deal(700000 + i, ai0, ai1)
        if r is not None:
            rows.append(r)
    if not rows:
        print("没有有效对局")
        return 1

    import statistics as st
    print("=" * 78)
    print("%s（team0） vs %s（team1），%d 局" % (a, b, len(rows)))
    print("=" * 78)
    print("  牌力差 edge   ：均值 %+.1f" % st.mean(r["edge"] for r in rows))
    print("  期望差 expected：均值 %+.1f 分" % st.mean(r["expected"] for r in rows))
    print("  实际差 actual  ：均值 %+.1f 分" % st.mean(r["actual"] for r in rows))
    res = [r["actual"] - r["expected"] for r in rows]
    ci = 1.96 * st.pstdev(res) / (len(res) ** 0.5)
    print("  **残差 residual = %.1f ±%.1f**（正数 = 超出牌力预期，即会打）"
          % (st.mean(res), ci))

    rows.sort(key=lambda r: r["edge"])
    q = len(rows) // 4
    print("-" * 78)
    print("  按牌力差分桶（从逆风到顺风）：")
    print("  %-10s %5s %8s %9s %9s %8s" %
          ("桶", "局数", "牌力差", "期望差", "实际差", "残差"))
    labels = ["逆风(最差)", "偏弱", "偏强", "顺风(最好)"]
    for i in range(4):
        chunk = rows[i * q:(i + 1) * q] if i < 3 else rows[3 * q:]
        if not chunk:
            continue
        print("  %-10s %5d %8.1f %9.1f %9.1f %8.1f" % (
            labels[i], len(chunk),
            st.mean(r["edge"] for r in chunk),
            st.mean(r["expected"] for r in chunk),
            st.mean(r["actual"] for r in chunk),
            st.mean(r["actual"] - r["expected"] for r in chunk)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
