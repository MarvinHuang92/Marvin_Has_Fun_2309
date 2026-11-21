"""阶段 3 骨架：带限深度搜索的策略（PIMC 单样本版）。

和 `ai_heuristic.py` 的区别：决策时先把未知牌随机分配成一个"世界"，
再在这个世界上做限深度 alpha-beta（`search.Searcher`），最后由估价函数截断。

现在只用了 **1 个世界**（单样本），下一步的 PIMC 会采样多个世界再聚合。
"""
from __future__ import annotations

import random
from typing import List, Optional

from .fast_state import FastState
from .search import Searcher, determinize


class SearchAI:
    name = "search"

    def __init__(self, depth: int = 10, time_limit: float = 0.05,
                 node_limit: int = 60000, seed: int = 20261122) -> None:
        self.searcher = Searcher(depth=depth, time_limit=time_limit, node_limit=node_limit)
        self.rng = random.Random(seed)
        self.stats = {"calls": 0, "nodes": 0, "time": 0.0}

    def choose(self, state: FastState, seat: int) -> List:
        world = determinize(state, seat, self.rng)
        mv, _ = self.searcher.choose(world, seat)
        self.stats["calls"] += 1
        self.stats["nodes"] += self.searcher.nodes
        if mv is None:
            return list(state.hands[seat])[:1]
        return mv
