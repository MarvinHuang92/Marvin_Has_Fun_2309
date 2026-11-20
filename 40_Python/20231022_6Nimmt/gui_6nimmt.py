# -*- coding: utf-8 -*-
"""6 Nimmt!（牛头牌）图形界面：1 个人类 + 1~9 个电脑对手

只依赖标准库 tkinter，不需要装任何东西。

规则层和电脑玩家**完全复用 game_6nimmt.py**：
    Game / Player / CardDeck / Game.arrangeCard() / Player.showPenaltyCards()
所以这里打出来的牌局，和 run_game() 跑出来的完全一致。

人类玩家的两处交互用阻塞式等待实现（tkinter 的嵌套事件循环）：
    出牌   -> canvas 点击，wait_variable
    吃行   -> 弹窗选行，wait_window

额外功能：
    提示   -> 下拉框选「关闭 / adv_ai / 搜索型」，在状态栏和手牌上标出推荐
    存档   -> 每局结束自动写 game_log/replays/*.json（一轮一个快照）
    回放   -> 「回放…」按钮载入存档，逐回合前后翻

对手类型：随机 / 手写启发式 / 搜索型 / 混合型（hybrid）。混合型需要
`model_searchc_25k400_ts.pth`，会自动切到 teacher_scores 特征。
两类 rollout 次数可用环境变量调：NIMMT_SEARCH_M（默认 8）、NIMMT_HYBRID_M（默认 24）。
实测（每局耗时 / 对随机胜率）：search M8 ≈ 28ms/89.3%，hybrid M24 ≈ 39ms/94.0%，
search M24 ≈ 81ms/93.3%。（一局 10 回合，所以单个决策只有 3~8ms。）

尺寸会按真实 DPI 和屏幕可用空间等比缩放（高分屏 200% 缩放时不这么做会超出屏幕）。

用法：
    python gui_6nimmt.py            # 正常玩
    python gui_6nimmt.py --selftest # 自动跑一局（第一张手牌代打），验证流程
"""

import contextlib
import io
import json
import os
import random
import sys
import time
import tkinter as tk
from tkinter import filedialog, ttk

import game_6nimmt as engine

# ---------------- 外观 ----------------
BG = "#262626"
PANEL = "#1e1e1e"
FG = "#eaeaea"
DIM = "#8a8a8a"
GOLD = "#ffd54f"
HINT = "#4fc3f7"
BASE_W, BASE_H, BASE_GAP = 66, 88, 8

CARD_COLORS = {1: "#ededed", 2: "#ffe9a8", 3: "#ffc98f", 5: "#ff9b9b", 7: "#b23a48"}

OPP_TYPES = [
    ("随机", "simple_ai"),
    ("手写启发式 advanced_ai", "advanced_ai"),
    ("搜索型 search", "search"),
    ("混合型 hybrid（更强）", "hybrid"),
]
TYPE_NAME = {v: k for k, v in OPP_TYPES}
MODEL_TYPES = {"hybrid", "scorepolicy", "network", "policy"}

# 模型路径（hybrid 用；load_model 会自动到 models/ 下找）
MODEL_PATH = "model_searchc_25k400_ts.pth"
# 各类型的 rollout 次数：search 沿用界面的 8 次（够用且快），hybrid 用 24 次
#   —— 实测 hybrid K3M24 与 search M24 打平（48.6%），但每个决策便宜一半
SEARCH_ROLLOUTS = int(os.environ.get("NIMMT_SEARCH_M", "8"))
HYBRID_ROLLOUTS = int(os.environ.get("NIMMT_HYBRID_M", "24"))

HINT_LABELS = ["关闭提示", "adv_ai", "搜索型"]
HINT_MODES = ["off", "adv", "search"]

REPLAY_DIR = os.path.join("game_log", "replays")


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


