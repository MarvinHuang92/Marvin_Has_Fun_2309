# -*- coding: utf-8 -*-
"""从对局 JSON 找"可疑垫牌"并还原当时手牌。

判定垫牌：领出花色是 S/H/C/D 之一时，某座位出的牌里**一张该花色都没有** -> 垫牌。
（主牌领出时不算，因为跟主牌/垫主牌分不开。）

用法：
    python scripts/probe_bad_discard.py 5      # 只看第 5 局
    python scripts/probe_bad_discard.py        # 全部
"""
import glob
import json
import os
import sys

DATA = r"D:\Programming\Marvin_Has_Fun_2309\40_Python\20261121_Tractor_game\data"
_SUIT = {"♠": "S", "♥": "H", "♣": "C", "♦": "D"}
NAMES = {0: "南(你)", 1: "东(下家)", 2: "北(对家)", 3: "西(上家)"}
JOKER = {"小王": "SJ", "大王": "BJ"}


def norm(c):
    if c in JOKER:
        return JOKER[c]
    if c and c[0] in _SUIT:
        return _SUIT[c[0]] + c[1:]
    return c


def rank_of(k):
    return k[1:]


def is_point(k):
    return rank_of(k) in ("5", "10", "K")


def main():
    want = int(sys.argv[1]) if len(sys.argv) > 1 else None
    files = sorted(glob.glob(os.path.join(DATA, "deal_20261123_2[012]*.json")))
    for path in files:
        d = json.load(open(path, encoding="utf-8"))
        if want is not None and d["deal_no"] != want:
            continue
        # 老存档用 short（"SJ"），新存档用 label（"♠J"/"小王"）——统一归一化
        hands = {int(k): [norm(c) for c in v]
                 for k, v in d["hands_start"].items()}
        buriers = {h["burier"] for h in d.get("bottom_history", [])}
        missing = {s: 0 for s in range(4)}
        hits = []
        for i, tk in enumerate(d["tricks"], 1):
            lead = tk["lead"]
            lead_short = norm(lead[0])
            lead_suit = lead_short[0] if lead_short[0] in "SHCD" else None
            if lead_suit is None:
                pass                        # 主牌领出，不判定
            else:
                for (seat, cards) in tk["plays"]:
                    if seat == tk["leader"]:
                        continue
                    keys = [norm(c) for c in cards]
                    if any(k[0] == lead_suit for k in keys):
                        continue            # 跟了花色，不是垫牌
                    n_tr = sum(1 for k in keys
                               if k[0] not in "SHCD" or rank_of(k) in ("2",)
                               or rank_of(k) == str(d["level"]))
                    pts = sum(10 for k in keys if is_point(k))
                    # 成对的分数牌
                    pair_pts = 0
                    cnt = {}
                    for k in keys:
                        cnt[k] = cnt.get(k, 0) + 1
                    for k, n in cnt.items():
                        if n >= 2 and is_point(k):
                            pair_pts += 10 * n
                    if n_tr >= 2 or pair_pts >= 20:
                        hits.append((i, seat, cards, n_tr, pts, pair_pts,
                                     list(hands[seat]),
                                     missing[seat] if seat in buriers else 0))
            for (seat, cards) in tk["plays"]:
                for c in cards:
                    k = norm(c)
                    if k in hands[seat]:
                        hands[seat].remove(k)
                    else:
                        missing[seat] += 1
        for (i, seat, cards, n_tr, pts, pair_pts, hand, miss) in hits:
            print("=" * 74)
            print("第 %d 局 第 %d 墩：%s 缺门垫牌 -> %s"
                  % (d["deal_no"], i, NAMES[seat], " ".join(cards)))
            print("   垫掉：主牌 %d 张、分 %d 分（其中对子分 %d）"
                  % (n_tr, pts, pair_pts))
            tag = (" <- 庄子/换过底，记录里缺 %d 张" % miss) if miss else ""
            print("   当时手牌 (%d 张)：%s%s"
                  % (len(hand), " ".join(hand), tag))


if __name__ == "__main__":
    main()
