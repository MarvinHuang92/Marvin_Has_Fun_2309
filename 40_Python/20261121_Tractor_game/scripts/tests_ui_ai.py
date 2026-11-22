# -*- coding: utf-8 -*-
"""界面 AI 链路测试：确认「电脑强度」开关接得上、能跑完整一局。

跑法::

    python scripts/tests_ui_ai.py
"""
import sys
import tkinter as tk
from pathlib import Path

PROJECT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT / "scripts"))

from tractor.ai_select import LEVELS, LEVEL_NAMES, AiEngine  # noqa: E402
from tractor.ui import TractorApp  # noqa: E402


def check_engines():
    """三档都能建起来，接口齐全。"""
    for kind in LEVELS:
        engine = AiEngine(kind)
        assert engine.kind == kind
        assert callable(engine.bid) and callable(engine.bury) and callable(engine.play)
        print("  [1] 档位 %-10s 构建正常" % kind)


def play_one_deal(app, g, max_plays: int = 10 ** 9) -> int:
    """用界面自己的 ai_step 跑完一局，人类那一家由引擎代打。

    `max_plays` 给定时，出够这么多手就停（用来只验证接线）。
    """
    root = app.root
    steps = 0
    plays = 0
    while steps < 4000:
        steps += 1
        root.update()
        if plays >= max_plays:
            break
        if g.phase in ("settle", "match_over"):
            break

        if g.phase in ("bid_initial", "bid_extra") and g.current_bidder == 0:
            ok, _ = g.submit_bid(0, app.ai_engine.bid(g, 0))
            if not ok:
                g.submit_bid(0, None)
            app.refresh()
            continue

        if g.phase in ("bury_initial", "bury_extra") and g.pending_bury_by == 0:
            ok, msg = g.submit_bury(0, app.ai_engine.bury(g, 0))
            if not ok:
                raise RuntimeError("人类埋底失败：%s" % msg)
            app.refresh()
            continue

        if g.phase == "play" and g.current_player == 0:
            lead = g.trick.lead if (g.trick and g.trick.lead) else None
            cards = app.ai_engine.play(g, 0)
            if lead is not None:
                ok, msg = g.play_follow(0, cards)
            else:
                ok, msg = g.play_lead(0, cards)
            if not ok:
                raise RuntimeError("人类代打失败：%s" % msg)
            app.ai_engine.observe(g, 0, cards, lead)
            plays += 1
            app.refresh()
            continue

        app.ai_step()
        plays += 1
    return steps


def main():
    print("=" * 60)
    print("界面 AI 链路测试")
    print("=" * 60)
    check_engines()

    root = tk.Tk()
    app = TractorApp(root, PROJECT)
    g = app.game
    steps = play_one_deal(app, g)
    print("  [2] 默认档位（%s）跑完整局：%d 步，阶段 %s，闲家 %d 分"
          % (app.ai_engine.kind, steps, g.phase, g.defender_points))
    assert g.phase in ("settle", "match_over"), "没有跑完一局"

    # 切档位：只验证重建成功、界面回调不炸（不在这里跑 search，太慢）
    app.level_var.set("简单（原始规则）")
    app.on_level_change()
    assert app.ai_engine.kind == "rule"
    print("  [3] 切换档位到 rule 正常")

    app.level_var.set("会记牌（推荐）")
    app.on_level_change()
    assert app.ai_engine.kind == "heuristic"
    print("  [4] 切回 heuristic 正常")

    # 布局：下拉框必须在窗口内，不能超出右边界
    root.update_idletasks()
    assert app.level_box.winfo_manager() == "grid", "强度下拉框没有被布局"
    right = app.level_box.winfo_rootx() + app.level_box.winfo_width()
    win_right = root.winfo_rootx() + root.winfo_width()
    assert right <= win_right, "强度下拉框超出窗口右边界（%d > %d）" % (right, win_right)
    print("  [5] 强度下拉框布局正常（右边界 %d <= 窗口 %d）" % (right, win_right))

    # 下拉框里只剩下三档（会搜索已去掉）
    vals = list(app.level_box["values"])
    assert len(vals) == 3, "下拉框应该只有三档，实际 %r" % (vals,)
    assert "会搜索（最强 · 慢）" not in vals, "会搜索档没去掉"
    assert vals == [LEVEL_NAMES[k] for k in LEVELS]
    print("  [5b] 强度下拉框只有三档：%s ✓" % " / ".join(vals))

    # 笔记框：三家都有、能写、清空有效
    for seat in (1, 2, 3):
        note = app.ai_panels[seat].get("note")
        assert note is not None, "座位 %d 没有笔记框" % seat
        note.insert("1.0", "测试笔记%d" % seat)
    assert app.ai_panels[2]["note"].get("1.0", "end-1c") == "测试笔记2"
    app._clear_notes()
    for seat in (1, 2, 3):
        assert app.ai_panels[seat]["note"].get("1.0", "end-1c") == "", "笔记没清空"
    print("  [6] 笔记框：三家都有、可写、新一局清空 ✓")

    # 我方笔记框（全局信息）
    hn = app.human_note
    hn.insert("1.0", "梅花A还没出")
    assert hn.get("1.0", "end-1c") == "梅花A还没出"
    app._clear_notes()
    assert hn.get("1.0", "end-1c") == "", "我方笔记没清空"
    print("  [6b] 我方笔记框：可写、新一局清空 ✓")

    # 角色文案：庄家的对家是「庄家队友」，不是「闲家」
    g0 = app.game
    if g0.zhuang is not None:
        partner = (g0.zhuang + 2) % 4
        assert app._role_text(g0.zhuang) == "庄家"
        assert app._role_text(partner) == "庄家队友"
        other = [s for s in range(4) if s not in (g0.zhuang, partner)][0]
        assert app._role_text(other) == "闲家"
        print("  [6c] 角色文案：庄家/庄家队友/闲家 ✓")

    # 方位：0 南 1 东 2 北 3 西
    assert [app._seat_dir(i) for i in range(4)] == ["南", "东", "北", "西"]
    print("  [6d] 方位标注：南/东/北/西 ✓")

    # 「会搜索」这一档必须真的加载到价值网络，并且能正常出牌
    # 「会推理」= 优势网络
    app.level_var.set("会推理（强 · 快）")
    app.on_level_change()
    assert app.ai_engine.kind == "adv"
    from tractor.ai_advantage import AdvantageAI

    assert isinstance(app.ai_engine._brain, AdvantageAI), "会推理档没换成优势网络"
    app.on_next()
    steps = play_one_deal(app, app.game, max_plays=8)
    print("  [7] 会推理档（优势网络，%d 维输入）出 8 手正常（%d 步）✓"
          % (len(app.ai_engine._brain.net.w1[0]), steps))

    root.destroy()
    print("-" * 60)
    print("全部通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
