# -*- coding: utf-8 -*-
"""
第四轮：策略梯度（REINFORCE + 基线）

三步走：
  1) distill 用监督模型当老师，热启动策略网络（交叉熵模仿老师的 argmin）
  2) sample  让策略自己打牌，采集 on-policy 数据（策略固定坐 P1）
  3) train   REINFORCE 微调：损失 = mean(logπ(a|s) * (G - V(s)))

用法：
  python train_policy.py distill <数据.csv> <监督模型.pth> <输出.pth> [epochs]
  python train_policy.py imitate <数据.csv> <输出.pth> [epochs] [玩家类型]
  python train_policy.py imitate_score <数据.csv> <输出.pth> [epochs] [温度]
  python train_policy.py sample  <策略模型.pth> <局数> <输出.csv> [起始种子] [玩家类型] [mode] [normalize] [对手]
  python train_policy.py sample_search <局数> <样本.csv> <代价.csv> [起始种子] [mode] [对手] [rollout]
  python train_policy.py distill_costs <代价.csv> <输出.pth> [epochs] [温度] [hidden]
  python train_policy.py train   <数据.csv> <策略模型.pth> [epochs] [lr] [熵权重]
  python train_policy.py train_score <数据.csv> <模型.pth> [epochs] [lr] [温度] [熵权重]

约定（本轮实验都按这个来）：
  - extra_feature_mode = "none"、normalize_state = False，即 state 是 40 维原始值
  - 策略玩家固定坐 P1（seat 元数据 = 1），只学自己那一侧的决策
  - imitate 用来模仿「别人的实际动作」（比如 advanced_ai），distill 用来模仿 Q 网络的 argmin
"""

import sys

import torch
from torch import nn

import game_6nimmt
import reward_to_go as rtg
from neural_network_6nimmt import resolve_model_path
from policy_6nimmt import PolicyNetwork, legal_mask, save_policy, load_policy, build_action_inputs, ResidualPolicy

STATE_DIM = 40
ACTION_DIM = 14
POLICY_SEAT = 1          # seat 元数据是 1-based，P1 = 1
POLICY_SEAT_INDEX = 0    # player_types 里的下标


def build_states_and_masks(rows, cols):
    """从样本表取出 state / 合法动作掩码 / 实际动作 / 标签"""
    state_dim = cols[0] - ACTION_DIM        # reward 前面是 state + action
    states, masks, actions, labels = [], [], [], []
    for row in rows:
        if int(row[cols[3]]) != POLICY_SEAT:      # 只看策略玩家自己的决策
            continue
        state = [float(v) for v in row[:state_dim]]
        situation = int(state[39])
        hand_count = int(state[37])
        states.append(state)
        masks.append(legal_mask(situation, hand_count))
        actions.append(max(range(ACTION_DIM), key=lambda i: float(row[state_dim + i])))
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


def sample(policy_path, game_num, out_csv, seed_base=800000, player_type="policy", mode="none", normalize=False, opponent="simple_ai"):
    """让指定类型的玩家采样对局，把样本写进 out_csv（该玩家固定坐 P1）"""
    import contextlib
    import io

    game_6nimmt.extra_feature_mode = mode
    game_6nimmt.normalize_state = normalize
    game_6nimmt.policy_sample = True
    game_6nimmt.PER_GAME_FILES = False
    game_6nimmt.SAMPLE_DATA_MASTER = out_csv

    with contextlib.redirect_stdout(io.StringIO()):
        for i in range(game_num):
            game_6nimmt.run_game(2, seed_base + i, False,
                                 [player_type, opponent], policy_path, record_to_file=True)
    print("采样完成: %d 局（%s vs %s）-> %s" % (game_num, player_type, opponent, out_csv))
    return 0


