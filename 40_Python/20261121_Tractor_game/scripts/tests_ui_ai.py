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

from tractor.ai_select import LEVELS, AiEngine  # noqa: E402
from tractor.ui import TractorApp  # noqa: E402


def check_engines():
    """三档都能建起来，接口齐全。"""
    for kind in LEVELS:
        engine = AiEngine(kind)
        assert engine.kind == kind
        assert callable(engine.bid) and callable(engine.bury) and callable(engine.play)
        print("  [1] 档位 %-10s 构建正常" % kind)


def play_one_deal(app, g) -> int:
    """用界面自己的 ai_step 跑完一局，人类那一家由引擎代打。"""
    root = app.root
    steps = 0
    while steps < 4000:
        steps += 1
        root.update()
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
            app.refresh()
            continue

        app.ai_step()
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

    root.destroy()
    print("-" * 60)
    print("全部通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
