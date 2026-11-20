# -*- coding: utf-8 -*-
"""树集成 vs 神经网络：同一份数据、同一个切分、同一个标签

对照组（都吃 game_log/02_nn_sample_data_full_v2.csv 的同一批样本）：
    输入 = 第 0~53 列（40 维 state + 14 维 action one-hot）
    标签 = 第 54 列（advanced_ai 的启发式期望罚分）
    按 game_id（第 55 列）分组切分，同一局不会跨训练/验证

    LightGBM   400~800 轮，num_leaves 63
    MLP        54 → 30 → 1（就是项目里 model_heur_30 的结构）+ Adam + MSE
               给两个训练预算：2001 步（项目当年的设置）和 8004 步（4 组 × 2001）

产出（供 evaluate.py 调用）：
    models/lgb_heur.pkl         LightGBM，全量重训
    models/mlp_heur_same.pth    MLP，全量重训

用法：
    python train_gbdt_compare.py
"""

import sys
import time

import numpy as np
import pandas as pd
import torch
import torch.nn as nn

try:
    import lightgbm as lgb
    HAS_LGB = True
except ImportError:                      # 没装 LightGBM 时退回自己写的直方图 GBDT
    HAS_LGB = False
    from gbdt import GBDT, save_model as save_gbdt

CSV = "game_log/02_nn_sample_data_full_v2.csv"
N_FEAT = 54
MLP_HIDDEN = 30
MLP_BATCH = 8000
MLP_LR = 5e-3            # 与项目一致：新建模型时 learning_rate ×10
LGB_PARAMS = {
    "objective": "regression",
    "metric": "l2",
    "learning_rate": 0.05,
    "num_leaves": 63,
    "min_data_in_leaf": 20,
    "feature_fraction": 0.9,
    "bagging_fraction": 0.8,
    "bagging_freq": 1,
    "verbosity": -1,
    "num_threads": 0,
    "seed": 0,
}
LGB_ROUNDS = 800


def load_data():
    df = pd.read_csv(CSV, header=None)
    X = df.iloc[:, :N_FEAT].to_numpy(dtype=np.float32)
    y = df.iloc[:, N_FEAT].to_numpy(dtype=np.float64)
    gid = df.iloc[:, N_FEAT + 1].astype(str).to_numpy()
    return X, y, gid


def group_split(gid, val_ratio=0.15, seed=0):
    """按对局切分：同一局的所有样本只会出现在训练集或验证集一侧"""
    ug = np.unique(gid)
    rng = np.random.default_rng(seed)
    rng.shuffle(ug)
    val_games = set(ug[:max(1, int(len(ug) * val_ratio))])
    mask = np.fromiter((g in val_games for g in gid), dtype=bool, count=len(gid))
    return ~mask, mask


def build_mlp(hidden=MLP_HIDDEN):
    torch.manual_seed(0)
    return nn.Sequential(nn.Linear(N_FEAT, hidden), nn.ReLU(), nn.Linear(hidden, 1))


def train_mlp(X, y, steps, hidden=MLP_HIDDEN, batch=MLP_BATCH, lr=MLP_LR):
    model = build_mlp(hidden)
    opt = torch.optim.Adam(model.parameters(), lr=lr)
    loss_fn = nn.MSELoss()
    xt = torch.from_numpy(np.asarray(X, dtype=np.float32))
    yt = torch.from_numpy(np.asarray(y, dtype=np.float32)).view(-1, 1)
    n = len(xt)
    g = torch.Generator().manual_seed(0)
    for _ in range(steps):
        idx = torch.randint(0, n, (min(batch, n),), generator=g)
        opt.zero_grad()
        loss = loss_fn(model(xt[idx]), yt[idx])
        loss.backward()
        opt.step()
    return model


def mlp_predict(model, X):
    with torch.no_grad():
        return model(torch.from_numpy(np.asarray(X, dtype=np.float32))).view(-1).numpy()


