# -*- coding: utf-8 -*-
"""一个够用的梯度提升树（numpy，直方图分裂，平方损失）

为什么自己写：环境里没有 lightgbm / sklearn，pip 也连不上外网。
但对照实验要的只是「树集成」这一族，实现上用小直方图 GBDT 就够了，
和 LightGBM 的差别主要在工程优化（直方图减法、leaf-wise 生长、类别特征处理），
算法骨架是一样的。

用法：
    from gbdt import GBDT, save_model, load_model
    m = GBDT(n_trees=250, depth=6, lr=0.06).fit(X, y)
    pred = m.predict(X)

注意：
- 分箱用训练集的分位点，predict 时用同一套边界
- 叶子值用 mean(residual)，没有 hessian（平方损失的 hessian 恒为 1）
"""

import os
import pickle

import numpy as np

MODEL_DIR = "models"


class GBDT(object):
    def __init__(self, n_trees=250, depth=6, lr=0.06, n_bins=64,
                 min_leaf=20, l2=1.0, seed=0):
        self.n_trees = n_trees
        self.depth = depth
        self.lr = lr
        self.n_bins = n_bins
        self.min_leaf = min_leaf
        self.l2 = l2
        self.seed = seed
        self.edges = None          # list[np.ndarray]，每个特征的分箱边界
        self.init = 0.0
        self.trees = []            # 每棵树：dict(feat/thr/left/right/value 一维数组)
        # 拍平后的加速结构（predict 用）
        self._F = None
        self._T = None
        self._max_depth = 0
        self._feat = self._thr = self._left = self._right = self._value = None

    # ---------------- 分箱 ----------------
    def _fit_edges(self, X):
        edges = []
        for f in range(X.shape[1]):
            col = X[:, f]
            q = np.quantile(col, np.linspace(0.0, 1.0, self.n_bins + 1)[1:-1])
            edges.append(np.unique(q))
        return edges

    def _bin(self, X, edges=None):
        edges = self.edges if edges is None else edges
        out = np.empty(X.shape, dtype=np.uint8)
        for f, e in enumerate(edges):
            # searchsorted(left) 得到「第一个 >= x 的边界下标」，正好是分箱号
            out[:, f] = np.searchsorted(e, X[:, f], side="left")
        return out

    # ---------------- 建树 ----------------
    def _best_split(self, Xb, r, rows):
        n = len(rows)
        tot = float(r[rows].sum())
        rr = r[rows]
        best_gain, best = -1.0, None
        for f in range(Xb.shape[1]):
            b = Xb[rows, f].astype(np.intp)
            s = np.bincount(b, weights=rr, minlength=self.n_bins)
            c = np.bincount(b, minlength=self.n_bins)
            cs = np.cumsum(s)[:-1]
            cc = np.cumsum(c)[:-1]
            lc = cc
            rc = n - lc
            ok = (lc >= self.min_leaf) & (rc >= self.min_leaf)
            if not ok.any():
                continue
            ls = cs
            rs = tot - ls
            # 保护分母：lc/rc 可能为 0，先算再 where 会报除零
            gl = ls * ls / np.maximum(lc, 1)
            gr = rs * rs / np.maximum(rc, 1)
            gain = np.where(ok, gl + gr, -1.0)
            k = int(gain.argmax())
            if gain[k] > best_gain:
                best_gain, best = float(gain[k]), (f, k)
        return best

    def _grow(self, Xb, r, rows, depth, node_arrays):
        feat, thr, left, right, value = node_arrays
        node = len(feat)
        feat.append(-1)
        thr.append(0)
        left.append(-1)
        right.append(-1)
        value.append(0.0)
        if depth == 0 or len(rows) < 2 * self.min_leaf:
            value[node] = float(r[rows].sum() / (len(rows) + self.l2)) if len(rows) else 0.0
            return node
        best = self._best_split(Xb, r, rows)
        if best is None:
            value[node] = float(r[rows].sum() / (len(rows) + self.l2))
            return node
        f, k = best
        mask = Xb[rows, f] <= k
        if not mask.any() or mask.all():
            value[node] = float(r[rows].sum() / (len(rows) + self.l2))
            return node
        feat[node] = f
        thr[node] = k
        left[node] = self._grow(Xb, r, rows[mask], depth - 1, node_arrays)
        right[node] = self._grow(Xb, r, rows[~mask], depth - 1, node_arrays)
        return node

    def _build_tree(self, Xb, r):
        arrays = ([], [], [], [], [])
        self._grow(Xb, r, np.arange(len(r)), self.depth, arrays)
        feat, thr, left, right, value = arrays
        return {"feat": np.array(feat, dtype=np.int32),
                "thr": np.array(thr, dtype=np.int32),
                "left": np.array(left, dtype=np.int32),
                "right": np.array(right, dtype=np.int32),
                "value": np.array(value, dtype=np.float64)}

    # ---------------- 训练 ----------------
    def fit(self, X, y, verbose=False):
        X = np.asarray(X, dtype=np.float32)
        y = np.asarray(y, dtype=np.float64)
        self.edges = self._fit_edges(X)
        Xb = self._bin(X)
        self.init = float(y.mean())
        pred = np.full(len(y), self.init)
        self.trees = []
        for t in range(self.n_trees):
            r = y - pred
            tree = self._build_tree(Xb, r)
            self.trees.append(tree)
            pred += self.lr * self._eval_trees([tree], Xb)
            if verbose and (t + 1) % 50 == 0:
                mse = float(np.mean((y - pred) ** 2))
                print("    tree %3d/%d  train MSE %.4f" % (t + 1, self.n_trees, mse))
        self._flatten()
        return self

    # ---------------- 预测 ----------------
    def _eval_trees(self, trees, Xb):
        """单个/少数几棵树时的预测（训练中更新 pred 用）"""
        out = np.zeros(len(Xb))
        for tree in trees:
            feat, thr, left, right, value = (tree["feat"], tree["thr"],
                                             tree["left"], tree["right"], tree["value"])
            stack = [(0, np.arange(len(Xb)))]
            while stack:
                node, rows = stack.pop()
                f = feat[node]
                if f < 0:
                    out[rows] += value[node]
                else:
                    m = Xb[rows, f] <= thr[node]
                    stack.append((left[node], rows[m]))
                    stack.append((right[node], rows[~m]))
        return out

    def _flatten(self):
        """把所有树拍成 (T, max_nodes) 的二维数组，predict 时按层一次性走完"""
        self._T = len(self.trees)
        max_nodes = max(len(t["feat"]) for t in self.trees)
        T = self._T
        self._feat = np.full((T, max_nodes), -1, dtype=np.int32)
        self._thr = np.zeros((T, max_nodes), dtype=np.int32)
        self._left = np.zeros((T, max_nodes), dtype=np.int32)
        self._right = np.zeros((T, max_nodes), dtype=np.int32)
        self._value = np.zeros((T, max_nodes), dtype=np.float64)
        for i, t in enumerate(self.trees):
            n = len(t["feat"])
            self._feat[i, :n] = t["feat"]
            self._thr[i, :n] = t["thr"]
            self._left[i, :n] = t["left"]
            self._right[i, :n] = t["right"]
            self._value[i, :n] = t["value"]
        self._max_depth = 0
        for t in self.trees:
            d, stack = 0, [(0, 0)]
            while stack:
                node, dep = stack.pop()
                d = max(d, dep)
                if t["feat"][node] >= 0:
                    stack.append((t["left"][node], dep + 1))
                    stack.append((t["right"][node], dep + 1))
            self._max_depth = max(self._max_depth, d)

    def predict(self, X):
        X = np.asarray(X, dtype=np.float32)
        if X.ndim == 1:
            X = X[None, :]
        Xb = self._bin(X)
        m = len(Xb)
        T = self._T
        node = np.zeros((m, T), dtype=np.int32)      # 每行每棵树当前节点
        tidx = np.arange(T)[None, :]
        ridx = np.arange(m)[:, None]
        for _ in range(self._max_depth + 1):
            f = self._feat[tidx, node]               # (m, T)
            thr = self._thr[tidx, node]
            x = Xb[ridx, np.maximum(f, 0)]
            go_left = x <= thr
            nxt = np.where(go_left, self._left[tidx, node], self._right[tidx, node])
            node = np.where(f >= 0, nxt, node)       # 叶子原地不动
        return self.init + self.lr * self._value[tidx, node].sum(axis=1)


# ---------------- 存取 ----------------
def resolve_path(path):
    if os.path.exists(path):
        return path
    cand = os.path.join(MODEL_DIR, os.path.basename(path))
    return cand if os.path.exists(cand) else path


def save_model(model, path):
    path = path if os.path.isabs(path) else os.path.join(MODEL_DIR, os.path.basename(path))
    with open(path, "wb") as f:
        pickle.dump(model, f, protocol=4)
    return path


def load_model(path):
    with open(resolve_path(path), "rb") as f:
        return pickle.load(f)
