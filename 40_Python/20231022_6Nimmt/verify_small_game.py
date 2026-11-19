# -*- coding: utf-8 -*-
"""用 2023 年的游戏引擎给 small_game_solver 做规则对照

做法：把 game_6nimmt.placeCard（引擎里"放一张牌"的规则，search/rollout 用的就是它）
当成标准答案，喂给两边完全相同的局面，比较「吃到多少牛头 + 桌面变成什么样」。

注意：placeCard 里的行容量写死为 5，所以这里用 cap=5 对照；
小游戏只用 cap=3，两者差别仅在那一个常数（place_options 的 cap 参数）。

需要能 import torch 的解释器：
    D:\\Programming\\Python_dir_38\\python.exe verify_small_game.py
"""

import random
import sys

import game_6nimmt as engine
import small_game_solver as solver

N_TRIALS = 3000
TABLE = {v: engine.cardBullheads(v) for v in range(1, 105)}


def random_table(rnd):
    """随机造一个 4 行、每行 1~5 张、牌面递增且互不相同的桌面"""
    cards = rnd.sample(range(1, 105), 20)
    rows = []
    pos = 0
    for _ in range(4):
        n = rnd.randint(1, 5)
        chunk = sorted(cards[pos:pos + n])
        pos += n
        rows.append(list(chunk))
    rows.sort(key=tuple)          # 两边用同一个行顺序，pick=0 才可比
    return rows


def main():
    bad = 0

    # 1) 牛头计分
    for v in range(1, 105):
        if engine.cardBullheads(v) != solver.bullheads(v):
            print("牛头不一致: %d  engine=%d solver=%d" % (v, engine.cardBullheads(v), solver.bullheads(v)))
            bad += 1
    print("牛头计分 1~104 全部一致: %s" % (bad == 0))

    # 2) 放置规则
    rnd = random.Random(20231120)
    for t in range(N_TRIALS):
        rows = random_table(rnd)
        used = set(c for r in rows for c in r)
        free = [c for c in range(1, 105) if c not in used]
        card = rnd.choice(free)
        pick = rnd.randrange(4)          # "比所有行尾都小"时选哪一行
        dealt = [c for r in rows for c in r] + [card]
        if len(set(dealt)) != len(dealt):
            continue

        erows = [list(r) for r in rows]
        e_taken = engine.placeCard(erows, card, lambda cur, p=pick: p, 104)

        kind, opts = solver.place_options(
            tuple(tuple(r) for r in rows), card, cap=5, table=TABLE)
        idx = pick if kind == "choose" else 0
        s_rows, s_taken = opts[idx]

        if e_taken != s_taken or sorted(tuple(r) for r in s_rows) != sorted(tuple(r) for r in erows):
            bad += 1
            if bad <= 5:
                print("不一致 #%d: rows=%r card=%d pick=%d" % (t, rows, card, pick))
                print("   engine: taken=%d rows=%r" % (e_taken, erows))
                print("   solver: taken=%d rows=%r kind=%s"
                      % (s_taken, [list(r) for r in s_rows], kind))

    print("%d 个随机局面，放置规则不一致 %d 个" % (N_TRIALS, bad))
    print()
    if bad == 0:
        print("结论：small_game_solver 的规则层与旧引擎完全一致（行容量常数除外）。")
    else:
        print("结论：存在不一致，需要检查。")
    return 0 if bad == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