def metrics(pred, y):
    pred = np.asarray(pred, dtype=np.float64).reshape(-1)
    y = np.asarray(y, dtype=np.float64).reshape(-1)
    return float(np.mean((pred - y) ** 2)), float(np.mean(np.abs(pred - y)))


def main():
    print("=" * 74)
    print("数据：%s" % CSV)
    X, y, gid = load_data()
    tr, va = group_split(gid)
    print("样本 %d（训练 %d / 验证 %d，按 game_id 分组，共 %d 局）"
          % (len(X), tr.sum(), va.sum(), len(np.unique(gid))))
    print("标签：均值 %.4f  标准差 %.4f   （常数预测的验证 MSE = %.4f）"
          % (y.mean(), y.std(), np.mean((y[va] - y[tr].mean()) ** 2)))
    print("LightGBM: %s" % (lgb.__version__ if HAS_LGB else "未安装，退回自带 GBDT"))
    print()

    rows = []

    # ---- 树 ----
    t0 = time.time()
    if HAS_LGB:
        m_tree = lgb.train(LGB_PARAMS, lgb.Dataset(X[tr], y[tr]), num_boost_round=LGB_ROUNDS)
        pred = m_tree.predict(X[va])
        name = "LightGBM(63叶/%d轮)" % LGB_ROUNDS
    else:
        m_tree = GBDT(n_trees=250, depth=6, lr=0.06).fit(X[tr], y[tr])
        pred = m_tree.predict(X[va])
        name = "自带GBDT(250棵/深度6)"
    mse, mae = metrics(pred, y[va])
    rows.append((name, mse, mae, time.time() - t0))
    print("%-20s 验证 MSE %.4f  MAE %.4f  (%.1fs)" % (name, mse, mae, time.time() - t0))

    # ---- MLP 两个训练预算 ----
    for steps in (2001, 8004):
        t0 = time.time()
        m = train_mlp(X[tr], y[tr], steps=steps)
        mse, mae = metrics(mlp_predict(m, X[va]), y[va])
        rows.append(("MLP 30 单位 %d 步" % steps, mse, mae, time.time() - t0))
        print("%-20s 验证 MSE %.4f  MAE %.4f  (%.1fs)"
              % ("MLP 30 单位 %d 步" % steps, mse, mae, time.time() - t0))

    print()
    print("=" * 74)
    print("%-22s %10s %10s %8s" % ("模型", "验证MSE", "验证MAE", "训练秒"))
    for n, a, b, c in rows:
        print("%-22s %10.4f %10.4f %8.1f" % (n, a, b, c))
    print("=" * 74)

    # ---- 全量重训，存成对局可用的模型 ----
    print()
    print("用全部 %d 条样本重训，供 evaluate.py 调用……" % len(X))
    import pickle
    t0 = time.time()
    if HAS_LGB:
        full_tree = lgb.train(LGB_PARAMS, lgb.Dataset(X, y), num_boost_round=LGB_ROUNDS)
        with open("models/lgb_heur.pkl", "wb") as f:
            pickle.dump(full_tree, f, protocol=4)
        print("  LightGBM -> models/lgb_heur.pkl  (%.1fs)" % (time.time() - t0))
    else:
        full_tree = GBDT(n_trees=250, depth=6, lr=0.06).fit(X, y)
        print("  GBDT -> %s  (%.1fs)" % (save_gbdt(full_tree, "gbdt_heur.pkl"), time.time() - t0))

    t0 = time.time()
    mlp_full = train_mlp(X, y, steps=8004)
    torch.save(mlp_full, "models/mlp_heur_same.pth")
    print("  MLP      -> models/mlp_heur_same.pth  (%.1fs)" % (time.time() - t0))
    print()
    print("接下来跑评测（固定种子、双方轮座、4000 局）：")
    print("  python evaluate.py 4000 lgb_heur.pkl       none 0 gbm     950000 simple_ai")
    print("  python evaluate.py 4000 mlp_heur_same.pth  none 0 network 950000 simple_ai")
    return 0


if __name__ == "__main__":
    sys.exit(main())
