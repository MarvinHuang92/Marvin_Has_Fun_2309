"""阶段 3-②：PIMC（Perfect Information Monte Carlo）多世界采样。

思路（桥牌界的标准做法）：

  1. 按**公开信息**采样 N 个"可能的世界"（`determinize`，尊重缺门约束）
  2. 每个世界做一次限深度 alpha-beta
  3. 把**根节点每个候选动作的估值跨世界求平均**，选平均值最高的

为什么用"平均"而不是"投票"：搜索过程中根节点本来就把每个候选都估过一遍了
（`Searcher.root_values`），所以平均不额外花算力，而且比投票保留了更多信息
（"某个动作在 8 个世界里 7 次第二、1 次第一"和"1 次第一、7 次最差"是完全不同的）。

## 为什么这比"加深搜索"更划算

阶段的实测告诉我们：100 ms 预算下搜索只能看到 1.5 墩。
同样 100 ms，拆成"4 个世界 × 25 ms"通常比"1 个世界 × 100 ms"更准 ——
因为 4 个世界多覆盖了隐藏信息，而 25 ms 和 100 ms 在 1 墩深度上差别不大。

## 已知的 PIMC 理论缺陷（桥牌界叫 "strategy fusion"）

采样出来的世界都是"完整信息"的，搜索在每个世界里都打得像上帝；
但真实对手不知道我的牌，会把"本来应该被惩罚的诈唬"错判成好棋。
表现为：PIMC 在**残局**很强，在**需要长期欺骗/保留**的中盘会偏保守。
这也是为什么 AlphaZero 那类方法要用 MCTS + 信念，而不是纯 PIMC。
"""
from __future__ import annotations

import random
from typing import Dict, List, Optional, Tuple

from .fast_state import FastState
from .search import Searcher, _move_key, determinize


class PIMCAI:
    name = "pimc"

    def __init__(self, depth: int = 40, time_limit: float = 0.03,
                 samples: int = 4, node_limit: int = 60000,
                 seed: int = 20261122) -> None:
        self.searcher = Searcher(depth=depth, time_limit=time_limit, node_limit=node_limit)
        self.samples = max(1, samples)
        self.rng = random.Random(seed)
        self.stats = {"calls": 0, "worlds": 0, "nodes": 0}

    def choose(self, state: FastState, seat: int, tracker=None) -> List:
        totals: Dict[Tuple, float] = {}
        counts: Dict[Tuple, int] = {}
        moves: Dict[Tuple, List] = {}

        for _ in range(self.samples):
            world = determinize(state, seat, self.rng, tracker)
            self.searcher.choose(world, seat)
            self.stats["worlds"] += 1
            for key, val in self.searcher.root_values.items():
                totals[key] = totals.get(key, 0.0) + val
                counts[key] = counts.get(key, 0) + 1
                moves.setdefault(key, self.searcher.root_moves[key])

        self.stats["calls"] += 1
        if not totals:                       # 一个世界都没搜出来（时间太紧）
            from . import moves as moves_mod
            mv = moves_mod.any_legal_move(state, seat)
            return mv if mv else list(state.hands[seat])[:1]

        best_key = max(totals, key=lambda k: totals[k] / counts[k])
        return moves[best_key]
