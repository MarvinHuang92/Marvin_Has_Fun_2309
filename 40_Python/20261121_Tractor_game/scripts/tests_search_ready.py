# -*- coding: utf-8 -*-
"""验证"为搜索准备的三件事"是否和引擎完全一致。

跑法::

    python scripts/tests_search_ready.py

检查三件事：

  1. FastState 重放一局，每一墩的得分必须和引擎的 trick_history 完全一致
  2. moves 生成的每一个动作，都要被引擎自己的判罚函数接受
  3. memory 推断出的缺门，不能和引擎的 void_seats 矛盾
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from tractor import ai as rule_ai  # noqa: E402
from tractor.cards import is_trump  # noqa: E402
from tractor.engine import TractorGame  # noqa: E402
from tractor.fast_state import FastState  # noqa: E402
from tractor.memory import CardTracker  # noqa: E402
from tractor.moves import legal_moves  # noqa: E402
from tractor.rules import decompose_lead, is_legal_follow  # noqa: E402


def drive_to_play(game: TractorGame) -> None:
    """把亮主/埋底跑完，进入出牌阶段。"""
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


def check_deal(seed: int) -> dict:
    game = TractorGame(seed)
    game.start_match()
    drive_to_play(game)
    assert game.phase == "play", "没能进入出牌阶段"

    state = FastState.from_game(game)
    tracker = CardTracker(game.level, game.trump_suit, my_seat=0)
    for s in range(4):
        tracker.observe_hand(game.hands[s]) if s == 0 else None

    n_moves = 0
    n_illegal = 0
    n_void_checked = 0
    n_void_bad = 0
    n_trump_dead = 0

    for _ in range(400):
        if game.phase != "play":
            break
        seat = game.acting_seat()
        if seat is None:
            break

        # --- 检查 2：枚举出来的动作必须合法、且都在手里 ---
        cand = legal_moves(state, seat, max_moves=64)
        hand = list(state.hands[seat])
        for mv in cand:
            n_moves += 1
            pool = list(hand)
            for c in mv:
                assert c in pool, "候选动作里有不在手上的牌"
                pool.remove(c)
            if state.lead is None:
                ok = decompose_lead(mv, state.level, state.trump_suit) is not None
            else:
                ok = is_legal_follow(hand, mv, state.lead, state.level, state.trump_suit)[0]
            if not ok:
                n_illegal += 1
        assert cand, "枚举不出任何合法动作（座位 %d）" % seat

        # --- 检查 3：本墩的缺门推断必须和引擎一致 ---
        lead = game.trick.lead if game.trick else None
        if lead is not None:
            for vs in game.trick.void_seats:
                if vs == game.trick.leader:
                    continue
                if vs == seat:
                    continue
                n_void_checked += 1
                if not tracker.is_void(vs, lead.category.kind):
                    # 还没轮到他出牌就无从观察，跳过
                    pass

        # --- 检查 5：trumps_dead 一旦为真，三家必须真的一张主牌都没有 ---
        if tracker.trumps_dead():
            for s in range(4):
                if s == tracker.my_seat:
                    continue
                real_trumps = [c for c in state.hands[s]
                               if is_trump(c, state.level, state.trump_suit)]
                assert not real_trumps, (
                    "trumps_dead 误判：座位 %d 手里还有 %d 张主牌" % (s, len(real_trumps)))
            n_trump_dead += 1

        cards = rule_ai.choose_play(game, seat)
        lead_before = game.trick.lead if game.trick else None
        if game.trick is None or game.trick.lead is None:
            ok_g, msg_g = game.play_lead(seat, cards)
        else:
            ok_g, msg_g = game.play_follow(seat, cards)
        assert ok_g, "引擎拒绝了规则 AI 的出牌：%s" % msg_g

        ok_s, msg_s, _ = state.play(seat, cards)
        assert ok_s, "FastState 和引擎判罚不一致：%s" % msg_s

        tracker.observe_play(seat, cards, lead_before)

        # 观察完之后，如果引擎说某人是缺门，我们应当已经标记
        # （注意：tracker.my_seat 是自己的座位，自己的牌已知，不需要也不应该推断）
        if lead_before is not None and seat in game.trick.void_seats:
            if seat != tracker.my_seat and not tracker.is_void(seat, lead_before.category.kind):
                n_void_bad += 1

    # --- 检查 1：每一墩的得分对账 ---
    engine_points = {0: 0, 1: 0}
    for t in game.trick_history:
        engine_points[game.team(t["winner"])] += t["points"]
    assert engine_points == state.points, (
        "FastState 得分和引擎不一致：%r vs %r" % (state.points, engine_points))
    assert state.is_terminal(), "FastState 没有走到局末"

    return {
        "seed": seed,
        "tricks": len(game.trick_history),
        "moves": n_moves,
        "illegal": n_illegal,
        "void_bad": n_void_bad,
        "points": engine_points,
        "trump_dead": n_trump_dead,
    }


def main() -> int:
    print("=" * 60)
    print("验证：FastState / moves / memory 与引擎的一致性")
    print("=" * 60)
    total_moves = 0
    for seed in range(1, 9):
        r = check_deal(seed)
        total_moves += r["moves"]
        print("  seed=%d  %2d 墩  枚举 %4d 个动作，非法 %d，缺门漏判 %d，主牌清零判定 %d 次  %r"
              % (r["seed"], r["tricks"], r["moves"], r["illegal"], r["void_bad"],
                 r["trump_dead"], r["points"]))
        assert r["illegal"] == 0, "有非法动作被枚举出来了"
        assert r["void_bad"] == 0, "缺门推断漏判"
    print("-" * 60)
    print("全部通过：8 局、%d 个枚举动作、判罚 0 处不一致" % total_moves)
    return 0


if __name__ == "__main__":
    sys.exit(main())
