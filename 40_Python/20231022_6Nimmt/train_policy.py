# -*- coding: utf-8 -*-
"""
第四轮：策略梯度（REINFORCE + 基线）

三步走：
  1) distill 用监督模型当老师，热启动策略网络（交叉熵模仿老师的 argmin）
  2) sample  让策略自己打牌，采集 on-policy 数据（策略固定坐 P1）
  3) train   REINFORCE 微调：损失 = mean(logπ(a|s) * (G - V(s)))

用法：
  python train_policy.py distill <数据.csv> <监督模型.pth> <输出.pth> [epochs]
  python train_policy.py sample <策略模型.pth> <局数> <输出.csv> [起始种子]
  python train_policy.py train  <数据.csv> <策略模型.pth> [epochs] [lr]

约定（本轮实验都按这个来）：
  - extra_feature_mode = "none"、normalize_state = False，即 state 是 40 维原始值
  - 策略玩家固定坐 P1（seat 元数据 = 1），只学自己那一侧的决策
"""

import sys

import torch
from torch import nn

import game_6nimmt
import reward_to_go as rtg
from neural_network_6nimmt import resolve_model_path
from policy_6nimmt import PolicyNetwork, legal_mask, save_policy, load_policy

STATE_DIM = 40
ACTION_DIM = 14
POLICY_SEAT = 1          # seat 元数据是 1-based，P1 = 1
POLICY_SEAT_INDEX = 0    # player_types 里的下标


def build_states_and_masks(rows, cols):
    """从样本表取出 state / 合法动作掩码 / 实际动作 / 标签"""
    states, masks, actions, labels = [], [], [], []
    for row in rows:
        if int(row[cols[3]]) != POLICY_SEAT:      # 只看策略玩家自己的决策
            continue
        state = [float(v) for v in row[:STATE_DIM]]
        situation = int(state[39])
        hand_count = int(state[37])
        states.append(state)
        masks.append(legal_mask(situation, hand_count))
        actions.append(max(range(ACTION_DIM), key=lambda i: float(row[STATE_DIM + i])))
        labels.append(float(row[cols[0]]))
    return states, masks, actions, labels


def mask_tensor(masks):
    return torch.Tensor(masks)


def distill(data_csv, teacher_path, out_path, epochs=30):
    """用监督模型（Q 网络，取 argmin）的决策当标签，交叉熵训练策略网络"""
    rows, cols, _ = rtg.read_rows(data_csv)
    states, masks, _, _ = build_states_and_masks(rows, cols)
    if not states:
        print("没有读到策略玩家的样本")
        return 1

    state_dim = cols[0] - ACTION_DIM
    x = torch.Tensor(states)
    mask = mask_tensor(masks)

    print("加载老师: %s" % resolve_model_path(teacher_path))
    teacher = torch.load(resolve_model_path(teacher_path), weights_only=False)

    # 老师的动作 = 合法动作里 Q 最小的那个。把 14 个动作一次性拼成 (N*14, state+14)
    targets = []
    chunk = 2048
    with torch.no_grad():
        for start in range(0, len(states), chunk):
            xs = x[start:start + chunk]
            ms = mask[start:start + chunk]
            n = xs.shape[0]
            xa = xs.unsqueeze(1).repeat(1, ACTION_DIM, 1)          # (n,14,state_dim)
            onehot = torch.eye(ACTION_DIM).unsqueeze(0).repeat(n, 1, 1)
            xa = torch.cat([xa, onehot], dim=2).view(n * ACTION_DIM, -1)
            q = teacher(xa).view(n, ACTION_DIM)
            q = torch.where(ms > 0, q, torch.full_like(q, 1e9))     # 非法动作不参与比较
            targets.extend(q.argmin(1).tolist())

    targets = torch.LongTensor(targets)
    policy = PolicyNetwork(state_dim)
    optimizer = torch.optim.Adam(policy.parameters(), 1e-3)
    criterion = nn.CrossEntropyLoss()
    for epoch in range(epochs):
        logits = policy(x) + (mask - 1.0) * 1e9
        loss = criterion(logits, targets)
        optimizer.zero_grad()
        loss.backward()
        optimizer.step()
        if epoch % 10 == 0 or epoch == epochs - 1:
            agree = (logits.argmax(1) == targets).float().mean().item()
            print("epoch %3d  loss %.4f  与老师一致率 %.2f%%" % (epoch, loss.item(), 100 * agree))

    save_policy(policy, out_path)
    return 0


def sample(policy_path, game_num, out_csv, seed_base=800000):
    """用策略采样对局，把样本写进 out_csv（策略固定坐 P1）"""
    import contextlib
    import io

    game_6nimmt.extra_feature_mode = "none"
    game_6nimmt.normalize_state = False
    game_6nimmt.policy_sample = True
    game_6nimmt.PER_GAME_FILES = False
    game_6nimmt.SAMPLE_DATA_MASTER = out_csv

    with contextlib.redirect_stdout(io.StringIO()):
        for i in range(game_num):
            game_6nimmt.run_game(2, seed_base + i, False,
                                 ["policy", "simple_ai"], policy_path, record_to_file=True)
    print("采样完成: %d 局 -> %s" % (game_num, out_csv))
    return 0


def train(data_csv, policy_path, epochs=8, lr=3e-4, batch=4096):
    """REINFORCE：损失 = mean(logπ(a|s) * A)，A = G - V(s) 已在数据里算好"""
    rows, cols, _ = rtg.read_rows(data_csv)
    states, masks, actions, advantages = build_states_and_masks(rows, cols)
    if not states:
        print("没有读到策略玩家的样本")
        return 1

    state_dim = cols[0] - ACTION_DIM
    x = torch.Tensor(states)
    mask = mask_tensor(masks)
    taken = torch.LongTensor(actions)
    adv = torch.Tensor(advantages)
    adv = adv - adv.mean()          # 再减一次常数基线，纯降方差、不引入偏差

    policy = load_policy(policy_path)
    optimizer = torch.optim.Adam(policy.parameters(), lr)
    n = x.shape[0]
    for epoch in range(epochs):
        order = torch.randperm(n)
        total_loss = 0.0
        for start in range(0, n, batch):
            idx = order[start:start + batch]
            logits = policy(x[idx]) + (mask[idx] - 1.0) * 1e9
            logp = torch.log_softmax(logits, dim=1)
            logp_taken = logp.gather(1, taken[idx].unsqueeze(1)).squeeze(1)
            loss = (logp_taken * adv[idx]).mean()
            optimizer.zero_grad()
            loss.backward()
            optimizer.step()
            total_loss += loss.item() * len(idx)
        print("epoch %2d  loss %+.5f" % (epoch, total_loss / n))

    save_policy(policy, policy_path)
    return 0


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return 1

    cmd = sys.argv[1]
    if cmd == "distill":
        epochs = int(sys.argv[5]) if len(sys.argv) > 5 else 30
        return distill(sys.argv[2], sys.argv[3], sys.argv[4], epochs)
    if cmd == "sample":
        seed = int(sys.argv[5]) if len(sys.argv) > 5 else 800000
        return sample(sys.argv[2], int(sys.argv[3]), sys.argv[4], seed)
    if cmd == "train":
        epochs = int(sys.argv[4]) if len(sys.argv) > 4 else 8
        lr = float(sys.argv[5]) if len(sys.argv) > 5 else 3e-4
        return train(sys.argv[2], sys.argv[3], epochs, lr)

    print("未知命令: %s" % cmd)
    return 1


if __name__ == "__main__":
    sys.exit(main())
