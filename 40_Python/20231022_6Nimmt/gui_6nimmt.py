# -*- coding: utf-8 -*-
"""6 Nimmt!（牛头牌）图形界面：1 个人类 + 1~9 个电脑对手

只依赖标准库 tkinter，不需要装任何东西。

规则层和电脑玩家**完全复用 game_6nimmt.py**：
    Game / Player / CardDeck / Game.arrangeCard() / Player.showPenaltyCards()
所以这里打出来的牌局，和 run_game() 跑出来的完全一致。

人类玩家的两处交互用阻塞式等待实现（tkinter 的嵌套事件循环）：
    出牌   -> canvas 点击，wait_variable
    吃行   -> 弹窗选行，wait_window

尺寸会按屏幕可用空间等比缩放（高分屏 150% 缩放时窗口会放不下）。

用法：
    python gui_6nimmt.py            # 正常玩
    python gui_6nimmt.py --selftest # 自动跑一局（用随机手牌代打），验证流程
"""

import contextlib
import io
import os
import random
import sys
import tkinter as tk
from tkinter import ttk

import game_6nimmt as engine

# ---------------- 外观 ----------------
BG = "#262626"
PANEL = "#1e1e1e"
FG = "#eaeaea"
DIM = "#8a8a8a"
GOLD = "#ffd54f"
BASE_W, BASE_H, BASE_GAP = 66, 88, 8

# 牛头数 -> 卡面底色
CARD_COLORS = {1: "#ededed", 2: "#ffe9a8", 3: "#ffc98f", 5: "#ff9b9b", 7: "#b23a48"}

OPP_TYPES = [
    ("随机", "simple_ai"),
    ("手写启发式 advanced_ai", "advanced_ai"),
    ("搜索型 search", "search"),
]
TYPE_NAME = {v: k for k, v in OPP_TYPES}


@contextlib.contextmanager
def quiet():
    """把引擎里大量的 print 吞掉"""
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        yield buf


def enable_dpi_awareness():
    """让 Tk 拿到真实像素。

    不这么做的话，Windows 会把整个窗口按缩放比例放大，而 Tk 仍以为自己在
    逻辑分辨率下画图 —— 结果就是窗口超出屏幕、下半截被裁掉。
    """
    if sys.platform != "win32":
        return
    try:
        import ctypes
        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(2)      # 每显示器 DPI 感知
        except Exception:
            ctypes.windll.user32.SetProcessDPIAware()           # 老系统
    except Exception:
        pass


def draw_card(cv, x, y, card, w, h, f_num, f_mark, selected=False, dim=False):
    bh = card.bullheads
    fill = CARD_COLORS.get(bh, "#ededed")
    if dim:
        fill = "#8f8f8f"
    tcol = "#ffffff" if bh >= 7 else "#1a1a1a"
    cv.create_rectangle(x, y, x + w, y + h, fill=fill,
                        outline=GOLD if selected else "#1a1a1a",
                        width=3 if selected else 1)
    cv.create_text(x + w / 2, y + h * 0.31, text=str(card.value), fill=tcol, font=f_num)
    marks = "●" * min(bh, 5) + ("+%d" % (bh - 5) if bh > 5 else "")
    cv.create_text(x + w / 2, y + h * 0.71, text=marks, fill=tcol, font=f_mark)


def draw_slot(cv, x, y, w, h):
    cv.create_rectangle(x, y, x + w, y + h, outline="#4a4a4a", dash=(3, 4))