def sample_search(game_num, sample_csv, cost_csv, seed_base=800000, mode="none", opponent="simple_ai", rollouts=12):
    """第十轮：让搜索型玩家打 game_num 局，同时产出两份数据

    - sample_csv：常规样本表（动作 one-hot + 搜索代价当 reward），给 imitate_score 用
    - cost_csv  ：逐动作代价表（state 54 列 + 14 个动作的代价），给 distill_costs 用
    """
    import contextlib
    import io

    game_6nimmt.extra_feature_mode = mode
    game_6nimmt.normalize_state = False
    game_6nimmt.PER_GAME_FILES = False
    game_6nimmt.SAMPLE_DATA_MASTER = sample_csv
    game_6nimmt.SEARCH_COST_LOG = []
    if rollouts:
        game_6nimmt.SEARCH_ROLLOUTS = rollouts

    with contextlib.redirect_stdout(io.StringIO()):
        for i in range(game_num):
            game_6nimmt.run_game(2, seed_base + i, False,
                                 ["search", opponent], None, record_to_file=True)

    with open(cost_csv, "w") as f:
        for line in game_6nimmt.SEARCH_COST_LOG:
            f.write(",".join("%.6f" % v for v in line) + "\n")
    print("采样完成: %d 局（search vs %s，rollout=%d）" % (game_num, opponent, game_6nimmt.SEARCH_ROLLOUTS))
    print("  样本 -> %s" % sample_csv)
    print("  代价 -> %s（%d 条决策）" % (cost_csv, len(game_6nimmt.SEARCH_COST_LOG)))
    game_6nimmt.SEARCH_COST_LOG = None
    return 0


def distill_costs(cost_csv, out_path, epochs=150, temperature=1.0, hidden=120, batch=1024):
    """第十轮：用「逐动作代价」做软标签蒸馏。

    和 imitate_score（只学"选中了哪个动作"）不同，这里每个动作都有代价，
    把它转成玻尔兹曼分布当软标签 —— 代价接近的动作得到接近的概率，
    这正是搜索信息的价值：**知道次优解差多少**，而不只是一个 argmin。
    """
    from neural_network_template import Network

    x_list, cost_list, mask_list = [], [], []
    with open(cost_csv) as f:
        for line in f:
            if not line.strip():
                continue
            vals = [float(v) for v in line.split(",")]
            state, costs = vals[:-ACTION_DIM], vals[-ACTION_DIM:]
            situation = int(round(state[39]))
            hand_count = int(round(state[37]))
            legal = legal_mask(situation, hand_count)
            if sum(legal) < 2:
                continue                       # 只有一个合法动作，没有学习信号
            x_list.append(state)
            cost_list.append(costs)
            mask_list.append(legal)
    if not x_list:
        print("没有读到有效的代价样本")
        return 1

    x = torch.Tensor(x_list)
    costs = torch.Tensor(cost_list)
    mask = torch.Tensor(mask_list)
    # 行内标准化：代价的绝对值（对手也会吃多少）没用，只有"动作之间差多少"有用
    legal_count = mask.sum(dim=1, keepdim=True).clamp(min=1.0)
    mean = (costs * mask).sum(dim=1, keepdim=True) / legal_count
    var = (((costs - mean) * mask) ** 2).sum(dim=1, keepdim=True) / legal_count
    z = -(costs - mean) / torch.sqrt(var + 1e-6)          # 越小越好 → 取负号变成越大越好
    target = torch.softmax(z / temperature + (mask - 1.0) * 1e9, dim=1)

    state_dim = x.shape[1]
    model = Network(state_dim + ACTION_DIM, hidden, 1, torch.relu)
    print("隐藏单元: %d，参数量: %d，样本数: %d"
          % (hidden, sum(p.numel() for p in model.parameters()), len(x_list)))
    optimizer = torch.optim.Adam(model.parameters(), 1e-3)
    all_actions = torch.arange(ACTION_DIM).unsqueeze(0)
    n = x.shape[0]
    best_index = costs + (1.0 - mask) * 1e9          # 非法动作推到极大，argmin 才只看合法动作
    best_index = best_index.argmin(dim=1)

    for epoch in range(epochs):
        order = torch.randperm(n)
        total = 0.0
        for start in range(0, n, batch):
            idx = order[start:start + batch]
            acts = all_actions.repeat(len(idx), 1)
            scores = model(build_action_inputs(x[idx], acts).view(-1, state_dim + ACTION_DIM)).view(-1, ACTION_DIM)
            logp = torch.log_softmax(-scores / temperature + (mask[idx] - 1.0) * 1e9, dim=1)
            loss = -(target[idx] * logp).sum(dim=1).mean()
            optimizer.zero_grad()
            loss.backward()
            optimizer.step()
            total += loss.item() * len(idx)
        if epoch % 25 == 0 or epoch == epochs - 1:
            with torch.no_grad():
                acts = all_actions.repeat(n, 1)
                scores = model(build_action_inputs(x, acts).view(-1, state_dim + ACTION_DIM)).view(-1, ACTION_DIM)
                logp = torch.log_softmax(-scores / temperature + (mask - 1.0) * 1e9, dim=1)
                agree = (logp.argmax(1) == best_index).float().mean().item()
                kl = (target * (torch.log(target + 1e-12) - logp)).sum(dim=1).mean().item()
            print("epoch %3d  loss %.4f  与 argmin(代价) 一致率 %.2f%%  软标签 KL %.4f"
                  % (epoch, total / n, 100 * agree, kl))

    save_policy(model, out_path)
    return 0