# ---------------- 画牌 ----------------
def draw_card(cv, x, y, card, w, h, f_num, f_mark, selected=False, hint=False):
    bh = card.bullheads
    fill = CARD_COLORS.get(bh, "#ededed")
    tcol = "#ffffff" if bh >= 7 else "#1a1a1a"
    if selected:
        outline, width = GOLD, 3
    elif hint:
        outline, width = HINT, 3
    else:
        outline, width = "#1a1a1a", 1
    cv.create_rectangle(x, y, x + w, y + h, fill=fill, outline=outline, width=width)
    cv.create_text(x + w / 2, y + h * 0.31, text=str(card.value), fill=tcol, font=f_num)
    marks = "●" * min(bh, 5) + ("+%d" % (bh - 5) if bh > 5 else "")
    cv.create_text(x + w / 2, y + h * 0.71, text=marks, fill=tcol, font=f_mark)
    if hint and not selected:
        cv.create_polygon(x + w / 2 - 6, y - 7, x + w / 2 + 6, y - 7, x + w / 2, y - 1,
                          fill=HINT, outline="")


def draw_slot(cv, x, y, w, h):
    cv.create_rectangle(x, y, x + w, y + h, outline="#4a4a4a", dash=(3, 4))


def paint_table(cv, rows, cw, ch, gap, f_num, f_mark):
    cv.delete("all")
    for r in range(4):
        row = rows[r] if r < len(rows) else []
        y = gap + r * (ch + gap)
        for c in range(5):
            x = gap + c * (cw + gap)
            if c < len(row) and row[c] is not None:
                draw_card(cv, x, y, row[c], cw, ch, f_num, f_mark)
            else:
                draw_slot(cv, x, y, cw, ch)


def paint_hand(cv, hand, cw, ch, gap, f_num, f_mark, selected=None, hint=None):
    cv.delete("all")
    for i, card in enumerate(hand):
        draw_card(cv, gap + i * (cw + gap), gap, card, cw, ch, f_num, f_mark,
                  selected=(i == selected), hint=(i == hint))
    for i in range(len(hand), 10):
        draw_slot(cv, gap + i * (cw + gap), gap, cw, ch)


# ---------------- 回放窗口 ----------------
class ReplayWindow(tk.Toplevel):
    def __init__(self, master, app, data):
        tk.Toplevel.__init__(self, master)
        self.app = app
        self.data = data
        self.rounds = data.get("rounds", [])
        self.idx = 0
        self.title("回放 —— %s" % data.get("created", ""))
        self.configure(bg=BG)
        self.transient(master)

        top = tk.Frame(self, bg=BG)
        top.pack(fill="x", padx=10, pady=(10, 0))
        self.table_cv = tk.Canvas(top, width=app.table_w, height=app.table_h,
                                  bg=PANEL, highlightthickness=0)
        self.table_cv.pack(side="left")
        side = tk.Frame(top, bg=BG)
        side.pack(side="left", padx=(14, 0), anchor="n", fill="y")
        self.info = tk.Label(side, text="", bg=BG, fg=GOLD, font=app.font_b,
                             justify="left", anchor="nw", wraplength=int(260 * app.k))
        self.info.pack(anchor="w")
        self.score_lbl = tk.Label(side, text="", bg=BG, fg=FG, font=app.log_font,
                                  justify="left", anchor="nw")
        self.score_lbl.pack(anchor="w", pady=(8, 0))

        tk.Label(self, text="你（P1）的手牌", bg=BG, fg=DIM,
                 font=app.font).pack(anchor="w", padx=10, pady=(8, 2))
        self.hand_cv = tk.Canvas(self, width=app.hand_w, height=app.ch + app.gap,
                                 bg=PANEL, highlightthickness=0)
        self.hand_cv.pack(fill="x", padx=10)

        bar = tk.Frame(self, bg=BG)
        bar.pack(fill="x", padx=10, pady=10)
        tk.Button(bar, text="<< 上一回合", font=app.font,
                  command=self.prev).pack(side="left")
        tk.Button(bar, text="下一回合 >>", font=app.font,
                  command=self.next).pack(side="left", padx=8)
        tk.Button(bar, text="关闭", font=app.font,
                  command=self.destroy).pack(side="left")
        self.show(0)

    # 0 = 开局，k = 第 k 回合结束后
    def show(self, k):
        k = max(0, min(k, len(self.rounds)))
        self.idx = k
        if k == 0:
            snap = self.data["initial"]
            title = "开局"
            played = ""
        else:
            snap = self.rounds[k - 1]
            title = "第 %d 回合结束" % snap["round"]
            played = "本轮出牌：" + "，".join(
                "%s=%d" % (x["name"], x["card"]) for x in snap.get("played", []))
        rows = [[engine.Card(v) for v in row] for row in snap["table"]]
        paint_table(self.table_cv, rows, self.app.cw, self.app.ch, self.app.gap,
                    self.app.f_num, self.app.f_mark)
        hand = [engine.Card(v) for v in snap["hands"][0]]
        paint_hand(self.hand_cv, hand, self.app.cw, self.app.ch, self.app.gap,
                   self.app.f_num, self.app.f_mark)
        names = self.data.get("players", [])
        self.info.configure(text="%s\n%s\n（%d/%d）" % (title, played, k, len(self.rounds)))
        self.score_lbl.configure(text="\n".join(
            "%-14s %3d" % (names[i]["name"] if i < len(names) else "P%d" % (i + 1), s)
            for i, s in enumerate(snap["scores"])))

    def prev(self):
        self.show(self.idx - 1)

    def next(self):
        self.show(self.idx + 1)


