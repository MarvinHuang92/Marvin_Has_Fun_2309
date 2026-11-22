# -*- coding: utf-8 -*-
"""量一下：按用户的排除规则剪枝之后，埋底的动作空间还有多大。

排除顺序（用户给的优先级）：王 → 拖拉机 → 级牌 → 2 → A → AAK / AKK。
剩下的牌里选 8 张埋掉。

统计每局的"可选张数 n"和对应的 C(n,8)，以及评估成本。
"""
import sys
from collections import Counter
from math import comb

sys.path.insert(0, r"D:\Programming\Marvin_Has_Fun_2309\40_Python\20261121_Tractor_game\scripts")

from tractor.cards import is_trump  # noqa: E402
from tractor.engine import TractorGame  # noqa: E402


def protected_ids(pool, level, trump):
    """返回"不该埋"的牌（按用户的优先级），以及每一步各排除了多少。"""
    prot = set()
    steps = Counter()

    def kind(c):
        return "T" if is_trump(c, level, trump) else c.suit

    # 每个 (花色,点数) 我持有几张
    cnt = Counter((c.suit, c.rank) for c in pool)

    # 1) 王
    for c in pool:
        if c.is_joker:
            prot.add(id(c))
            steps["王"] += 1

    # 2) 拖拉机（同门里连续两对以上）
    by_kind = {}
    for c in pool:
        by_kind.setdefault(kind(c), Counter())[c.rank] += 1
    for k, ranks in by_kind.items():
        pair_ranks = sorted(r for r, n in ranks.items() if n >= 2)
        in_tractor = set()
        for i in range(len(pair_ranks) - 1):
            if pair_ranks[i + 1] == pair_ranks[i] + 1:
                in_tractor.add(pair_ranks[i])
                in_tractor.add(pair_ranks[i + 1])
        for c in pool:
            if kind(c) == k and c.rank in in_tractor and id(c) not in prot:
                prot.add(id(c))
                steps["拖拉机"] += 1

    # 3) 级牌
    for c in pool:
        if c.rank == level and id(c) not in prot:
            prot.add(id(c))
            steps["级牌"] += 1

    # 4) 常主 2
    for c in pool:
        if c.rank == 2 and id(c) not in prot:
            prot.add(id(c))
            steps["2"] += 1

    # 5) A
    for c in pool:
        if c.rank == 14 and id(c) not in prot:
            prot.add(id(c))
            steps["A"] += 1

    # 6) AAK / AKK（同门 A + K 对，或 A 对 + K）
    for c in pool:
        if id(c) in prot:
            continue
        k = kind(c)
        if cnt.get((c.suit, 14), 0) >= 1 and cnt.get((c.suit, 13), 0) >= 2:
            prot.add(id(c))
            steps["AAK/AKK"] += 1
        elif cnt.get((c.suit, 14), 0) >= 2 and cnt.get((c.suit, 13), 0) >= 1:
            prot.add(id(c))
            steps["AAK/AKK"] += 1
    return prot, steps


def main():
    deals = int(sys.argv[1]) if len(sys.argv) > 1 else 300
    dist = Counter()
    step_tot = Counter()
    spaces = []
    for d in range(deals):
        g = TractorGame(700000 + d)
        g.start_match()
        # 跑到"庄家要埋底"的那一刻
        for _ in range(300):
            if g.phase in ("bury_initial", "bury_extra"):
                break
            if g.phase == "play":
                break
            seat = g.acting_seat()
            if seat is None:
                break
            if g.phase in ("bid_initial", "bid_extra"):
                bids = g.legal_bids(seat)
                g.submit_bid(seat, bids[0] if bids else None)
            else:
                break
        if g.phase not in ("bury_initial", "bury_extra"):
            continue
        seat = g.pending_bury_by
        pool = list(g.hands[seat]) + list(g.bottom)
        if len(pool) != 33:
            continue
        prot, steps = protected_ids(pool, g.level, g.trump_suit)
        n = len(pool) - len(prot)
        dist[n] += 1
        step_tot.update(steps)
        spaces.append(comb(n, 8) if n >= 8 else 0)

    total = sum(dist.values())
    print("=" * 68)
    print("埋底可选张数分布（%d 局，每局 33 张里排掉不该埋的）" % total)
    print("=" * 68)
    print("  各类被排除的张数（平均每局）：")
    for k in ("王", "拖拉机", "级牌", "2", "A", "AAK/AKK"):
        print("    %-8s %.2f 张" % (k, step_tot[k] / max(1, total)))
    print()
    print("  剩余可选张数 n 的分布：")
    for n in sorted(dist):
        c = comb(n, 8) if n >= 8 else 0
        print("    n=%2d：%3d 局（%4.0f%%）  C(n,8)=%d"
              % (n, dist[n], 100.0 * dist[n] / total, c))
    spaces = [s for s in spaces if s]
    if spaces:
        spaces.sort()
        print()
        print("  C(n,8) 中位数 %d，最大 %d，平均 %.0f"
              % (spaces[len(spaces) // 2], spaces[-1], sum(spaces) / len(spaces)))
        print("  按 V 网络每次 30 微秒估：中位数约 %.1f ms，最大约 %.0f ms"
              % (spaces[len(spaces) // 2] * 30 / 1000.0, spaces[-1] * 30 / 1000.0))
        # 若 n < 8 的比例
        lack = sum(v for n, v in dist.items() if n < 8)
        print("  可选不足 8 张的局：%d（%.0f%%）" % (lack, 100.0 * lack / total))
    return 0


if __name__ == "__main__":
    sys.exit(main())