def imitate(data_csv, out_path, epochs=200):
    """模仿数据里「实际执行的动作」（例如 advanced_ai 的决策），交叉熵训练策略网络"""
    rows, cols, _ = rtg.read_rows(data_csv)
    states, masks, actions, _ = build_states_and_masks(rows, cols)
    if not states:
        print("没有读到 P1 的样本")
        return 1

    state_dim = cols[0] - ACTION_DIM
    x = torch.Tensor(states)
    mask = mask_tensor(masks)
    targets = torch.LongTensor(actions)

    policy = PolicyNetwork(state_dim)
    optimizer = torch.optim.Adam(policy.parameters(), 1e-3)
    criterion = nn.CrossEntropyLoss()
    for epoch in range(epochs):
        logits = policy(x) + (mask - 1.0) * 1e9
        loss = criterion(logits, targets)
        optimizer.zero_grad()
        loss.backward()
        optimizer.step()
        if epoch % 50 == 0 or epoch == epochs - 1:
            agree = (logits.argmax(1) == targets).float().mean().item()
            print("epoch %3d  loss %.4f  与示教动作一致率 %.2f%%" % (epoch, loss.item(), 100 * agree))

    save_policy(policy, out_path)
    return 0


def train(data_csv, policy_path, epochs=8, lr=3e-4, batch=4096, entropy=0.0):
    """REINFORCE：损失 = mean(logπ(a|s) * A) - 熵权重 * 熵，A = G - V(s) 已在数据里算好"""
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
        total_ent = 0.0
        for start in range(0, n, batch):
            idx = order[start:start + batch]
            logits = policy(x[idx]) + (mask[idx] - 1.0) * 1e9
            logp = torch.log_softmax(logits, dim=1)
            logp_taken = logp.gather(1, taken[idx].unsqueeze(1)).squeeze(1)
            ent = -(torch.exp(logp) * logp).sum(dim=1).mean()
            loss = (logp_taken * adv[idx]).mean() - entropy * ent
            optimizer.zero_grad()
            loss.backward()
            optimizer.step()
            total_loss += loss.item() * len(idx)
            total_ent += ent.item() * len(idx)
        print("epoch %2d  loss %+.5f  熵 %.4f" % (epoch, total_loss / n, total_ent / n))

    save_policy(policy, policy_path)
    return 0


def train_score(data_csv, model_path, epochs=8, lr=3e-4, temperature=1.0, entropy=0.0, kl_beta=0.0, batch=2048):
    """打分式策略的 REINFORCE：logits = -Q/T，损失 = mean(logπ(a|s)·A) - 熵权重·熵 + KL权重·KL(π‖π_ref)

    kl_beta > 0 时是「保守更新」：以训练开始时的模型为参考策略，
    每步额外惩罚 KL(π_θ ‖ π_ref)，避免把已经很好的 argmin 排序推坏。
    """
    import copy

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
    adv = adv - adv.mean()
    all_actions = torch.arange(ACTION_DIM).unsqueeze(0)

    model = torch.load(resolve_model_path(model_path), weights_only=False)
    reference = copy.deepcopy(model)
    reference.eval()
    for p in reference.parameters():
        p.requires_grad_(False)

    optimizer = torch.optim.Adam(model.parameters(), lr)
    n = x.shape[0]
    for epoch in range(epochs):
        order = torch.randperm(n)
        total_loss, total_ent, total_kl = 0.0, 0.0, 0.0
        for start in range(0, n, batch):
            idx = order[start:start + batch]
            acts = all_actions.repeat(len(idx), 1)
            xa = build_action_inputs(x[idx], acts).view(-1, state_dim + ACTION_DIM)
            logits = -model(xa).view(-1, ACTION_DIM) / temperature + (mask[idx] - 1.0) * 1e9
            with torch.no_grad():
                logits_ref = -reference(xa).view(-1, ACTION_DIM) / temperature + (mask[idx] - 1.0) * 1e9
            logp = torch.log_softmax(logits, dim=1)
            logp_ref = torch.log_softmax(logits_ref, dim=1)
            logp_taken = logp.gather(1, taken[idx].unsqueeze(1)).squeeze(1)
            ent = -(torch.exp(logp) * logp).sum(dim=1).mean()
            kl = (torch.exp(logp) * (logp - logp_ref)).sum(dim=1).mean()   # KL(π_θ ‖ π_ref)
            loss = (logp_taken * adv[idx]).mean() - entropy * ent + kl_beta * kl
            optimizer.zero_grad()
            loss.backward()
            optimizer.step()
            total_loss += loss.item() * len(idx)
            total_ent += ent.item() * len(idx)
            total_kl += kl.item() * len(idx)
        print("epoch %2d  loss %+.5f  熵 %.4f  KL %.5f" % (epoch, total_loss / n, total_ent / n, total_kl / n))

    save_policy(model, model_path)
    return 0


