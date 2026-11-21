# -*- coding: utf-8 -*-
"""双明手基准：求解器性能 + "AI 离完美差多远"。

两个模式：

  perf  求解器在尾局的耗时/节点/是否精确（默认）
  regret **当裁判用**：把一局打到只剩 N 墩 → 对每个候选动作做双明手精确估值
        → 最优值减去 AI 所选动作的值 = 这一步的后悔值

跑法::

    python scripts/dd_bench.py --mode perf --deals 2 --time 8
    python scripts/dd_bench.py --mode regret --tricks 3 --deals 20 --time 10
"""
from __future__ import annotations

import argparse
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from tractor import ai as rule_ai  # noqa: E402
from tractor.ai_heuristic import HeuristicAI  # noqa: E402
from tractor.dds import DoubleDummySolver  # noqa: E402
from tractor.engine import TractorGame  # noqa: E402
from tractor.fast_state import FastState  # noqa: E402
from tractor.memory import CardTracker  # noqa: E402


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


def plays_left(state: FastState) -> int:
    return sum(len(state.hands[s]) for s in range(4))


def run_until(state: FastState, ai: HeuristicAI, tracker: CardTracker, stop_plays: int) -> None:
    while plays_left(state) > stop_plays:
        seat = state.current_player
        lead = state.lead
        mv = ai.choose(state, seat)
        ok, msg, _ = state.play(seat, mv)
        if not ok:
            raise RuntimeError("出牌失败：%s" % msg)
        tracker.observe_play(seat, mv, lead)


def playout(state: FastState, ai: HeuristicAI, tracker: CardTracker, team: int) -> float:
    """从当前局面让 AI 打到底，返回 team 的净得分。"""
    before = dict(state.points)
    while not state.is_terminal():
        seat = state.current_player
        lead = state.lead
        mv = ai.choose(state, seat)
        ok, msg, _ = state.play(seat, mv)
        if not ok:
            raise RuntimeError("出牌失败：%s" % msg)
        tracker.observe_play(seat, mv, lead)
    mine = state.points[team] - before[team]
    theirs = state.points[1 - team] - before[1 - team]
    return float(mine - theirs)


def mode_perf(args) -> int:
    trick_list = [args.tricks] if args.tricks else [3, 4, 5, 6]
    print("=" * 74)
    print("双明手求解器：尾局精确求解（四家手牌全公开）")
    print("=" * 74)
    print("  %6s %5s %8s %9s %9s %8s" % ("剩余墩", "样例", "用时(s)", "节点数", "深度", "精确?"))
    for tricks in trick_list:
        stop_plays = tricks * 4
        times, nodes, depths, exacts = [], [], [], []
        for d in range(args.deals):
            game = TractorGame(5000 + d * 17 + tricks)
            game.start_match()
            drive_to_play(game)
            state = FastState.from_game(game)
            ai = HeuristicAI()
            tracker = CardTracker(game.level, game.trump_suit, my_seat=-1)
            run_until(state, ai, tracker, stop_plays)

            solver = DoubleDummySolver(time_limit=args.time, node_limit=args.nodes)
            t0 = time.perf_counter()
            res = solver.solve(state, state.current_player)
            dt = time.perf_counter() - t0
            times.append(dt)
            nodes.append(res.nodes)
            depths.append(res.depth)
            exacts.append(res.exact)
            print("  %6d %5d %8.2f %9d %9d %8s  value=%+.0f"
                  % (tricks, d, dt, res.nodes, res.depth, "是" if res.exact else "否", res.value))
        print("  %6d %5s %8.2f %9.0f %9.1f %8.0f%%" % (
            tricks, "均值", sum(times) / len(times), sum(nodes) / len(nodes),
            sum(depths) / len(depths), 100.0 * sum(exacts) / len(exacts)))
        print()
    return 0


def mode_regret(args) -> int:
    """单步后悔值：对手保持完美，只把我方这一步换成 AI 的选择。

    为什么不用"AI 打到底"来比：那样对手也是这个弱 AI，对手失误时我方分数会
    超过"双方都完美"的双明手值，出现负差。衡量 AI 离完美多远，必须只换一步。
    """
    from tractor.moves import legal_moves

    stop_plays = args.tricks * 4
    print("=" * 74)
    print("双明手当裁判：AI 在最后 %d 墩的单步后悔值" % args.tricks)
    print("=" * 74)
    regrets, n_moves_total = [], 0
    for d in range(args.deals):
        game = TractorGame(7000 + d)
        game.start_match()
        drive_to_play(game)
        state = FastState.from_game(game)
        ai = HeuristicAI()
        tracker = CardTracker(game.level, game.trump_suit, my_seat=-1)
        run_until(state, ai, tracker, stop_plays)

        seat = state.current_player
        team = state.team(seat)
        cand = legal_moves(state, seat, max_moves=32)
        if not cand:
            continue
        values = {}
        for mv in cand:
            child = state.clone()
            ok, _, res = child.play(seat, mv)
            if not ok:
                continue
            gain = 0.0
            if res is not None:
                gain = float(res.points) if FastState.team(res.winner) == team else -float(res.points)
            if child.is_terminal():
                values[tuple(sorted(mv))] = gain
                continue
            solver = DoubleDummySolver(time_limit=args.time, node_limit=args.nodes)
            r = solver.solve(child, child.current_player, team=team)
            values[tuple(sorted(mv))] = gain + r.value
        if not values:
            continue
        best = max(values.values())
        ai_mv = ai.choose(state, seat)
        ai_val = values.get(tuple(sorted(ai_mv)), best)
        regrets.append(best - ai_val)
        n_moves_total += len(values)
        print("  #%2d  最优 %+6.0f  AI %+6.0f  后悔 %+5.0f   （%d 个候选）"
              % (d, best, ai_val, best - ai_val, len(values)))
    if regrets:
        m = sum(regrets) / len(regrets)
        sd = (sum((g - m) ** 2 for g in regrets) / (len(regrets) - 1)) ** 0.5 if len(regrets) > 1 else 0.0
        ci = 1.96 * sd / (len(regrets) ** 0.5) if len(regrets) > 1 else 0.0
        print("-" * 74)
        print("  平均后悔 %+0.2f ±%.2f 分/决策（正的 = AI 比完美少拿）" % (m, ci))
        print("  每步候选数 %.1f，最大后悔 %.0f" % (n_moves_total / len(regrets), max(regrets)))
    return 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", default="perf", choices=["perf", "regret"])
    ap.add_argument("--tricks", type=int, default=0, help="剩余墩数（perf 模式 0=扫 3~6）")
    ap.add_argument("--deals", type=int, default=3)
    ap.add_argument("--time", type=float, default=8.0)
    ap.add_argument("--nodes", type=int, default=3000000)
    args = ap.parse_args()
    if args.mode == "perf":
        return mode_perf(args)
    if not args.tricks:
        args.tricks = 3
    return mode_regret(args)


if __name__ == "__main__":
    sys.exit(main())
