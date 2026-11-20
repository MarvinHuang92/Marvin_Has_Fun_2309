# -*- coding: utf-8 -*-
"""
固定种子评测：模型 A vs 模型 B（或 vs 电脑），双方轮流坐庄。

- 每副牌用固定种子（SEED_BASE 起），同样的模型每次评测结果完全一致，消除评测噪声
- `record_to_file=False`：不写 game_log、不写训练样本，不会污染数据集
- 双方轮座：同一副牌让 A 分别坐 P1 / P2，消除座位偏差

用法（前 7 个是位置参数，向后兼容）：
  python evaluate.py [局数] [模型A] [特征模式] [归一化] [玩家类型] [起始种子] [对手类型]

新增的具名参数（用 `--key=value` 写在任意位置）：
  --opp-model=xxx.pth   对手用另一个模型。不给的话两边用同一个模型（自己打自己）

例：
  # A 用 hybrid 打随机电脑
  python evaluate.py 4000 model_searchc_25k400_ts.pth teacher_scores 0 hybrid 950000 simple_ai

  # 新一代 vs 上一代：两边都是 hybrid，只是模型不同
  python evaluate.py 4000 model_new.pth teacher_scores 0 hybrid 950000 hybrid --opp-model=model_old.pth
"""

import contextlib
import io
import sys

import game_6nimmt

SEED_BASE = 900000


def parse_args(argv):
    """位置参数 + `--key=value` 具名参数混排"""
    opts, pos = {}, []
    i = 0
    while i < len(argv):
        a = argv[i]
        if a.startswith("--"):
            body = a[2:]
            if "=" in body:
                k, v = body.split("=", 1)
            else:
                k = body
                i += 1
                v = argv[i] if i < len(argv) else ""
            opts[k] = v
        else:
            pos.append(a)
        i += 1
    return pos, opts


def main():
    pos, opts = parse_args(sys.argv[1:])

    game_num = int(pos[0]) if len(pos) > 0 else 1000
    model_path = pos[1] if len(pos) > 1 else "model.pth"
    mode = pos[2] if len(pos) > 2 else "none"
    normalize = len(pos) > 3 and pos[3].lower() not in ("0", "false")
    player_type = pos[4] if len(pos) > 4 else "network"
    seed_base = int(pos[5]) if len(pos) > 5 else SEED_BASE
    opponent = pos[6] if len(pos) > 6 else "simple_ai"
    opp_model = opts.get("opp-model") or opts.get("opp_model")

    game_6nimmt.extra_feature_mode = mode
    game_6nimmt.normalize_state = normalize
    if player_type in ("policy", "scorepolicy") or opponent in ("policy", "scorepolicy"):
        game_6nimmt.policy_sample = False      # 评测时取 argmax，不采样

    pairs = max(1, game_num // 2)
    wins = 0
    bullheads_a = 0
    bullheads_b = 0

    # 对局打印太多，整体吞掉
    with contextlib.redirect_stdout(io.StringIO()):
        for i in range(pairs):
            seed = seed_base + i
            # 同一副牌，模型分别坐 P1 / P2，消除座位偏差
            for a_seat in (0, 1):
                types = [player_type, opponent] if a_seat == 0 else [opponent, player_type]
                if opp_model:
                    paths = [model_path, opp_model] if a_seat == 0 else [opp_model, model_path]
                else:
                    paths = model_path
                result = game_6nimmt.run_game(2, seed, False, types, paths,
                                              record_to_file=False)
                bullheads = result["bullheads"]
                if result["winner"] == a_seat:
                    wins += 1
                bullheads_a += bullheads[a_seat]
                bullheads_b += bullheads[1 - a_seat]

    total = pairs * 2
    p = 1.0 * wins / total
    half = 1.96 * (p * (1.0 - p) / total) ** 0.5
    print("模型 A   : %s  [%s]" % (model_path, player_type))
    if opp_model:
        print("模型 B   : %s  [%s]   <- 双方都是模型" % (opp_model, opponent))
    else:
        print("对手     : %s" % opponent)
    print("配置     : extra_feature_mode=%s, normalize_state=%s" % (mode, normalize))
    print("对局数   : %d（%d 副牌 × 双方轮座）" % (total, pairs))
    print("A 胜率   : %.2f%%  (%d/%d)   95%% 区间 ±%.2f 个百分点"
          % (100.0 * p, wins, total, 100.0 * half))
    print("牛头占比 : A %.2f%% (我方 %d / 对手 %d)"
          % (100.0 * bullheads_a / max(bullheads_a + bullheads_b, 1),
             bullheads_a, bullheads_b))
    return 0


if __name__ == "__main__":
    sys.exit(main())
