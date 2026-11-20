# -*- coding: utf-8 -*-
"""固定种子评测：模型 A vs 模型 B（或 vs 电脑），双方轮流坐庄。

- 每副牌用固定种子，同样的模型每次结果完全一致，消除评测噪声
- 双方轮座：同一副牌让 A 分别坐 P1 / P2，消除座位偏差
- `record_to_file=False`：不写 game_log、不写训练样本，不会污染数据集

全部走具名参数（`--key=value` 或 `--key value` 都行），避免位置传错：
    --games     对局数（默认 1000）
    --model     A 方模型文件（默认 model.pth）
    --mode      extra_feature_mode，必须和模型训练时一致（默认 none）
    --normalize 是否归一化 state（--normalize 或 --normalize=1）
    --player    A 方玩家类型（network / policy / scorepolicy / hybrid / search ...）
    --seed      起始种子（默认 900000）
    --opponent  B 方玩家类型（默认 simple_ai）
    --opp-model B 方模型文件；不给则两边用同一个模型

示例：
    # 模型 vs 随机电脑
    python evaluate.py --games=4000 --model=model_heur_30.pth --player=network

    # 纯搜索 vs 手写启发式
    python evaluate.py --games=2000 --model=dummy.pth --player=search --opponent=advanced_ai

    # 新一代 vs 上一代（两边都是 hybrid，只是模型不同）
    python evaluate.py --games=4000 --model=new.pth --mode=teacher_scores ^
        --player=hybrid --opponent=hybrid --opp-model=old.pth

兼容：如果第一个参数不是以 `--` 开头，仍按旧的 7 个位置参数解析并给出提示。
"""

import argparse
import contextlib
import io
import sys

import game_6nimmt

SEED_BASE = 900000

# 旧的位置参数顺序，仅用于兼容
POS_ORDER = ["games", "model", "mode", "normalize", "player", "seed", "opponent"]

EXAMPLES = """示例：
  python evaluate.py --games=4000 --model=model_heur_30.pth --player=network
  python evaluate.py --games=2000 --model=dummy.pth --player=search --opponent=advanced_ai
  python evaluate.py --games=4000 --model=new.pth --mode=teacher_scores \\
      --player=hybrid --opponent=hybrid --opp-model=old.pth
"""


def build_parser():
    p = argparse.ArgumentParser(
        description="固定种子评测：模型 A vs 模型 B（或 vs 电脑），双方轮座，结果可复现。",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=EXAMPLES)
    p.add_argument("--games", default="1000", help="对局数（默认 1000）")
    p.add_argument("--model", default="model.pth", help="A 方模型文件（默认 model.pth）")
    p.add_argument("--mode", default="none",
                   help="extra_feature_mode，必须和模型训练时一致（默认 none）")
    p.add_argument("--normalize", nargs="?", const="1", default="0",
                   help="是否归一化 state：--normalize 或 --normalize=1/0")
    p.add_argument("--player", default="network", help="A 方玩家类型（默认 network）")
    p.add_argument("--seed", default=str(SEED_BASE), help="起始种子（默认 900000）")
    p.add_argument("--opponent", default="simple_ai", help="B 方玩家类型（默认 simple_ai）")
    p.add_argument("--opp-model", dest="opp_model", default=None,
                   help="B 方模型文件；不给则两边用同一个模型")
    return p


def legacy_to_named(argv):
    """把旧的 7 个位置参数翻译成具名参数，返回 (argv, 是否用了旧写法)"""
    if not argv or argv[0].startswith("-"):
        return argv, False
    out = []
    for key, val in zip(POS_ORDER, argv):
        out.append("--%s=%s" % (key, val))
    return out, True


def main():
    argv, legacy = legacy_to_named(sys.argv[1:])
    if legacy:
        print("提示：位置参数已废弃，请改用具名参数（python evaluate.py --help 查看）",
              file=sys.stderr)
    args = build_parser().parse_args(argv)

    games = int(args.games)
    mode = args.mode
    normalize = str(args.normalize).lower() not in ("0", "false", "no", "")
    player_type = args.player
    seed_base = int(args.seed)
    opponent = args.opponent
    model_path = args.model
    opp_model = args.opp_model

    game_6nimmt.extra_feature_mode = mode
    game_6nimmt.normalize_state = normalize
    if player_type in ("policy", "scorepolicy") or opponent in ("policy", "scorepolicy"):
        game_6nimmt.policy_sample = False      # 评测时取 argmax，不采样

    pairs = max(1, games // 2)
    wins = 0
    pair_wins = []          # 每副牌的胜场数（0/1/2）——同一副牌打了两次，不能当独立样本
    bullheads_a = 0
    bullheads_b = 0

    with contextlib.redirect_stdout(io.StringIO()):    # 对局打印太多，整体吞掉
        for i in range(pairs):
            seed = seed_base + i
            w = 0
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
                    w += 1
                bullheads_a += bullheads[a_seat]
                bullheads_b += bullheads[1 - a_seat]
            pair_wins.append(w)

    total = pairs * 2
    p = 1.0 * wins / total
    # 配对标准误：以「一副牌」为单位，而不是以「一局」为单位
    vals = [w / 2.0 for w in pair_wins]
    m = sum(vals) / len(vals)
    if len(vals) > 1:
        sd = (sum((v - m) ** 2 for v in vals) / (len(vals) - 1)) ** 0.5
        se = sd / (len(vals) ** 0.5)
    else:
        se = 0.0
    half = 1.96 * se
    print("模型 A   : %s  [%s]" % (model_path, player_type))
    if opp_model:
        print("模型 B   : %s  [%s]   <- 双方都是模型" % (opp_model, opponent))
    else:
        print("对手     : %s" % opponent)
    print("配置     : mode=%s, normalize=%s" % (mode, normalize))
    print("对局数   : %d（%d 副牌 × 双方轮座）" % (total, pairs))
    print("A 胜率   : %.2f%%  (%d/%d)   95%% 区间 ±%.2f 个百分点"
          % (100.0 * p, wins, total, 100.0 * half))
    print("牛头占比 : A %.2f%% (A %d / B %d)"
          % (100.0 * bullheads_a / max(bullheads_a + bullheads_b, 1),
             bullheads_a, bullheads_b))
    return 0


if __name__ == "__main__":
    sys.exit(main())
