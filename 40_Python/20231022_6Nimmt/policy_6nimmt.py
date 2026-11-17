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
