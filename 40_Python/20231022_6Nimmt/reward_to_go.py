# -*- coding: utf-8 -*-
"""
把样本表里的 reward 列离线重算成别的标签，另存为新文件（原文件不动）。

标签类型：
  rtg   reward-to-go：从本回合起、到本局结束累计的真实罚分（默认，不折扣）
  step  单步实际罚分：只算本回合真实吃到的牛头
  keep  不改标签，只做分组校验

用法：
  python reward_to_go.py              # rtg 标签
  python reward_to_go.py step         # 单步实际罚分
  python reward_to_go.py rtg 0.9      # 折扣 reward-to-go（γ=0.9）
  python reward_to_go.py rtg 1.0 输入.csv 输出.csv   # 自定义输入/输出文件

输入必须是 v2 格式的样本表（game_6nimmt.py 现在写出的格式），
即 55 列之后还有 game_id / round / seat / 本回合罚分 / 回合前分数 这 5 列。
"""

import sys

# 输入 / 输出
INPUT = "game_log/02_nn_sample_data_full_v2.csv"
OUTPUT = "game_log/02_nn_sample_data_%s.csv"    # %s = 标签名

# 列位置由行宽反推，兼容「加过额外特征」的样本：
# 最后一列是 score_before_round，往前依次是 4 列元数据 + reward
META_COLS = 5


def col_indices(width):
    """返回 (reward, game_id, round, seat, penalty, score_before) 的列号"""
    reward = width - 1 - META_COLS
    return (reward, reward + 1, reward + 2, reward + 3, reward + 4, reward + 5)


def read_rows(path):
    """读样本表，返回 (rows, 列号, 跳过行数)。

    列宽以第一条合法行为准，宽度不一致的行（表头、旧格式、别的特征配置）跳过。
    """
    rows = []
    skipped = 0
    width = None
    with open(path) as f:
        for line in f:
            cols = line.strip().split(",")
            if width is None:
                if len(cols) <= META_COLS + 1:
                    skipped += 1
                    continue
                width = len(cols)
            if len(cols) != width:
                skipped += 1
                continue
            rows.append(cols)
    return rows, col_indices(width or 0), skipped


def group_by_game(rows, cols):
    """按 (对局, 玩家) 分组，再按回合归集行号。

    同一回合里可能有多行（出牌 1 行 + 打出最小牌时选行再加 1 行），
    它们发生在同一次结算之前，因此共享同一个 reward-to-go。
    """
    game_id_col, round_col, seat_col = cols[1], cols[2], cols[3]
    groups = {}
    for index, row in enumerate(rows):
        key = (row[game_id_col].strip(), int(row[seat_col]))
        round_no = int(row[round_col])
        groups.setdefault(key, {}).setdefault(round_no, []).append(index)
    return groups


def calc_labels(rows, cols, label_type, discount=1.0):
    reward_col, _, _, _, penalty_col, _ = cols
    if label_type == "keep":
        return [float(row[reward_col]) for row in rows]
    if label_type == "step":
        return [float(row[penalty_col]) for row in rows]

    # rtg：从最后一回合往前累加 G_t = r_t + γ * G_{t+1}
    labels = [0.0] * len(rows)
    for key, rounds in group_by_game(rows, cols).items():
        reward_to_go = 0.0
        for round_no in sorted(rounds, reverse=True):
            indices = rounds[round_no]
            penalties = set(rows[i][penalty_col].strip() for i in indices)
            if len(penalties) > 1:
                print("WARN: %s 第 %d 回合罚分不一致 %s" % (key[0], round_no, sorted(penalties)))
            reward_to_go = float(sorted(penalties)[0]) + discount * reward_to_go
            for i in indices:
                labels[i] = reward_to_go
    return labels


def check_rtg(rows, cols, labels):
    """校验：本局最终牛头数 == 第一回合的 reward-to-go（γ=1 时应严格成立）"""
    _, _, _, _, penalty_col, score_before_col = cols
    final_score = {}
    first_reward_to_go = {}
    for key, rounds in group_by_game(rows, cols).items():
        last_index = rounds[max(rounds)][0]
        final_score[key] = (float(rows[last_index][score_before_col])
                            + float(rows[last_index][penalty_col]))
        first_reward_to_go[key] = labels[rounds[min(rounds)][0]]

    bad = [key for key in final_score if abs(final_score[key] - first_reward_to_go[key]) > 1e-6]
    for key in bad[:5]:
        print("WARN: %s 终局 %s 与首回合 reward-to-go %s 不符"
              % (key, final_score[key], first_reward_to_go[key]))
    return len(final_score), len(bad)


def main():
    label_type = "rtg"
    discount = 1.0
    if len(sys.argv) > 1:
        label_type = sys.argv[1]
    if len(sys.argv) > 2:
        discount = float(sys.argv[2])
    if label_type not in ("rtg", "step", "keep"):
        print("未知标签类型: %s（可选 rtg / step / keep）" % label_type)
        return 1

    output = OUTPUT % (label_type if discount == 1.0 else "%s_g%s" % (label_type, discount))
    input_path = INPUT
    if len(sys.argv) > 3:
        input_path = sys.argv[3]
    if len(sys.argv) > 4:
        output = sys.argv[4]
    rows, cols, skipped = read_rows(input_path)
    if not rows:
        print("没有读到 v2 格式的样本，请先跑对局生成 %s" % input_path)
        return 1

    labels = calc_labels(rows, cols, label_type, discount)
    games = len(set(row[cols[1]].strip() for row in rows))
    nonzero = sum(1 for v in labels if v != 0)

    with open(output, "w") as f:
        for row, label in zip(rows, labels):
            row[cols[0]] = "%.6f" % label
            f.write(",".join(row) + "\n")

    print("输入: %s" % input_path)
    print("输出: %s" % output)
    print("标签类型: %s%s" % (label_type, "" if label_type != "rtg" else " (discount=%s)" % discount))
    print("样本行数: %d（跳过 %d 行表头/空行/格式不一致）" % (len(rows), skipped))
    print("每行宽度: %d 列（reward 在第 %d 列）" % (len(rows[0]), cols[0]))
    print("对局数: %d" % games)
    print("非零标签占比: %.2f%%" % (100.0 * nonzero / len(labels)))
    print("标签均值: %.4f" % (sum(labels) / len(labels)))

    # 只有不折扣的 rtg 才满足「首回合 G == 终局分」，其它标签不做这个校验
    if label_type == "rtg" and discount == 1.0:
        trajectories, bad = check_rtg(rows, cols, labels)
        print("校验（%d 条玩家轨迹）: 首回合 G 与终局分不符 %d 条" % (trajectories, bad))

    return 0


if __name__ == "__main__":
    sys.exit(main())
