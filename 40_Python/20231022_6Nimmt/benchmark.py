# -*- coding: utf-8 -*-
"""两两对战矩阵：现在这几个选手到底谁强谁弱

评测口径与 evaluate.py 完全一致：固定种子、同一副牌双方轮座、不写文件。
配置沿用优化记录里的最强设置：SEARCH_ROLLOUTS=24、HYBRID_TOP_K=3、
extra_feature_mode=teacher_scores。

用法：
    python benchmark.py                 # 每对 1000 局（±3.1 个点）
    python benchmark.py 3000            # 每对 3000 局（±1.8 个点）
"""

import contextlib
import io
import sys
import time

import game_6nimmt

SEED_BASE = 950000

# (显示名, 玩家类型, 模型文件)
CONTESTANTS = [
    ("hybrid K3M24", "hybrid", "model_searchc_25k400_ts.pth"),
    ("search M24", "search", None),
    ("scorepolicy", "scorepolicy", "model_searchc_25k400_ts.pth"),
    ("advanced_ai", "advanced_ai", None),
]


def play(a, b, games):
    """a 方对 b 方，返回 (a 胜率, 半宽, a 牛头, b 牛头)"""
    name_a, type_a, model_a = a
    name_b, type_b, model_b = b
    pairs = max(1, games // 2)
    wins = 0
    bh_a = bh_b = 0
    with contextlib.redirect_stdout(io.StringIO()):
        for i in range(pairs):
            seed = SEED_BASE + i
            for a_seat in (0, 1):
                types = [type_a, type_b] if a_seat == 0 else [type_b, type_a]
                paths = [model_a, model_b] if a_seat == 0 else [model_b, model_a]
                r = game_6nimmt.run_game(2, seed, False, types, paths, record_to_file=False)
                bh = r["bullheads"]
                if r["winner"] == a_seat:
                    wins += 1
                bh_a += bh[a_seat]
                bh_b += bh[1 - a_seat]
    total = pairs * 2
    p = 1.0 * wins / total
    half = 1.96 * (p * (1.0 - p) / total) ** 0.5
    return p, half, bh_a, bh_b, total


def main():
    games = int(sys.argv[1]) if len(sys.argv) > 1 else 1000
    game_6nimmt.extra_feature_mode = "teacher_scores"
    game_6nimmt.normalize_state = False
    game_6nimmt.policy_sample = False          # scorepolicy 评测时取 argmax
    game_6nimmt.SEARCH_ROLLOUTS = 24
    game_6nimmt.HYBRID_TOP_K = 3

    print("配置：SEARCH_ROLLOUTS=%d  HYBRID_TOP_K=%d  mode=%s  每对 %d 局"
          % (game_6nimmt.SEARCH_ROLLOUTS, game_6nimmt.HYBRID_TOP_K,
             game_6nimmt.extra_feature_mode, games))
    print()

    names = [c[0] for c in CONTESTANTS]
    matrix = {}
    results = []
    t0 = time.time()
    for i in range(len(CONTESTANTS)):
        for j in range(i + 1, len(CONTESTANTS)):
            p, half, bh_a, bh_b, total = play(CONTESTANTS[i], CONTESTANTS[j], games)
            matrix[(i, j)] = (p, half)
            matrix[(j, i)] = (1 - p, half)
            results.append((names[i], names[j], p, half, bh_a, bh_b, total))
            print("  %-14s vs %-14s  A 胜率 %5.1f%% ±%.1f   牛头 %4.1f%%  （累计 %.0fs）"
                  % (names[i], names[j], 100 * p, 100 * half,
                     100.0 * bh_a / max(bh_a + bh_b, 1), time.time() - t0))
            sys.stdout.flush()

    print()
    print("=" * 78)
    print("胜率矩阵（行 = A，列 = B；格子是 A 的胜率）")
    print("=" * 78)
    print("  %-14s" % "" + "".join("%16s" % n for n in names))
    for i, n in enumerate(names):
        cells = []
        for j in range(len(names)):
            if i == j:
                cells.append("%16s" % "—")
            else:
                p, half = matrix[(i, j)]
                cells.append("%15s" % ("%.1f±%.1f" % (100 * p, 100 * half)))
        print("  %-14s" % n + "".join(cells))
    print()
    print("  （±是 95% 置信区间半宽；格子里比 ± 小的差距不要当结论）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
