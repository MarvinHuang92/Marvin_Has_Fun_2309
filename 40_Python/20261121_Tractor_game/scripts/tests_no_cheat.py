# -*- coding: utf-8 -*-
"""作弊审计：换掉对手手牌，看 AI 的决策会不会变。

原理
----
一个**只依赖合法信息**的 AI，它的决策只能取决于：
  - 自己的手牌
  - 公开信息（出过的牌、比分、墩数、谁埋的底、级别/主花色…）

如果把**对手两家手牌互换**（张数、我手牌、公开信息全都不变），
合法 AI 的决策必须**完全一样**；只要变了，就说明它读到了隐藏信息。

跑法::

    python scripts/tests_no_cheat.py              # 审计全部四档
    python scripts/tests_no_cheat.py heuristic    # 只审计一档
"""
from __future__ import annotations

import os
import random
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from tractor.ai_select import AiEngine, LEVELS  # noqa: E402
from tractor.engine import TractorGame  # noqa: E402


def _make_ai(kind):
    """建 AI。搜索档改成**限节点数**，否则限时搜索本身不确定，审计无从谈起。"""
    ai = AiEngine(kind)
    if kind == "search":
        from tractor.ai_search import SearchAI

        ai._search = SearchAI(depth=40, time_limit=60.0, node_limit=8000)
    return ai


def _apply(game, seat, cards, is_lead):
    if is_lead:
        return game.play_lead(seat, cards)
    return game.play_follow(seat, cards)


def drive_to_decision(kind: str, seed: int, skip_plays: int):
    """跑到 play 阶段的第 skip_plays 个决策点，返回 (game1, game2, ai1, ai2, seat)。

    两个 game 状态完全一致；ai1/ai2 观测到的公开信息也完全一致。
    """
    g1 = TractorGame(seed)
    g1.start_match()
    g2 = TractorGame(seed)
    g2.start_match()
    ai1 = _make_ai(kind)
    ai2 = _make_ai(kind)
    ai1.begin_deal(g1)
    ai2.begin_deal(g2)

    # 亮主 / 埋底
    for _ in range(600):
        if g1.phase == "play":
            break
        seat = g1.acting_seat()
        if seat is None:
            return None
        if g1.phase in ("bid_initial", "bid_extra"):
            bid = ai1.bid(g1, seat)
            g1.submit_bid(seat, bid)
            g2.submit_bid(seat, bid)
        elif g1.phase in ("bury_initial", "bury_extra"):
            cards = ai1.bury(g1, seat)
            ok1, _ = g1.submit_bury(seat, cards)
            ok2, _ = g2.submit_bury(seat, cards)
            assert ok1 and ok2
            ai1.note_buried(seat, cards)
            ai2.note_buried(seat, cards)
        else:
            return None

    # 出若干手，两边同步
    for _ in range(skip_plays):
        if g1.phase != "play":
            break
        seat = g1.current_player
        lead = g1.trick.lead if (g1.trick and g1.trick.lead) else None
        # **两个实例都要真的做一次决策**：search/adv 会用各自的 RNG 抽样世界，
        # 只调一个的话两边 RNG 进度不同，后面比较就不公平了。
        # rule 档用的是**全局 random**：两个实例交替调用会共享随机流，
        # 这里每次调用前重设同一个种子，否则 rule 档会假阳性（它本身不确定）。
        random.seed(20261124)
        c1 = ai1.play(g1, seat)
        random.seed(20261124)
        c2 = ai2.play(g2, seat)
        assert sorted(c.label for c in c1) == sorted(c.label for c in c2), \
            "两个同步局面下同一 AI 给出不同决策（说明它本身不确定）"
        ok, msg = _apply(g1, seat, c1, lead is None)
        assert ok, msg
        ok, msg = _apply(g2, seat, c2, lead is None)
        assert ok, msg
        ai1.observe(g1, seat, c1, lead)
        ai2.observe(g2, seat, c2, lead)

    if g1.phase != "play":
        return None
    return g1, g2, ai1, ai2, g1.current_player


def _public_key(game):
    """所有玩家都能看到的信息：出过的牌、比分、当前这墩、墩数、级别/主花色。"""
    trick = ()
    if game.trick is not None:
        trick = tuple((s, tuple(c.label for c in cards)) for s, cards in game.trick.plays)
    return (game.trick_no, game.declarer_points, game.defender_points,
            game.level, game.trump_suit, trick,
            tuple(len(game.hands[s]) for s in range(4)))