def imitate_score(data_csv, out_path, epochs=300, temperature=1.0, hidden=30, batch=2048):
    """用打分式架构（state + 动作 one-hot → 分数）模仿数据里实际执行的动作。

    与 imitate() 的区别：14 个候选动作各自走一遍同一个打分网络，
    「这是第几个动作」由输入 one-hot 显式给出，不需要网络自己把输出位置和输入槽位对应起来。
    交叉熵作用在 -分数/温度 上，等于要求「老师的动作得分最低」。
    hidden 用来做容量对照实验。
    """
    from neural_network_template import Network

    rows, cols, _ = rtg.read_rows(data_csv)
    states, masks, actions, _ = build_states_and_masks(rows, cols)
    if not states:
        print("没有读到 P1 的样本")
        return 1

    state_dim = cols[0] - ACTION_DIM
    x = torch.Tensor(states)
    mask = mask_tensor(masks)
    targets = torch.LongTensor(actions)
    all_actions = torch.arange(ACTION_DIM).unsqueeze(0)

    model = Network(state_dim + ACTION_DIM, hidden, 1, torch.relu)   # 与 Q 网络同构，随机初始化
    print("隐藏单元: %d，参数量: %d" % (hidden, sum(p.numel() for p in model.parameters())))
    optimizer = torch.optim.Adam(model.parameters(), 1e-3)
    criterion = nn.CrossEntropyLoss()
    n = x.shape[0]
    base = max(torch.bincount(targets).tolist()) / float(n)

    for epoch in range(epochs):
        order = torch.randperm(n)
        total = 0.0
        for start in range(0, n, batch):
            idx = order[start:start + batch]
            acts = all_actions.repeat(len(idx), 1)
            xa = build_action_inputs(x[idx], acts)
            scores = model(xa.view(-1, state_dim + ACTION_DIM)).view(-1, ACTION_DIM)
            logits = -scores / temperature + (mask[idx] - 1.0) * 1e9
            loss = criterion(logits, targets[idx])
            optimizer.zero_grad()
            loss.backward()
            optimizer.step()
            total += loss.item() * len(idx)
        if epoch % 50 == 0 or epoch == epochs - 1:
            with torch.no_grad():
                acts = all_actions.repeat(n, 1)
                scores = model(build_action_inputs(x, acts).view(-1, state_dim + ACTION_DIM)).view(-1, ACTION_DIM)
                pred = (-scores + (mask - 1.0) * 1e9).argmax(1)
            agree = (pred == targets).float().mean().item()
            print("epoch %3d  loss %.4f  一致率 %.2f%%（多数类基线 %.2f%%）"
                  % (epoch, total / n, 100 * agree, 100 * base))

    save_policy(model, out_path)
    return 0


