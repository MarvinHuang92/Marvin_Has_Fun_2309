# -*- coding: utf-8 -*-
"""第十轮诊断：搜索型玩家的决策有多"可学"？

做法：同一个局面下把 rollout 分成前后两半，各算一次最优动作，
比较两半是否选中同一张牌。这个一致率就是**标签自身的不确定性**
（搜索每次都要随机采对手手牌，采样不同就可能改主意）。

用法：
  python search_noise.py [局数] [rollout 总数] [起始种子]
  例：python search_noise.py 600 24 980000
"""

import contextlib
import io
import sys

import game_6nimmt


def main():
    game_num = int(sys.argv[1]) if len(sys.argv) > 1 else 600
    rollouts = int(sys.argv[2]) if len(sys.argv) > 2 else 24
    seed_base = int(sys.argv[3]) if len(sys.argv) > 3 else 980000

    game_6nimmt.extra_feature_mode = "none"
    game_6nimmt.PER_GAME_FILES = False
    game_6nimmt.SEARCH_ROLLOUTS = rollouts
    game_6nimmt.SEARCH_SPLIT_LOG = []

    with contextlib.redirect_stdout(io.StringIO()):
        for i in range(game_num):
            game_6nimmt.run_game(2, seed_base + i, False, ["search", "simple_ai"], None,
                                 record_to_file=False)

    log = game_6nimmt.SEARCH_SPLIT_LOG
    agree = [item for item in log if item[1] == item[2]]
    decisive = [item for item in log if item[3] >= 0.5]
    tie = [item for item in log if item[3] < 0.2]
    print("局数 %d，每局 rollout 总数 %d（两半各 %d）" % (game_num, rollouts, rollouts // 2))
    print("出牌决策样本: %d" % len(log))
    print("两半选中同一张牌的比例（标签自一致率）: %.2f%%" % (100.0 * len(agree) / max(len(log), 1)))
    if decisive:
        print("  其中「最优明显领先」(差距 >= 0.5 牛头) 的 %d 条，自一致率 %.2f%%"
              % (len(decisive), 100.0 * len([i for i in decisive if i[1] == i[2]]) / len(decisive)))
    if tie:
        print("  其中「基本并列」(差距 < 0.2 牛头) 的 %d 条，自一致率 %.2f%%"
              % (len(tie), 100.0 * len([i for i in tie if i[1] == i[2]]) / len(tie)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
