# -*- coding: utf-8 -*-
"""
固定种子评测：神经网络玩家 vs 随机电脑，双方轮流坐庄。

- 每副牌用固定种子（SEED_BASE 起），同样的模型每次评测结果完全一致，消除评测噪声
- `record_to_file=False`：不写 game_log、不写训练样本，不会污染数据集

用法：
  python evaluate.py [game_num] [model_path] [extra_feature_mode] [normalize]
例如：
  python evaluate.py 1000 model_heur_30.pth none 0
  python evaluate.py 1000 model_adv_rs_norm_30.pth row_segments 1
"""

import contextlib
import io
import sys

import game_6nimmt

SEED_BASE = 900000


def main():
    game_num = int(sys.argv[1]) if len(sys.argv) > 1 else 1000
    model_path = sys.argv[2] if len(sys.argv) > 2 else "model.pth"
    mode = sys.argv[3] if len(sys.argv) > 3 else "none"
    normalize = len(sys.argv) > 4 and sys.argv[4].lower() not in ("0", "false")
    player_type = sys.argv[5] if len(sys.argv) > 5 else "network"
    seed_base = int(sys.argv[6]) if len(sys.argv) > 6 else SEED_BASE

    game_6nimmt.extra_feature_mode = mode
    game_6nimmt.normalize_state = normalize
    if player_type in ("policy", "scorepolicy"):
        game_6nimmt.policy_sample = False      # 评测时取 argmax，不采样

    pairs = game_num // 2
    wins = 0
    bullheads_nn = 0
    bullheads_opp = 0

    # 对局打印太多，整体吞掉
    with contextlib.redirect_stdout(io.StringIO()):
        for i in range(pairs):
            seed = seed_base + i
            # 同一副牌，神经网络分别坐 P1 / P2，消除座位偏差
            for nn_seat in (0, 1):
                types = [player_type, "simple_ai"] if nn_seat == 0 else ["simple_ai", player_type]
                result = game_6nimmt.run_game(2, seed, False, types, model_path, record_to_file=False)
                bullheads = result["bullheads"]
                if result["winner"] == nn_seat:
                    wins += 1
                bullheads_nn += bullheads[nn_seat]
                bullheads_opp += bullheads[1 - nn_seat]

    total = pairs * 2
    print("模型     : %s" % model_path)
    print("配置     : extra_feature_mode=%s, normalize_state=%s" % (mode, normalize))
    print("对局数   : %d（%d 副牌 × 双方轮座）" % (total, pairs))
    print("胜率     : %.2f%%  (%d/%d)" % (100.0 * wins / total, wins, total))
    print("牛头占比 : %.2f%%  (我方 %d / 对手 %d)"
          % (100.0 * bullheads_nn / max(bullheads_nn + bullheads_opp, 1), bullheads_nn, bullheads_opp))
    return 0


if __name__ == "__main__":
    sys.exit(main())