def train_residual(data_csv, model_path, epochs=6, lr=1e-4, temperature=1.0, kl_beta=0.0, batch=2048):
    """残差策略的 RL：score = alpha * 老师分数 + 网络修正（第八轮）

    起点严格等于老师（输出层零初始化），所以这里主要是看「能不能学到有用的修正」。
    """
    import copy

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
    adv = adv - adv.mean()
    all_actions = torch.arange(ACTION_DIM).unsqueeze(0)

    model = torch.load(resolve_model_path(model_path), weights_only=False)
    start, end = model.teacher_slice
    reference = copy.deepcopy(model)
    reference.eval()
    for p in reference.parameters():
        p.requires_grad_(False)

    optimizer = torch.optim.Adam(model.parameters(), lr)
    n = x.shape[0]
    for epoch in range(epochs):
        order = torch.randperm(n)
        total_loss, total_kl, total_alpha = 0.0, 0.0, 0.0
        for begin in range(0, n, batch):
            idx = order[begin:begin + batch]
            acts = all_actions.repeat(len(idx), 1)
            xa = build_action_inputs(x[idx], acts).view(-1, state_dim + ACTION_DIM)
            teacher = x[idx][:, start:end]                       # (n,14) 每个动作的老师分数

            scores = model.alpha * teacher + model(xa).view(-1, ACTION_DIM)
            logits = -scores / temperature + (mask[idx] - 1.0) * 1e9
            with torch.no_grad():
                ref_scores = reference.alpha * teacher + reference(xa).view(-1, ACTION_DIM)
                logits_ref = -ref_scores / temperature + (mask[idx] - 1.0) * 1e9

            logp = torch.log_softmax(logits, dim=1)
            logp_ref = torch.log_softmax(logits_ref, dim=1)
            logp_taken = logp.gather(1, taken[idx].unsqueeze(1)).squeeze(1)
            kl = (torch.exp(logp) * (logp - logp_ref)).sum(dim=1).mean()
            loss = (logp_taken * adv[idx]).mean() + kl_beta * kl
            optimizer.zero_grad()
            loss.backward()
            optimizer.step()

            total_loss += loss.item() * len(idx)
            total_kl += kl.item() * len(idx)
            total_alpha += model.alpha.item() * len(idx)
        print("epoch %2d  loss %+.5f  KL %.5f  alpha %.4f"
              % (epoch, total_loss / n, total_kl / n, total_alpha / n))

    save_policy(model, model_path)
    return 0


