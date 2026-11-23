# -*- coding: utf-8 -*-
"""从对局 JSON 还原某一墩开始时的手牌。

注意：庄家（或换底者）的手牌 = 开局 25 张 + 底牌 8 张 − 自己埋掉的 8 张，
而 `hands_start` 记的是**开局**手牌，所以庄家那条会少 8 张（见 `missing`）。
非庄家/非换底者的手牌可以直接从开局手牌减出来 ✓

用法::
    python scripts/probe_deal_replay.py <json> <墩号(1基)>
"""
import json
import sys

DEFAULT = (r"D:\Programming\Marvin_Has_Fun_2309\40_Python\20261121_Tractor_game"
           r"\data\deal_20261123_205650_002.json")
_SUIT = {"♠": "S", "♥": "H", "♣": "C", "♦": "D"}
NAMES = {0: "南(你)", 1: "东(下家)", 2: "北(对家)", 3: "西(上家)"}


def norm(card: str) -> str:
    """出牌记录用 label（"♠J"/"小王"），开局手牌用 short（"SJ"/"SJ"）——统一起来。

    注意 short 有个历史包袱：小王也是 "SJ"，和 ♠J 撞名。这里按 label 优先归一。
    """
    if card == "小王":
        return "SJ"
    if card == "大王":
        return "BJ"
    if card and card[0] in _SUIT:
        return _SUIT[card[0]] + card[1:]
    return card


def main():
    path = sys.argv[1] if len(sys.argv) > 1 else DEFAULT
    trick_no = int(sys.argv[2]) if len(sys.argv) > 2 else 10
    d = json.load(open(path, encoding="utf-8"))
    print("=" * 74)
    print("第 %d 局：庄家 %s，级牌 %d，主牌 %s"
          % (d["deal_no"], NAMES[d["zhuang"]], d["level"], d["trump"]))
    print("=" * 74)

    # 老存档用 short（"SJ"），新存档用 label（"♠J"/"小王"）——统一归一化
    hands = {int(k): [norm(c) for c in v]
             for k, v in d["hands_start"].items()}
    buriers = {h["burier"] for h in d.get("bottom_history", [])}
    missing = {s: 0 for s in range(4)}

    for i, tk in enumerate(d["tricks"], 1):
        if i == trick_no:
            print("第 %d 墩开始时的手牌（领出者 %s）" % (i, NAMES[tk["leader"]]))
            print("-" * 74)
            for s in range(4):
                tag = "  <- 庄家/换过底，缺 %d 张（= 埋底后的差额）" % missing[s] \
                    if missing[s] else ""
                print("  %-9s (%2d 张) %s%s"
                      % (NAMES[s], len(hands[s]), " ".join(hands[s]), tag))
            print()
            print("本墩过程：")
            print("  领出 %s：%s" % (NAMES[tk["leader"]], " ".join(tk["lead"])))
            for (seat, cards) in tk["plays"]:
                note = "  (这是领出)" if seat == tk["leader"] else ""
                print("  %-9s 出 %s%s" % (NAMES[seat], " ".join(cards), note))
            print("  赢家 %s，本墩 %d 分（%s）"
                  % (NAMES[tk["winner"]], tk["points"], tk["kind"]))
            # 重点：本墩里出分的那位
            for (seat, cards) in tk["plays"]:
                pts = sum(10 if c[1:] in ("5", "10", "K") else 0 for c in cards)
                if pts:
                    print()
                    print("  ** %s 这一手送了 %d 分：%s"
                          % (NAMES[seat], pts, " ".join(cards)))
                    if seat in buriers:
                        print("     （它是庄家/换过底，手牌记录缺 %d 张，"
                              "这里只能看到开局剩下的）" % missing[seat])
            return 0
        for (seat, cards) in tk["plays"]:
            for c in cards:
                key = norm(c)
                if key in hands[seat]:
                    hands[seat].remove(key)
                else:
                    missing[seat] += 1      # 庄家/换底者手上有底牌，缺的就计数
    print("没有第 %d 墩" % trick_no)
    return 1


if __name__ == "__main__":
    sys.exit(main())