# ---------------- 主窗口 ----------------
class NimmtGUI(object):
    def __init__(self, root, auto=False):
        self.root = root
        self.auto = auto
        self.game = None
        self.me = None
        self.players = []
        self.round = 0
        self.pending = None
        self.waiting = False
        self.busy = False
        self.hint_index = None
        self.hint_label = ""
        self.record = None
        self.last_saved = None
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
        self.win_w = max(self.hand_w, self.table_w + int(300 * self.k)) + 44
        self.win_h = 20 + self.table_h + int(30 * self.k) + (ch + gap) + int(30 * self.k) \
            + max(140, int(180 * self.k)) + int(46 * self.k)

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
        self.log = tk.Text(logf, height=6, bg=PANEL, fg=FG, font=self.log_font,
                           insertbackground=FG, relief="flat", wrap="word")
        sb = tk.Scrollbar(logf, command=self.log.yview)
        self.log.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        self.log.pack(side="left", fill="both", expand=True)

        btns = tk.Frame(outer, bg=BG)
        btns.pack(fill="x", pady=(6, 0))
        tk.Button(btns, text="新开一局", font=self.font,
                  command=self.on_new_game).pack(side="left")
        tk.Button(btns, text="保存本局", font=self.font,
                  command=self.save_record).pack(side="left", padx=(8, 0))
        tk.Button(btns, text="回放…", font=self.font,
                  command=self.open_replay).pack(side="left", padx=(8, 0))
        tk.Button(btns, text="退出", font=self.font,
                  command=self.root.destroy).pack(side="left", padx=(8, 0))

        tk.Label(btns, text="提示：", bg=BG, fg=FG, font=self.font).pack(
            side="left", padx=(20, 2))
        self.hint_combo = ttk.Combobox(btns, values=HINT_LABELS, state="readonly",
                                       width=10, font=self.font)
        self.hint_combo.current(0)
        self.hint_combo.pack(side="left")
        self.hint_combo.bind("<<ComboboxSelected>>", self._on_hint_change)

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
        # 默认在「随机 / advanced_ai / search」之间轮换（hybrid 要加载模型，让用户自己选）
        type_vars = [tk.StringVar(value=OPP_TYPES[i % 3][1]) for i in range(9)]

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
        n = cfg["n"]
        self.players = [engine.Player("P%d" % (i + 1)) for i in range(n)]
        self.me = self.players[0]
        self.me.intellegence = "human"

        # 有 hybrid 才需要模型和 teacher_scores 特征
        need_model = any(t in MODEL_TYPES for t in cfg["types"])
        model = None
        load_err = None
        if need_model:
            try:
                with quiet():
                    model = engine.load_model(MODEL_PATH)
                engine.extra_feature_mode = "teacher_scores"
            except Exception as exc:
                load_err = "%s —— 混合型降级为 advanced_ai" % exc
        else:
            engine.extra_feature_mode = "none"
        engine.policy_sample = False

        for i, t in enumerate(cfg["types"]):
            p = self.players[i + 1]
            p.intellegence = t
            if t in MODEL_TYPES:
                if model is not None:
                    p.NN_model = model
                else:
                    p.intellegence = "advanced_ai"
            p.rollout_count = (HYBRID_ROLLOUTS if p.intellegence == "hybrid"
                               else SEARCH_ROLLOUTS)
            p.search_depth = 0          # L1 关闭（实测截断会掉强度）

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
        self.hint_index = None
        self.record = {
            "version": 1,
            "created": time.strftime("%Y-%m-%d %H:%M:%S"),
            "config": cfg,
            "players": [{"name": p.name, "type": p.intellegence} for p in self.players],
            "initial": self._snapshot(),
            "rounds": [],
        }
        self.log_clear()
        self.log_line("新局开始：%d 人（你 + %d 个电脑），种子 %s" % (n, n - 1, cfg["seed"]))
        self.log_line("算力：search=%d 次 rollout，hybrid=%d 次（K=%d）"
                      % (SEARCH_ROLLOUTS, HYBRID_ROLLOUTS, engine.HYBRID_TOP_K))
        if load_err:
            self.log_line("！模型加载失败：%s" % load_err)
        self.log_line("对手：" + "，".join("P%d=%s" % (i + 2, TYPE_NAME[t])
                                          for i, t in enumerate(cfg["types"])))
        for rnd in range(self.game.max_round):
            if not self.root.winfo_exists():
                return
            self.play_round(rnd)
        self.finish()

    def _snapshot(self):
        return {
            "table": [[c.value for c in row if c] for row in self.game.table],
            "hands": [[c.value for c in p.handCards] for p in self.players],
            "scores": [p.bullheads for p in self.players],
        }

    # ---------------- 一回合 ----------------
    def play_round(self, rnd):
        self.round = rnd + 1
        self.game.left_round = self.game.max_round - 1 - rnd
        self.game.stash = []
        self.compute_hint()
        self.refresh()
        if self.hint_index is not None:
            self.status("第 %d/10 回合 —— 点一张手牌　　提示（%s）：%d 号牌"
                        % (self.round, self.hint_label,
                           self.me.handCards[self.hint_index].value))
        else:
            self.status("第 %d/10 回合 —— 点一张手牌" % self.round)

        idx = self.ask_card()
        card = self.me.handCards.pop(idx)
        self.game.stash.append({"player": self.me, "card": card})
        self.hint_index = None

        self.status("对手出牌中…")
        with quiet():
            for p in self.players:
                if p is not self.me:
                    p.playCard(self.game, self.deck)

        played_rows = [{"seat": self.players.index(it["player"]),
                        "name": it["player"].name,
                        "card": it["card"].value} for it in self.game.stash]
        self.log_line("第 %2d 回合出牌：%s" % (
            self.round, "，".join("%s=%d" % (x["name"], x["card"]) for x in played_rows)))

        with quiet():
            self.game.arrangeCard()          # 人类要选行时会在这里弹窗
        self.game.stash = []
        with quiet():
            for p in self.players:
                p.showPenaltyCards()

        for p in self.players:
            self.log_line("        %s 累计牛头 %d" % (p.name, p.bullheads))
        snap = self._snapshot()
        snap["round"] = self.round
        snap["played"] = played_rows
        self.record["rounds"].append(snap)
        self.refresh()

    # ---------------- 提示 ----------------
    def _on_hint_change(self, _ev=None):
        if self.waiting:                     # 正等着我出牌，立刻重算
            self.compute_hint()
            self.refresh()
            if self.hint_index is not None:
                self.status("第 %d/10 回合 —— 点一张手牌　　提示（%s）：%d 号牌"
                            % (self.round, self.hint_label,
                               self.me.handCards[self.hint_index].value))
            else:
                self.status("第 %d/10 回合 —— 点一张手牌" % self.round)

    def compute_hint(self):
        self.hint_index = None
        self.hint_label = ""
        mode = HINT_MODES[self.hint_combo.current()]
        if mode == "off" or not self.me or not self.me.handCards:
            return
        state = random.getstate()            # 提示要跑 rollout，别扰动牌局本身的随机数
        best = None
        try:
            with quiet():
                if mode == "adv":
                    ds = self.me.advAiCalcPlayCardReward(self.game, self.deck)
                    best = min(range(len(ds)), key=lambda i: ds[i]["reward"])
                    self.hint_label = "adv_ai"
                else:
                    # searchCostsFor 会往 self.search_costs 里写，人类玩家没初始化过
                    self.me.search_costs = {}
                    costs = self.me.searchCostsFor(self.game,
                                                   list(range(len(self.me.handCards))))
                    best = costs.index(min(costs))
                    self.hint_label = "搜索型"
        except Exception as exc:             # 提示失败不该影响游戏
            self.log_line("（提示计算失败：%s）" % exc)
        finally:
            random.setstate(state)
        if best is not None and 0 <= best < len(self.me.handCards):
            self.hint_index = best
            self.log_line("        提示（%s）：建议出 %d"
                          % (self.hint_label, self.me.handCards[best].value))

    # ---------------- 人类交互 ----------------
    def ask_card(self):
        if self.auto:
            return 0
        self.pending = None
        self.card_var.set(0)
        self.waiting = True
        self.root.wait_variable(self.card_var)
        self.waiting = False
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
        if not self.game:
            return
        paint_table(self.table_cv, self.game.table, self.cw, self.ch, self.gap,
                    self.f_num, self.f_mark)
        paint_hand(self.hand_cv, self.me.handCards, self.cw, self.ch, self.gap,
                   self.f_num, self.f_mark, selected=self.pending, hint=self.hint_index)

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

    # ---------------- 存档 / 回放 ----------------
    def save_record(self):
        if not self.record or not self.record["rounds"]:
            self.log_line("（还没打完一回合，没有可保存的内容）")
            return None
        try:
            os.makedirs(REPLAY_DIR, exist_ok=True)
            fn = os.path.join(REPLAY_DIR, "nimmt_%s_seed%s.json" % (
                time.strftime("%Y%m%d_%H%M%S"), self.record["config"]["seed"]))
            with open(fn, "w", encoding="utf-8") as f:
                json.dump(self.record, f, ensure_ascii=False, indent=1)
            self.last_saved = fn
            self.log_line("对局已保存：%s" % fn)
            return fn
        except Exception as exc:
            self.log_line("（保存失败：%s）" % exc)
            return None

    def open_replay(self):
        os.makedirs(REPLAY_DIR, exist_ok=True)
        fn = filedialog.askopenfilename(
            parent=self.root, title="选择对局存档", initialdir=REPLAY_DIR,
            filetypes=[("对局存档", "*.json"), ("所有文件", "*.*")])
        if not fn:
            return
        try:
            with open(fn, "r", encoding="utf-8") as f:
                data = json.load(f)
            ReplayWindow(self.root, self, data)
        except Exception as exc:
            self.log_line("（读取存档失败：%s）" % exc)

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
        self.record["final"] = {
            "scores": [p.bullheads for p in self.players],
            "ranking": [p.name for p in ranked],
        }
        self.save_record()
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