def train_pairwise(data_csv, model_path, epochs=6, lr=1e-4, margin=0.05, batch=512):
    """成对比较目标（第八轮）：只要求「老师认为更好的动作得分更低」，不拟合分数绝对值

    对每个局面取出老师的 14 个分数，构成 (a 优于 b) 的动作对，
    用 margin ranking loss：max(0, margin + score_a - score_b)。
    相比交叉熵，它只关心排序、不关心分数尺度。
    """
    rows, cols, _ = rtg.read_rows(data_csv)
    states, masks, actions, _ = build_states_and_masks(rows, cols)
    if not states:
        print("没有读到策略玩家的样本")
        return 1

    state_dim = cols[0] - ACTION_DIM
    x = torch.Tensor(states)
    mask = mask_tensor(masks)
    all_actions = torch.arange(ACTION_DIM).unsqueeze(0)
    start, end = 40, 54                       # teacher_scores 块的位置

    model = torch.load(resolve_model_path(model_path), weights_only=False)
    optimizer = torch.optim.Adam(model.parameters(), lr)
    n = x.shape[0]
    for epoch in range(epochs):
        order = torch.randperm(n)
        total = 0.0
        for begin in range(0, n, batch):
            idx = order[begin:begin + batch]
            acts = all_actions.repeat(len(idx), 1)
            xa = build_action_inputs(x[idx], acts).view(-1, state_dim + ACTION_DIM)
            scores = model(xa).view(-1, ACTION_DIM)            # 分数越小越好
            teacher = x[idx][:, start:end]

            diff_t = teacher.unsqueeze(2) - teacher.unsqueeze(1)   # t_a - t_b < 0 → a 更好
            diff_s = scores.unsqueeze(2) - scores.unsqueeze(1)
            legal = mask[idx]
            pair = (diff_t < -1e-6) & (legal.unsqueeze(2) > 0) & (legal.unsqueeze(1) > 0)
            if pair.sum() == 0:
                continue
            hinge = torch.relu(margin + diff_s)[pair]
            loss = hinge.mean()
            optimizer.zero_grad()
            loss.backward()
            optimizer.step()
            total += loss.item() * len(idx)
        print("epoch %2d  ranking loss %.5f" % (epoch, total / n))

    save_policy(model, model_path)
    return 0


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return 1

    cmd = sys.argv[1]
    if cmd == "distill":
        epochs = int(sys.argv[5]) if len(sys.argv) > 5 else 30
        return distill(sys.argv[2], sys.argv[3], sys.argv[4], epochs)
    if cmd == "imitate":
        epochs = int(sys.argv[4]) if len(sys.argv) > 4 else 200
        return imitate(sys.argv[2], sys.argv[3], epochs)
    if cmd == "imitate_score":
        epochs = int(sys.argv[4]) if len(sys.argv) > 4 else 300
        temperature = float(sys.argv[5]) if len(sys.argv) > 5 else 1.0
        hidden = int(sys.argv[6]) if len(sys.argv) > 6 else 30
        return imitate_score(sys.argv[2], sys.argv[3], epochs, temperature, hidden)
    if cmd == "sample":
        seed = int(sys.argv[5]) if len(sys.argv) > 5 else 800000
        player_type = sys.argv[6] if len(sys.argv) > 6 else "policy"
        mode = sys.argv[7] if len(sys.argv) > 7 else "none"
        normalize = len(sys.argv) > 8 and sys.argv[8].lower() not in ("0", "false")
        opponent = sys.argv[9] if len(sys.argv) > 9 else "simple_ai"
        return sample(sys.argv[2], int(sys.argv[3]), sys.argv[4], seed, player_type, mode, normalize, opponent)
    if cmd == "train":
        epochs = int(sys.argv[4]) if len(sys.argv) > 4 else 8
        lr = float(sys.argv[5]) if len(sys.argv) > 5 else 3e-4
        entropy = float(sys.argv[6]) if len(sys.argv) > 6 else 0.0
        return train(sys.argv[2], sys.argv[3], epochs, lr, 4096, entropy)
    if cmd == "sample_search":
        seed = int(sys.argv[5]) if len(sys.argv) > 5 else 800000
        mode = sys.argv[6] if len(sys.argv) > 6 else "none"
        opponent = sys.argv[7] if len(sys.argv) > 7 else "simple_ai"
        rollouts = int(sys.argv[8]) if len(sys.argv) > 8 else 12
        return sample_search(int(sys.argv[2]), sys.argv[3], sys.argv[4], seed, mode, opponent, rollouts)
    if cmd == "distill_costs":
        epochs = int(sys.argv[4]) if len(sys.argv) > 4 else 150
        temperature = float(sys.argv[5]) if len(sys.argv) > 5 else 1.0
        hidden = int(sys.argv[6]) if len(sys.argv) > 6 else 120
        return distill_costs(sys.argv[2], sys.argv[3], epochs, temperature, hidden)
    if cmd == "train_score":
        epochs = int(sys.argv[4]) if len(sys.argv) > 4 else 8
        lr = float(sys.argv[5]) if len(sys.argv) > 5 else 3e-4
        temperature = float(sys.argv[6]) if len(sys.argv) > 6 else 1.0
        entropy = float(sys.argv[7]) if len(sys.argv) > 7 else 0.0
        kl_beta = float(sys.argv[8]) if len(sys.argv) > 8 else 0.0
        return train_score(sys.argv[2], sys.argv[3], epochs, lr, temperature, entropy, kl_beta)
    if cmd == "residual_init":
        hidden = int(sys.argv[3]) if len(sys.argv) > 3 else 120
        model = ResidualPolicy(54 + ACTION_DIM, hidden)
        save_policy(model, sys.argv[2])
        print("已创建残差模型（输出层零初始化，策略=老师），隐藏单元 %d" % hidden)
        return 0
    if cmd == "train_residual":
        epochs = int(sys.argv[4]) if len(sys.argv) > 4 else 6
        lr = float(sys.argv[5]) if len(sys.argv) > 5 else 1e-4
        temperature = float(sys.argv[6]) if len(sys.argv) > 6 else 1.0
        kl_beta = float(sys.argv[7]) if len(sys.argv) > 7 else 0.0
        return train_residual(sys.argv[2], sys.argv[3], epochs, lr, temperature, kl_beta)
    if cmd == "train_pairwise":
        epochs = int(sys.argv[4]) if len(sys.argv) > 4 else 6
        lr = float(sys.argv[5]) if len(sys.argv) > 5 else 1e-4
        margin = float(sys.argv[6]) if len(sys.argv) > 6 else 0.05
        return train_pairwise(sys.argv[2], sys.argv[3], epochs, lr, margin)

    print("未知命令: %s" % cmd)
    return 1


if __name__ == "__main__":
    sys.exit(main())
