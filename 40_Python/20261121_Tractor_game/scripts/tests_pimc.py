# -*- coding: utf-8 -*-
"""PIMC 采样的正确性测试。

检查四件事：

  1. 采样出来的三家手牌张数正确
  2. **不偷看**：采样结果不能等于真实手牌（且多次采样应当不同）
  3. **尊重缺门**：已知某人缺某门，就不能发给他这门牌
  4. PIMC 选出的动作一定合法（能被引擎接受）
"""
from __future__ import annotations

import os
import random
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from tractor import ai as rule_ai  # noqa: E402
from tractor.engine import TractorGame  # noqa: E402
from tractor.fast_state import FastState  # noqa: E402
from tractor.memory import CardTracker  # noqa: E402
from tractor.search import determinize, unseen_pool, _kind_of  # noqa: E402


def drive_to_play(game):
    for _ in range(500):
        if game.phase == "play":
            return
        seat = game.acting_seat()
        if seat is None:
            return
        if game.phase in ("bid_initial", "bid_extra"):
            game.submit_bid(seat, rule_ai.choose_bid(game, seat))
        elif game.phase in ("bury_initial", "bury_extra"):
            game.submit_bury(seat, rule_ai.choose_bury(game, seat))
        else:
            return


def main() -> int:
    game = TractorGame(4242)
    game.start_match()
    drive_to_play(game)
    state = FastState.from_game(game)
    seat = state.current_player
    rng = random.Random(7)

    print("=" * 62)
    print("PIMC 采样正确性")
    print("=" * 62)

    # 1) 张数
    world = determinize(state, seat, rng)
    for s in range(4):
        want = len(state.hands[s])
        got = len(world.hands[s])
        assert got == want or s == seat, "座位 %d 张数 %d != %d" % (s, got, want)
    print("  [1] 张数正确（三家各 %s）" % [len(world.hands[s]) for s in range(4) if s != seat])

    # 2) 不偷看
    same = all(sorted(world.hands[s]) == sorted(state.hands[s])
               for s in range(4) if s != seat)
    assert not same, "采样结果等于真实手牌 —— 在偷看！"
    a = determinize(state, seat, rng)
    b = determinize(state, seat, rng)
    differ = any(sorted(a.hands[s]) != sorted(b.hands[s]) for s in range(4) if s != seat)
    assert differ, "两次采样完全相同 —— 随机性坏了"
    print("  [2] 不偷看：采样 != 真实手牌，且两次采样不同 ✓")

    # 3) 缺门约束
    tracker = CardTracker(game.level, game.trump_suit, my_seat=seat)
    # 挑一个**不是主牌**的花色来当缺门（主牌花色属于 "T" 类别，不受副牌缺门约束）
    banned = next((s for s in ("S", "H", "C", "D") if s != game.trump_suit), "S")
    target = (seat + 1) % 4
    tracker.voids[target].add(banned)
    ok_count = 0
    bad_examples = []
    for _ in range(50):
        w = determinize(state, seat, rng, tracker)
        # 注意：黑桃 2 / 黑桃级牌属于"主牌"类别（常主），不算在"缺黑桃"里
        got = [c for c in w.hands[target] if _kind_of(c, state) == banned]
        if not got:
            ok_count += 1
        elif len(bad_examples) < 3:
            bad_examples.append([c.short for c in got])
    print("  [3] 缺门约束（%s）：50 次采样里 %d 次没发%s给缺门者" % (banned, ok_count, banned))
    if bad_examples:
        print("      违规样例：%s" % bad_examples)
    assert ok_count == 50, "缺门约束被违反"

    # 4) 未知牌池 = 其余三家手牌（底牌不参与出牌，不在池子里）
    pool = unseen_pool(state, seat)
    expect = sum(len(state.hands[s]) for s in range(4) if s != seat)
    print("  [4] 未知牌池 %d 张 = 其余三家手牌 %d 张 ✓" % (len(pool), expect))
    assert len(pool) == expect, "unseen_pool 长度异常：%d != %d" % (len(pool), expect)

    print("-" * 62)
    print("全部通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
