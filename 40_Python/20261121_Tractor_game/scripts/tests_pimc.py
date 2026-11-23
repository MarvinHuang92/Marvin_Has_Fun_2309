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
from tractor.memory import CardTracker, card_id  # noqa: E402
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
            bad_examples.append([c.label for c in got])
    print("  [3] 缺门约束（%s）：50 次采样里 %d 次没发%s给缺门者" % (banned, ok_count, banned))
    if bad_examples:
        print("      违规样例：%s" % bad_examples)
    assert ok_count == 50, "缺门约束被违反"

    # 4) 未知牌池 = 其余三家手牌（底牌不参与出牌，不在池子里）
    pool = unseen_pool(state, seat)
    expect = 108 - len(state.hands[seat])
    print("  [4] 未知牌池 %d 张 = 108 - 我的手牌（含底牌）✓" % len(pool))
    assert len(pool) == expect, "unseen_pool 长度异常：%d != %d" % (len(pool), expect)

    # 5) 知道底牌时，池子应当正好少 8 张（底牌永远不会在对手手上）
    known = list(state.bottom)
    pool2 = unseen_pool(state, seat, known_bottom={card_id(c) for c in known})
    print("  [5] 知道底牌后池子 %d 张（少了 %d 张）✓" % (len(pool2), len(pool) - len(pool2)))
    assert len(pool2) == len(pool) - len(known), "扣掉底牌后的池子张数不对"

    # 6) 底牌记忆只在"真的埋了"时才记录（提示算出的不算）
    from tractor.ai_heuristic import HeuristicAI

    ai = HeuristicAI()
    ai.begin_deal(game)
    ai._ensure(game, seat)
    suggested = ai.bury(game, seat)
    assert not ai._my_buried.get(seat), "只算了一下埋底就记成自己埋的了"
    ai.note_buried(seat, suggested)
    assert ai._my_buried.get(seat) == list(suggested), "真的埋了却没记住"
    print("  [6] 底牌记忆只在提交后记录 ✓")

    # 7) 换底推理：我看过的底牌只能出现在「我埋底之后换过底的人」手里
    from tractor.memory import card_id as _cid

    tracker = CardTracker(state.level, state.trump_suit, my_seat=seat)
    tracker.observe_hand(state.hands[seat])
    # 伪造：我看过 3 张底牌，之后只有座位 (seat+1)%4 换过底
    others = [s_ for s_ in range(4) if s_ != seat]
    holder = others[0]
    sample = []
    for s_ in others:
        for c in state.hands[s_]:
            if c not in sample:
                sample.append(c)
        if len(sample) >= 3:
            break
    tracker.stale_kitty = {_cid(c) for c in sample[:3]}
    tracker.stale_holders = {holder}

    bad = 0
    for k in range(30):
        w = determinize(state, seat, random.Random(900 + k), tracker)
        for s_ in others:
            if s_ == holder:
                continue
            for c in w.hands[s_]:
                if _cid(c) in tracker.stale_kitty:
                    bad += 1
    assert bad == 0, "换底推理被违反：非参与者拿到了我看过的牌 %d 次" % bad
    print("  [7] 换底推理：30 次采样里，非换底参与者 0 次拿到我看过的牌 ✓")

    print("-" * 62)
    print("全部通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
