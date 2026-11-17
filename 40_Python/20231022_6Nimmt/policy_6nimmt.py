# -*- coding: utf-8 -*-
"""
策略网络（第四轮）：输入 state，输出 14 个动作的 logits。

动作空间与 Q 网络一致：
  0~9  = 出第几张手牌
  10~13= 打出最小牌后吃第几行（1~4 行）
非法动作用 -1e9 的掩码屏蔽。

与 Q 网络的区别：
  Q 网络要「枚举所有动作取最小」，训练标签是反事实估值；
  策略网络直接对动作给分布，训练只用实际做过的那一手，不需要反事实。
"""

import os

import torch
from torch import nn

from neural_network_6nimmt import MODEL_DIR, resolve_model_path

POLICY_ACTIONS = 14
MASK_VALUE = -1e9


class PolicyNetwork(nn.Module):
    def __init__(self, n_in, n_hidden=30, n_out=POLICY_ACTIONS):
        super().__init__()
        self.stack = nn.Sequential(
            nn.Linear(n_in, n_hidden),
            nn.ReLU(),
            nn.Linear(n_hidden, n_out),
        )

    def forward(self, x):
        return self.stack(x)


def legal_mask(situation, hand_count):
    """返回长度 14 的 0/1 掩码：出牌时只有前 hand_count 张手牌合法，收行时只有 10~13 合法"""
    mask = [0.0] * POLICY_ACTIONS
    if situation == 0:
        for i in range(min(hand_count, 10)):
            mask[i] = 1.0
    else:
        for i in range(10, 14):
            mask[i] = 1.0
    return mask


def apply_mask(logits, mask_tensor):
    """把非法动作的 logits 压到 -1e9（近似 -inf）：mask=1 保持原值，mask=0 减 1e9"""
    return logits + (mask_tensor - 1.0) * 1e9


def load_policy(path=None):
    path = resolve_model_path(path if path is not None else "models/model_policy.pth")
    print("Loading policy: %s\n" % path)
    return torch.load(path, weights_only=False)


def save_policy(model, path):
    """只写文件名时，统一存到 models/ 下（与 load_policy 保持一致）"""
    if os.sep not in path and "/" not in path:
        path = os.path.join(MODEL_DIR, path)
    torch.save(model, path)
    print("Saving policy: %s" % path)


# ===== 第五轮：打分式策略 =====
# 直接用 Q 网络的架构（state + 动作 one-hot → 1 个分数），把分数取负再 softmax 当动作概率。
# 好处：网络能看到「这是哪个动作」，天然解决了「共享隐藏层无法把第 i 张手牌路由到第 i 个输出」的问题。

# 采样温度：分数除以它再 softmax；越小越接近 argmin（贪心）
SCORE_TEMPERATURE = 1.0


def build_action_inputs(states, actions):
    """把 (state, 动作) 拼成 Q 网络要的输入：state + 14 维 one-hot

    states: (n, state_dim) 张量；actions: (n, k) 张量（每行 k 个候选动作）
    返回 (n, k, state_dim + 14)
    """
    n, k = actions.shape
    state_dim = states.shape[1]
    x = states.unsqueeze(1).repeat(1, k, 1)
    onehot = torch.zeros(n, k, POLICY_ACTIONS)
    onehot.scatter_(2, actions.unsqueeze(2).long(), 1.0)
    return torch.cat([x, onehot], dim=2)


def scores_to_logits(scores, temperature=SCORE_TEMPERATURE):
    """Q 分数越小越好，所以取负；温度控制采样随机性"""
    return -scores / temperature


class ResidualPolicy(nn.Module):
    """score(s, a) = alpha * t(s, a) + net(s, a)（第八轮）

    t 取自 state 里的 teacher_scores 块（第 40~53 位，每个动作一个老师分数）。
    输出层零初始化 ⇒ 初始 correction = 0 ⇒ 策略严格等于老师（起点 74.65%），
    网络只需要学「老师哪里算错了」，比「把 t 当普通特征重新学一遍」更有针对性。
    """
    residual = True                     # 玩家侧据此决定要不要叠加 alpha * t
    teacher_slice = (40, 54)

    def __init__(self, n_in, n_hidden=120):
        super().__init__()
        self.net = nn.Sequential(
            nn.Linear(n_in, n_hidden),
            nn.ReLU(),
            nn.Linear(n_hidden, 1),
        )
        self.alpha = nn.Parameter(torch.tensor(1.0))
        nn.init.zeros_(self.net[-1].weight)
        nn.init.zeros_(self.net[-1].bias)

    def forward(self, x):
        return self.net(x).view(-1)