def audit(kind: str, deals: int = 3, points: int = 8) -> int:
    """返回发现的可疑决策数。"""
    bad = 0
    total = 0
    for d in range(deals):
        for k in range(points):
            got = drive_to_decision(kind, 700000 + d * 31, 4 + k * 3)
            if got is None:
                continue
            g1, g2, ai1, ai2, seat = got

            # 在两个对手之间**同花色互换两张牌**：
            # 张数、每门张数、缺门、已出牌全都不变，只改变"谁拿着哪张"
            me = seat
            others = [s for s in range(4) if s != me]
            if len(others) < 2:
                continue
            a, b = others[0], others[1]
            swapped = False
            for suit in ("S", "H", "C", "D"):
                ca = [c for c in g2.hands[a] if c.suit == suit]
                cb = [c for c in g2.hands[b] if c.suit == suit]
                if ca and cb and ca[0].rank != cb[0].rank:
                    g2.hands[a].remove(ca[0])
                    g2.hands[b].remove(cb[0])
                    g2.hands[a].append(cb[0])
                    g2.hands[b].append(ca[0])
                    swapped = True
                    break
            if not swapped:
                continue

            # 公开状态必须一致，否则这次比较无效
            assert _public_key(g1) == _public_key(g2), "两个局面在比较前就不同步了"
            assert (len(g1.hands[seat]) == len(g2.hands[seat])), "我的手牌张数变了"
            assert sorted(c.label for c in g1.hands[seat]) == \
                sorted(c.label for c in g2.hands[seat]), "我的手牌内容变了"

            # rule 用的是全局 random，比较前重设同一个种子，保证随机性一致
            random.seed(20261125)
            mv1 = ai1.play(g1, seat)
            random.seed(20261125)
            mv2 = ai2.play(g2, seat)
            total += 1
            k1 = sorted(c.label for c in mv1)
            k2 = sorted(c.label for c in mv2)
            if k1 != k2:
                bad += 1
                print("  !! %s 第%d局第%d点 决策随对手手牌变化：%s -> %s"
                      % (kind, d, k, k1, k2))
    print("  %-10s 检查 %d 个决策，可疑 %d 个" % (kind, total, bad))
    return bad


def audit_bottom(kind: str, deals: int = 3, points: int = 8) -> int:
    """底牌泄漏审计：**我不是最后埋底者时**，把底牌和某个对手的牌互换。

    互换的双方（底牌 + 对手手牌）都是我看不到的隐藏信息，所以合法 AI 的决策必须不变。
    这是我给"给 V 加底牌特征"专门加的保险 —— 门控写错的话这里会立刻炸。
    """
    bad = 0
    total = 0
    for d in range(deals):
        for k in range(points):
            got = drive_to_decision(kind, 700000 + d * 31, 4 + k * 3)
            if got is None:
                continue
            g1, g2, ai1, ai2, seat = got
            # 只在"我不该知道底牌"的时候检查
            if getattr(g1, "last_burier", None) == seat:
                continue
            if not g1.bottom:
                continue
            other = [s for s in range(4) if s != seat][0]
            if not g2.hands[other]:
                continue
            # 底牌第 0 张 <-> 对手第 0 张（两边都是隐藏信息，张数不变）
            cb = g2.bottom[0]
            co = g2.hands[other][0]
            g2.bottom[0] = co
            g2.hands[other].remove(co)
            g2.hands[other].append(cb)
            if g2.bottom[0] is cb:
                continue
            assert _public_key(g1) == _public_key(g2), "比较前局面就不同步了"
            assert (len(g1.hands[seat]) == len(g2.hands[seat])), "我的手牌张数变了"
            random.seed(20261125)
            mv1 = ai1.play(g1, seat)
            random.seed(20261125)
            mv2 = ai2.play(g2, seat)
            total += 1
            if sorted(c.label for c in mv1) != sorted(c.label for c in mv2):
                bad += 1
                print("  !! %s 第%d局第%d点 **底牌泄漏**：%s -> %s"
                      % (kind, d, k,
                         sorted(c.label for c in mv1),
                         sorted(c.label for c in mv2)))
    print("  %-10s 底牌审计 %d 个决策，可疑 %d 个" % (kind, total, bad))
    return bad


def main():
    kinds = sys.argv[1:] or list(LEVELS)
    print("=" * 62)
    print("作弊审计：互换对手两家手牌，决策必须不变")
    print("=" * 62)
    total_bad = 0
    for kind in kinds:
        total_bad += audit(kind)
        total_bad += audit_bottom(kind)
    print("-" * 62)
    if total_bad == 0:
        print("全部通过：四档 AI 的决策都不依赖隐藏信息")
        return 0
    print("发现 %d 个可疑决策" % total_bad)
    return 1


if __name__ == "__main__":
    sys.exit(main())