class NimmtGUI(object):
    def __init__(self, root, auto=False):
        self.root = root
        self.auto = auto
        self.game = None
        self.me = None
        self.players = []
        self.round = 0
        self.pending = None
        self.busy = False
        self.card_var = tk.IntVar(value=0)
        self._setup_scale()
        root.title("6 Nimmt! 牛头牌")
        root.configure(bg=BG)
        root.geometry("%dx%d" % (self.win_w, self.win_h))
        root.minsize(self.win_w, self.win_h)
        self._build_ui()
        if not auto:
            self.root.after(80, self.setup_dialog)

    # ---------------- 按屏幕缩放 ----------------
    def _setup_scale(self):
        sw = self.root.winfo_screenwidth()
        sh = self.root.winfo_screenheight()
        dpi = self.root.winfo_fpixels("1i")
        # 先按 DPI 放大（高分屏 150% / 200%），再夹到屏幕能放下
        k = min(dpi / 96.0, (sh - 140) / 760.0, (sw - 100) / 1060.0)
        env = os.environ.get("NIMMT_SCALE")
        if env:                      # 想强制大小就设 NIMMT_SCALE=1.5 之类
            try:
                k = float(env)
            except ValueError:
                pass
        self.k = max(0.55, k)
        cw = int(BASE_W * self.k)
        ch = int(BASE_H * self.k)
        gap = max(4, int(BASE_GAP * self.k))
        self.cw, self.ch, self.gap = cw, ch, gap
        fs = max(8, int(10 * self.k))
        self.font = ("Microsoft YaHei", fs)
        self.font_b = ("Microsoft YaHei", fs, "bold")
        self.f_num = ("Consolas", max(10, int(20 * self.k)), "bold")
        self.f_mark = ("Segoe UI", max(6, int(8 * self.k)))
        self.log_font = ("Microsoft YaHei", max(8, int(9 * self.k)))
        self.table_w = 5 * (cw + gap) + gap
        self.table_h = 4 * (ch + gap) + gap
        self.hand_w = 10 * (cw + gap) + gap
        self.win_w = max(self.hand_w, self.table_w + int(280 * self.k)) + 44
        self.win_h = 20 + self.table_h + int(30 * self.k) + (ch + gap) + int(30 * self.k) \
            + max(140, int(180 * self.k)) + int(40 * self.k)

    # ---------------- 界面骨架 ----------------
    def _build_ui(self):
        outer = tk.Frame(self.root, bg=BG)
        outer.pack(fill="both", expand=True, padx=12, pady=10)

        top = tk.Frame(outer, bg=BG)
        top.pack(fill="x")
        self.table_cv = tk.Canvas(top, width=self.table_w, height=self.table_h,
                                  bg=PANEL, highlightthickness=0)
        self.table_cv.pack(side="left")
        self.score_box = tk.Frame(top, bg=BG)
        self.score_box.pack(side="left", padx=(16, 0), fill="y", anchor="n")

        tk.Label(outer, text="我的手牌（点牌出牌）", bg=BG, fg=DIM,
                 font=self.font).pack(anchor="w", pady=(10, 2))
        self.hand_cv = tk.Canvas(outer, width=self.hand_w, height=self.ch + self.gap,
                                 bg=PANEL, highlightthickness=0)
        self.hand_cv.pack(fill="x")
        self.hand_cv.bind("<Button-1>", self._on_hand_click)

        self.status_var = tk.StringVar(value="准备开始")
        tk.Label(outer, textvariable=self.status_var, bg=BG, fg=GOLD,
                 font=self.font_b, anchor="w").pack(fill="x", pady=(8, 4))

        logf = tk.Frame(outer, bg=BG)
        logf.pack(fill="both", expand=True)
        self.log = tk.Text(logf, height=6, bg=PANEL, fg=FG,
                           font=self.log_font, insertbackground=FG, relief="flat",
                           wrap="word")
        sb = tk.Scrollbar(logf, command=self.log.yview)
        self.log.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        self.log.pack(side="left", fill="both", expand=True)

        btns = tk.Frame(outer, bg=BG)
        btns.pack(fill="x", pady=(6, 0))
        tk.Button(btns, text="新开一局", font=self.font,
                  command=self.on_new_game).pack(side="left")
        tk.Button(btns, text="退出", font=self.font,
                  command=self.root.destroy).pack(side="left", padx=8)

    # ---------------- 日志 ----------------
    def log_line(self, text):
        self.log.configure(state="normal")
        self.log.insert("end", text + "\n")
        self.log.see("end")
        self.log.configure(state="disabled")

    def log_clear(self):
        self.log.configure(state="normal")
        self.log.delete("1.0", "end")
        self.log.configure(state="disabled")

    def status(self, text):
        self.status_var.set(text)
        self.root.update_idletasks()

    # ---------------- 开局设置 ----------------
    def on_new_game(self):
        if self.busy:                 # 对局进行中不响应，避免嵌套跑第二局
            return
        self.setup_dialog()

    def setup_dialog(self):
        if self.auto:
            self.new_game({"n": 4, "types": ["simple_ai", "advanced_ai", "search"], "seed": 7})
            return
        dlg = tk.Toplevel(self.root)
        dlg.title("新开一局")
        dlg.configure(bg=BG)
        dlg.transient(self.root)
        dlg.resizable(False, False)

        n_var = tk.IntVar(value=4)
        seed_var = tk.StringVar(value="")
        type_vars = [tk.StringVar(value=OPP_TYPES[i % len(OPP_TYPES)][1]) for i in range(9)]

        tk.Label(dlg, text="你是 P1，其余都是电脑", bg=BG, fg=FG,
                 font=self.font_b).grid(row=0, column=0, columnspan=3, sticky="w",
                                        padx=14, pady=(12, 8))
        tk.Label(dlg, text="玩家总数（含你）", bg=BG, fg=FG, font=self.font).grid(
            row=1, column=0, sticky="w", padx=14, pady=4)
        ttk.Spinbox(dlg, from_=2, to=10, textvariable=n_var, width=6).grid(
            row=1, column=1, sticky="w", pady=4)

        rows_frame = tk.Frame(dlg, bg=BG)
        rows_frame.grid(row=2, column=0, columnspan=3, sticky="w", padx=14, pady=(8, 4))
        combos = []

        def refresh_rows(*_):
            n = n_var.get()
            for i, cb in enumerate(combos):
                if i + 2 <= n:
                    cb.master.grid()
                else:
                    cb.master.grid_remove()

        for i in range(9):
            f = tk.Frame(rows_frame, bg=BG)
            f.grid(row=i, column=0, sticky="w", pady=1)
            tk.Label(f, text="P%d" % (i + 2), bg=BG, fg=FG, font=self.font,
                     width=4, anchor="w").pack(side="left")
            cb = ttk.Combobox(f, values=[t[0] for t in OPP_TYPES], state="readonly",
                              width=24, font=self.font)
            cb.current(next(j for j, t in enumerate(OPP_TYPES) if t[1] == type_vars[i].get()))
            cb.pack(side="left")
            cb.bind("<<ComboboxSelected>>",
                    lambda e, i=i, cb=cb: type_vars[i].set(OPP_TYPES[cb.current()][1]))
            combos.append(cb)

        n_var.trace_add("write", refresh_rows)
        refresh_rows()

        tk.Label(dlg, text="随机种子（留空则每局不同）", bg=BG, fg=FG, font=self.font).grid(
            row=3, column=0, sticky="w", padx=14, pady=(8, 4))
        tk.Entry(dlg, textvariable=seed_var, width=18, font=self.font).grid(
            row=3, column=1, sticky="w")

        result = {"ok": False}

        def on_start():
            result["ok"] = True
            dlg.destroy()

        bf = tk.Frame(dlg, bg=BG)
        bf.grid(row=4, column=0, columnspan=3, pady=14)
        tk.Button(bf, text="开始游戏", font=self.font_b, width=12,
                  command=on_start).pack(side="left", padx=6)
        tk.Button(bf, text="取消", font=self.font, width=8,
                  command=dlg.destroy).pack(side="left")

        dlg.grab_set()
        self.root.wait_window(dlg)
        if not result["ok"]:
            return
        n = n_var.get()
        types = [type_vars[i].get() for i in range(n - 1)]
        seed = seed_var.get().strip()
        self.new_game({"n": n, "types": types,
                       "seed": int(seed) if seed else random.randrange(1, 10 ** 9)})

    def new_game(self, cfg):
        if self.busy:
            return
        self.busy = True
        try:
            self.start_game(cfg)
        finally:
            self.busy = False

    # ---------------- 建局 ----------------
    def start_game(self, cfg):
        engine.SEARCH_ROLLOUTS = 8          # 交互时别用 12 次 rollout，太慢
        n = cfg["n"]
        self.players = [engine.Player("P%d" % (i + 1)) for i in range(n)]
        self.me = self.players[0]
        self.me.intellegence = "human"
        for i, t in enumerate(cfg["types"]):
            self.players[i + 1].intellegence = t

        self.game = engine.Game(n, 10)
        self.game.playerList = self.players

        random.seed(cfg["seed"])
        deck = engine.CardDeck(players=n)
        random.shuffle(deck)
        self.deck = deck
        for p in self.players:
            for _ in range(self.game.max_round):
                p.handCards.append(deck.pop(0))
        for i in range(4):
            self.game.table[i][0] = deck.pop(0)
        self.game.played_cards = [self.game.table[i][0].value for i in range(4)]
        self.game.played_bullheads = sum(self.game.table[i][0].bullheads for i in range(4))
        self.game.deck_total_bullheads = sum(c.bullheads for c in deck.shadow)
        self.me.handCards.sort()
        self.me.chooseRowWhenSmallest = self._human_row_choice   # 用弹窗替代 input()

        self.round = 0
        self.pending = None
        self.log_clear()
        self.log_line("新局开始：%d 人（你 + %d 个电脑），种子 %s" % (n, n - 1, cfg["seed"]))
        self.log_line("对手：" + "，".join("P%d=%s" % (i + 2, TYPE_NAME[t])
                                          for i, t in enumerate(cfg["types"])))
        for rnd in range(self.game.max_round):
            if not self.root.winfo_exists():
                return
            self.play_round(rnd)
        self.finish()

    # ---------------- 一回合 ----------------
    def play_round(self, rnd):
        self.round = rnd + 1
        self.game.left_round = self.game.max_round - 1 - rnd
        self.game.stash = []
        self.status("第 %d/10 回合 —— 点一张手牌" % self.round)
        self.refresh()

        idx = self.ask_card()
        card = self.me.handCards.pop(idx)
        self.game.stash.append({"player": self.me, "card": card})

        self.status("对手出牌中…")
        with quiet():
            for p in self.players:
                if p is not self.me:
                    p.playCard(self.game, self.deck)

        played = "，".join("%s=%d" % (it["player"].name, it["card"].value)
                           for it in self.game.stash)
        self.log_line("第 %2d 回合出牌：%s" % (self.round, played))

        with quiet():
            self.game.arrangeCard()          # 人类要选行时会在这里弹窗
        self.game.stash = []
        with quiet():
            for p in self.players:
                p.showPenaltyCards()

        for p in self.players:
            self.log_line("        %s 累计牛头 %d" % (p.name, p.bullheads))
        self.refresh()

    # ---------------- 人类交互 ----------------
    def ask_card(self):
        if self.auto:
            return 0
        self.pending = None
        self.card_var.set(0)
        self.root.wait_variable(self.card_var)
        idx = self.pending
        self.pending = None
        return idx

    def _on_hand_click(self, ev):
        if self.pending is not None or not self.me or not self.me.handCards:
            return
        idx = int((ev.x - self.gap) // (self.cw + self.gap))
        if 0 <= idx < len(self.me.handCards):
            self.pending = idx
            self.refresh()                   # 先把选中的牌描个金边
            self.card_var.set(1)

    def _human_row_choice(self, game, card):
        """替换 Player.chooseRowWhenSmallest，被 Game.arrangeCard 调用"""
        self.me.played_smallest = True
        if self.auto:
            return 1
        return self.ask_row(card)

    def ask_row(self, card):
        dlg = tk.Toplevel(self.root)
        dlg.title("必须吃一行")
        dlg.configure(bg=BG)
        dlg.transient(self.root)
        dlg.grab_set()
        tk.Label(dlg, text="你打出的 %d 比所有行尾都小 —— 选一行吃下：" % card.value,
                 bg=BG, fg=FG, font=self.font_b).pack(padx=16, pady=(14, 8))
        result = {"row": None}
        for i, row in enumerate(self.game.table):
            cards = [c for c in row if c]
            total = sum(c.bullheads for c in cards)
            txt = "第 %d 行：%s    （共 %d 个牛头）" % (
                i + 1, "  ".join("%d" % c.value for c in cards), total)
            tk.Button(dlg, text=txt, font=self.font, width=44, anchor="w",
                      command=lambda i=i: (result.__setitem__("row", i + 1), dlg.destroy())
                      ).pack(fill="x", padx=16, pady=2)
        self.root.wait_window(dlg)
        if result["row"] is None:            # 直接关窗口：默认吃牛头最少的一行
            result["row"] = min(range(4), key=lambda i: sum(
                c.bullheads for c in self.game.table[i] if c)) + 1
        return result["row"]

    # ---------------- 绘制 ----------------
    def refresh(self):
        cv = self.table_cv
        cv.delete("all")
        if not self.game:
            return
        for r, row in enumerate(self.game.table):
            y = self.gap + r * (self.ch + self.gap)
            for c in range(5):
                x = self.gap + c * (self.cw + self.gap)
                if row[c]:
                    draw_card(cv, x, y, row[c], self.cw, self.ch,
                              self.f_num, self.f_mark)
                else:
                    draw_slot(cv, x, y, self.cw, self.ch)

        hv = self.hand_cv
        hv.delete("all")
        if self.me:
            for i, card in enumerate(self.me.handCards):
                x = self.gap + i * (self.cw + self.gap)
                draw_card(hv, x, self.gap, card, self.cw, self.ch,
                          self.f_num, self.f_mark, selected=(i == self.pending))
            for i in range(len(self.me.handCards), 10):
                draw_slot(hv, self.gap + i * (self.cw + self.gap), self.gap,
                          self.cw, self.ch)

        for w in self.score_box.winfo_children():
            w.destroy()
        tk.Label(self.score_box, text="罚分（越少越好）", bg=BG, fg=DIM,
                 font=self.font).pack(anchor="w", pady=(0, 4))
        best = min((p.bullheads for p in self.players), default=0)
        for p in self.players:
            if p is self.me:
                label = "%s（你）" % p.name
            else:
                label = "%s %s" % (p.name, TYPE_NAME.get(p.intellegence, ""))
            fg = "#8bd450" if (p.bullheads == best and self.round > 1) else FG
            tk.Label(self.score_box, text="%-16s %3d" % (label, p.bullheads),
                     bg=BG, fg=fg, font=("Consolas", max(8, int(10 * self.k))),
                     anchor="w").pack(anchor="w")

    # ---------------- 收尾 ----------------
    def finish(self):
        ranked = sorted(self.players, key=lambda p: p.bullheads)
        self.log_line("")
        self.log_line("=" * 46)
        for i, p in enumerate(ranked):
            self.log_line("  第 %d 名  %-4s %3d 个牛头" % (i + 1, p.name, p.bullheads))
        winners = [p for p in ranked if p.bullheads == ranked[0].bullheads]
        if self.me in winners:
            self.status("你赢了！（%d 个牛头）" % self.me.bullheads)
        else:
            self.status("你排第 %d（%d 个牛头）" % (
                ranked.index(self.me) + 1, self.me.bullheads))
        self.refresh()
        if self.auto:
            print("selftest 完成：%s" % "，".join(
                "%s(%s)=%d" % (p.name, p.intellegence, p.bullheads) for p in self.players))


def main():
    enable_dpi_awareness()
    root = tk.Tk()
    auto = "--selftest" in sys.argv
    app = NimmtGUI(root, auto=auto)
    if auto:
        root.after(150, app.setup_dialog)      # auto 模式下直接开局
        root.after(300, root.destroy)
    root.mainloop()


if __name__ == "__main__":
    main()
