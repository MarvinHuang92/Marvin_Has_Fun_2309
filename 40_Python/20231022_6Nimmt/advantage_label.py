# -*- coding: utf-8 -*-
"""
用「只吃 state 的价值网络 V(s)」当基线，把 reward-to-go 换成优势函数标签：

    A(s, a) = G_t - V(s)

这一步的目的是降方差：G_t 里绝大部分波动来自后面的运气，跟当前这一手关系很弱；
减掉同局面的平均期望 V(s) 后，剩下的才是「这个动作比平均水平好多少」，
网络才有可能把动作区分开。

前置条件：
  1. 有 v2 样本表，并已用 reward_to_go.py 生成 rtg 标签；
  2. 有一个只吃 state 的 V(s) 模型（用 neural_network_6nimmt 训练，
     input_col_max = state 维度、reward_col = reward 所在列）。

用法：
  python advantage_label.py
  python advantage_label.py 输入.csv 输出.csv 模型.pth
"""

import sys
import torch

import neural_network_6nimmt as nn6      # 顺带处理 models/ 路径与模型类导入
import reward_to_go as rtg

INPUT = "game_log/02_nn_sample_data_rtg.csv"
OUTPUT = "game_log/02_nn_sample_data_adv.csv"
VALUE_MODEL = "models/model_value.pth"
ACTION_DIMS = 14


def calc_values(rows, state_dim, model, batch=8192):
    values = []
    with torch.no_grad():
        for start in range(0, len(rows), batch):
            chunk = rows[start:start + batch]
            x = torch.Tensor([[float(v) for v in row[:state_dim]] for row in chunk])
            values.extend(model(x).view(-1).tolist())
    return values


def main():
    input_path = INPUT if len(sys.argv) < 2 else sys.argv[1]
    output_path = OUTPUT if len(sys.argv) < 3 else sys.argv[2]
    model_path = VALUE_MODEL if len(sys.argv) < 4 else sys.argv[3]

    rows, cols, skipped = rtg.read_rows(input_path)
    if not rows:
        print("没有读到样本，请先跑对局并用 reward_to_go.py 生成 rtg 标签")
        return 1

    reward_col = cols[0]
    state_dim = reward_col - ACTION_DIMS      # reward 前面是 state + action
    labels = [float(row[reward_col]) for row in rows]

    resolved = nn6.resolve_model_path(model_path)
    print("加载价值网络: %s" % resolved)
    model = torch.load(resolved, weights_only=False)
    values = calc_values(rows, state_dim, model)

    advantages = [label - value for label, value in zip(labels, values)]

    with open(output_path, "w") as f:
        for row, adv in zip(rows, advantages):
            row[reward_col] = "%.6f" % adv
            f.write(",".join(row) + "\n")

    def std(data):
        mean = sum(data) / len(data)
        return mean, (sum((v - mean) ** 2 for v in data) / len(data)) ** 0.5

    label_mean, label_std = std(labels)
    adv_mean, adv_std = std(advantages)
    value_mean, value_std = std(values)

    print("输入: %s" % input_path)
    print("输出: %s" % output_path)
    print("样本行数: %d（跳过 %d 行格式不一致）" % (len(rows), skipped))
    print("state 维度: %d" % state_dim)
    print("reward-to-go : 均值 %8.4f  标准差 %8.4f" % (label_mean, label_std))
    print("V(s) 预测     : 均值 %8.4f  标准差 %8.4f" % (value_mean, value_std))
    print("优势 A(s,a)   : 均值 %8.4f  标准差 %8.4f" % (adv_mean, adv_std))
    print("标签标准差降低: %.1f%%" % (100.0 * (1 - adv_std / label_std)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
