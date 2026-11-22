# -*- coding: utf-8 -*-
"""深搜索选出来的走法，真的比浅搜索的好吗？

对每个局面：
  1. mv_fast = 搜索 0.1 秒选出的走法
  2. mv_deep = 搜索 10 秒选出的走法
  3. 用**同一个参照**（从走完之后的局面再搜 2 秒）给这两手估价
  4. 比较：如果 mv_deep 明显更值，说明深搜索确实更强（之前 A/B 打平只是样本不够）；
     如果两者差不多，说明深搜索只是在"更深地收敛到一个有偏的估价上"。

跑法：python scripts/deep_compare.py 20
"""
from __future__ import annotations

import os
import random
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from tractor import value_net  # noqa: E402
from tractor.fast_state import FastState  # noqa: E402
from tractor.search import Searcher, determinize  # noqa: E402

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from conv_probe import make_positions  # noqa: E402

REF_BUDGET = 2.0
FAST = 0.1
DEEP = 10.0


def value_after(world, seat, move, ref_budget=REF_BUDGET):
    """走完这一手之后，从 `seat` 的队伍视角看，这个局面的价值。"""
    w = world.clone()
    ok, msg, _ = w.play(seat, move)
    if not ok:
        return None
    if w.is_terminal():
        # 终局：直接用真实得分
        return None
    nxt = w.current_player
    s = Searcher(depth=40, time_limit=ref_budget, node_limit=10 ** 7,
                 eval_kind="value")
    _, val = s.choose(w, nxt)
    if val is None:
        return None
    mine = w.team(seat) == w.team(nxt)
    return val if mine else -val


def main():
    count = int(sys.argv[1]) if len(sys.argv) > 1 else 20
    model = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                         "..", "models", "value_v4.json")
    value_net.load_active(model)
    positions = make_positions(count)

    print("=" * 70)
    print("深搜索的走法真的更好吗？（%d 个局面，参照预算 %.0f 秒）"
          % (len(positions), REF_BUDGET))
    print("=" * 70)

    diffs = []
    same = 0
    for i, pos in enumerate(positions):
        seat = pos.current_player
        world = determinize(pos, seat, random.Random(777 + i), tracker=None)

        fast = Searcher(depth=40, time_limit=FAST, node_limit=10 ** 7,
                        eval_kind="value")
        mv_fast, _ = fast.choose(world.clone(), seat)
        deep = Searcher(depth=40, time_limit=DEEP, node_limit=10 ** 7,
                        eval_kind="value")
        mv_deep, _ = deep.choose(world.clone(), seat)
        if mv_fast is None or mv_deep is None:
            continue

        k_fast = tuple(sorted(c.short for c in mv_fast))
        k_deep = tuple(sorted(c.short for c in mv_deep))
        if k_fast == k_deep:
            same += 1
            print("  局面%2d 两者选同一手（跳过）" % i)
            continue

        v_fast = value_after(world, seat, mv_fast)
        v_deep = value_after(world, seat, mv_deep)
        if v_fast is None or v_deep is None:
            continue
        d = v_deep - v_fast
        diffs.append(d)
        print("  局面%2d  0.1s的手=%.1f  10s的手=%.1f  差 %+.1f"
              % (i, v_fast, v_deep, d))

    print("-" * 70)
    print("两者选同一手：%d 个" % same)
    if diffs:
        import statistics as st
        pos = sum(1 for d in diffs if d > 0.5)
        neg = sum(1 for d in diffs if d < -0.5)
        print("可比局面 %d 个：深搜索更好 %d 个，更差 %d 个，持平 %d 个"
              % (len(diffs), pos, neg, len(diffs) - pos - neg))
        print("平均差 %+.2f 分（正数 = 深搜索的手更值）  中位数 %+.2f"
              % (st.mean(diffs), st.median(diffs)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
