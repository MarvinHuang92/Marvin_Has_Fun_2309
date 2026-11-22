"""Tkinter GUI for the Tractor game.

Only the Python standard library is used.  Seat 0 is the human; seats 1-3
are the simple AI.  The engine owns all rules; this module only draws state
and schedules AI moves.
"""
from __future__ import annotations

import itertools
import logging
import re
import tkinter as tk
import tkinter.font as tkfont
from tkinter import messagebox, ttk
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Set, Tuple

from .ai import choose_bid, choose_bury, choose_play
from .ai_select import LEVEL_NAMES, LEVELS, AiEngine
from .cards import (
    SUIT_NAMES,
    SUIT_SYMBOLS,
    Card,
    card_points,
    rank_label,
    sort_hand,
)
from .engine import Bid, TractorGame
from .storage import load_window_geometry, save_deal, save_window_geometry

logger = logging.getLogger(__name__)

CARD_RED = "#c62828"
CARD_BLACK = "#111111"

# Card tokens that appear in logs / labels.  Suit names and suit symbols are
# both handled so "红桃10" and "♥10" are coloured.
CARD_TOKEN_RE = re.compile(
    r"大王|小王"
    r"|(?:黑桃|红桃|梅花|方块)(?:10|[2-9JQKA])?"
    r"|(?:[♠♥♣♦])(?:10|[2-9JQKA])?"
)
GEOMETRY_RE = re.compile(r"^(\d+)x(\d+)([+-]\d+)([+-]\d+)$")


def _token_is_red(tok: str) -> bool:
    if tok.startswith("大王"):
        return True
    if tok.startswith(("红桃", "方块", "♥", "♦")):
        return True
    return False


PHASE_TEXT = {
    "bid_initial": "初始亮主",
    "bid_extra": "抄底/换底",
    "bury_initial": "初始埋底",
    "bury_extra": "换底",
    "play": "出牌",
    "settle": "结算",
    "match_over": "全场结束",
}


class TractorApp:
    def __init__(self, root: tk.Tk, project_dir: Path) -> None:
        self.root = root
        self.project_dir = project_dir
        self.data_dir = project_dir / "data"
        self.cfg_dir = project_dir / "cfg"
        self.game = TractorGame()
        self.selected: Set[Card] = set()
        self.ai_job: Optional[str] = None
        self.ai_engine = AiEngine("heuristic")     # 电脑强度，界面可切
        self.saved_deal_no: Optional[int] = None
        self.ai_fail_count = 0
        self.logger = logger

        # Manual "what are they missing" trackers, one per AI seat.
        # Keys are (seat, "single"/"pair", "S"/"H"/"C"/"D"/"T").
        self.track_state: Dict[Tuple[int, str, str], bool] = {}
        self.track_buttons: Dict[Tuple[int, str, str], tk.Button] = {}
        self.track_deal_no = -1
        self.track_font = tkfont.Font(family="Microsoft YaHei", size=9)
        self.track_font_strike = tkfont.Font(family="Microsoft YaHei", size=9, overstrike=1)

        self.root.title("拖拉机（双升 · 80 分）")
        geo = load_window_geometry(self.cfg_dir)
        if not self._geometry_fits(geo):
            geo = self._default_geometry()
        self.root.geometry(geo)
        self.root.minsize(1100, 760)
        self.root.configure(bg="#eef3f8")

        self._build_ui()
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)
        self.game.start_match()
        self.refresh()
        self.schedule_ai()

    # ------------------------------------------------------------------ UI
    def _geometry_fits(self, geo: Optional[str]) -> bool:
        if not geo:
            return False
        m = GEOMETRY_RE.match(geo)
        if not m:
            return False
        w, h, x, y = (int(v) for v in m.groups())
        sw, sh = self.root.winfo_screenwidth(), self.root.winfo_screenheight()
        if w < 1000 or h < 700:
            return False
        if w > sw - 20 or h > sh - 80:
            return False
        if x < 0 or y < 0 or x + w > sw or y + h > sh:
            return False
        return True

    def _default_geometry(self) -> str:
        sw, sh = self.root.winfo_screenwidth(), self.root.winfo_screenheight()
        w = min(1280, max(1000, sw - 80))
        h = min(900, max(700, sh - 120))
        return f"{w}x{h}+40+30"

    def _build_ui(self) -> None:
        font = ("Microsoft YaHei", 10)
        small = ("Microsoft YaHei", 9)
        bold = ("Microsoft YaHei", 11, "bold")

        self.root.rowconfigure(0, weight=0)
        self.root.rowconfigure(1, weight=3)
        self.root.rowconfigure(2, weight=2)
        self.root.rowconfigure(3, weight=1)
        self.root.columnconfigure(0, weight=1)

        # top info
        top = tk.Frame(self.root, bg="#dce8f5", bd=1, relief="groove")
        top.grid(row=0, column=0, sticky="ew", padx=6, pady=4)
        self.info_text = self._make_text(
            top, bg="#dce8f5", fg="#17324d", font=bold, height=2, width=1,
        )
        self.info_text.pack(fill="x", padx=6, pady=3)

        # table
        table = tk.Frame(self.root, bg="#ffffff", bd=1, relief="groove")
        table.grid(row=1, column=0, sticky="nsew", padx=6, pady=4)
        for r in range(3):
            table.rowconfigure(r, weight=1)
        for c in range(3):
            table.columnconfigure(c, weight=1)

        self.ai_panels: Dict[int, Dict[str, tk.Widget]] = {}
        self._make_ai_panel(table, 2, 0, 1)
        self._make_ai_panel(table, 3, 1, 0)
        self._make_ai_panel(table, 1, 1, 2)

        trick_box = tk.LabelFrame(table, text="桌面", font=font, bg="#f8fbff", fg="#17324d")
        trick_box.grid(row=1, column=1, sticky="nsew", padx=6, pady=4)
        self.trick_text = self._make_text(
            trick_box, bg="#f8fbff", fg="#17324d", font=small, height=8, width=1,
        )
        self.trick_text.pack(fill="both", expand=True, padx=8, pady=6)

        human_box = tk.LabelFrame(table, text="你（南）", font=font, bg="#f8fbff", fg="#17324d")
        human_box.grid(row=2, column=1, sticky="nsew", padx=6, pady=4)
        self.human_label = tk.Label(
            human_box, text="", justify="left", anchor="w", font=small,
            bg="#f8fbff", fg="#17324d",
        )
        self.human_label.pack(fill="x", padx=8, pady=6)

        # actions + hand
        middle = tk.Frame(self.root, bg="#eef3f8")
        middle.grid(row=2, column=0, sticky="nsew", padx=6, pady=2)
        middle.columnconfigure(0, weight=1)
        middle.rowconfigure(0, weight=0)
        middle.rowconfigure(1, weight=1)

        action = tk.Frame(middle, bg="#eef3f8")
        action.grid(row=0, column=0, sticky="ew")
        self.status_label = tk.Label(
            action, text="", anchor="w", font=("Microsoft YaHei", 12, "bold"),
            bg="#eef3f8", fg="#0d47a1", wraplength=1200, justify="left",
        )
        self.status_label.grid(row=0, column=0, columnspan=6, sticky="w", pady=(0, 4))

        self.bid_frame = tk.Frame(action, bg="#eef3f8")
        self.bid_frame.grid(row=1, column=0, columnspan=6, sticky="w", pady=2)

        self.selected_label = tk.Label(
            action, text="已选 0 张", font=small, bg="#eef3f8", fg="#455a64",
        )
        self.selected_label.grid(row=2, column=0, sticky="w")

        self.action_button = tk.Button(
            action, text="出牌", font=font, width=12, command=self.on_action,
            bg="#1565c0", fg="white", activebackground="#0d47a1",
        )
        self.action_button.grid(row=2, column=1, padx=4)
        self.hint_button = tk.Button(
            action, text="提示", font=font, width=8, command=self.on_hint,
            bg="#e3f2fd", fg="#0d47a1",
        )
        self.hint_button.grid(row=2, column=2, padx=4)
        self.pass_button = tk.Button(
            action, text="过", font=font, width=6, command=self.on_pass,
            bg="#eceff1", fg="#263238",
        )
        self.pass_button.grid(row=2, column=3, padx=4)
        self.next_button = tk.Button(
            action, text="下一局", font=font, width=10, command=self.on_next,
            bg="#2e7d32", fg="white", activebackground="#1b5e20",
        )
        self.next_button.grid(row=2, column=4, padx=4)
        self.new_button = tk.Button(
            action, text="新的一场", font=font, width=10, command=self.on_new_match,
            bg="#eceff1", fg="#263238",
        )
        self.new_button.grid(row=2, column=5, padx=4)

        self.level_var = tk.StringVar(value=LEVEL_NAMES[self.ai_engine.kind])
        self.level_box = ttk.Combobox(
            action, textvariable=self.level_var, state="readonly", width=16,
            values=[LEVEL_NAMES[k] for k in LEVELS], font=font,
        )
        self.level_box.grid(row=2, column=6, padx=(12, 4))
        self.level_box.bind("<<ComboboxSelected>>", self.on_level_change)
        tk.Label(action, text="电脑强度", font=("Microsoft YaHei", 9),
                 bg="#ffffff", fg="#455a64").grid(row=1, column=6, padx=(12, 4))

        hand_box = tk.LabelFrame(middle, text="你的手牌（点击选择）", font=font, bg="#ffffff", fg="#17324d")
        hand_box.grid(row=1, column=0, sticky="nsew", pady=4)
        hand_box.rowconfigure(0, weight=1)
        hand_box.columnconfigure(0, weight=1)
        self.hand_inner = tk.Frame(hand_box, bg="#ffffff")
        self.hand_inner.grid(row=0, column=0, sticky="nw", padx=6, pady=6)

        # bottom: seen + log
        bottom = tk.Frame(self.root, bg="#eef3f8")
        bottom.grid(row=3, column=0, sticky="nsew", padx=6, pady=(0, 4))
        bottom.columnconfigure(0, weight=1)
        bottom.columnconfigure(1, weight=3)
        bottom.rowconfigure(0, weight=1)

        seen_box = tk.LabelFrame(bottom, text="记牌 / 底牌信息", font=font, bg="#ffffff", fg="#17324d")
        seen_box.grid(row=0, column=0, sticky="nsew", padx=(0, 4))
        self.seen_text = self._make_text(
            seen_box, height=6, width=38, font=small, bg="#ffffff", fg="#263238",
        )
        self.seen_text.pack(fill="both", expand=True, padx=4, pady=4)

        log_box = tk.LabelFrame(bottom, text="对局记录", font=font, bg="#ffffff", fg="#17324d")
        log_box.grid(row=0, column=1, sticky="nsew")
        log_box.rowconfigure(0, weight=1)
        log_box.columnconfigure(0, weight=1)
        self.log_text = self._make_text(
            log_box, height=6, width=1, font=small, bg="#ffffff", fg="#263238",
        )
        self.log_text.grid(row=0, column=0, sticky="nsew", padx=(4, 0), pady=4)
        sb = tk.Scrollbar(log_box, command=self.log_text.yview)
        sb.grid(row=0, column=1, sticky="ns", pady=4)
        self.log_text.configure(yscrollcommand=sb.set)

    def _make_ai_panel(self, parent: tk.Frame, seat: int, row: int, col: int) -> None:
        names = {1: "电脑·下家", 2: "电脑·对家", 3: "电脑·上家"}
        box = tk.LabelFrame(parent, text=f"{names[seat]}（{self._team_label(seat)}）",
                            font=("Microsoft YaHei", 10), bg="#f8fbff", fg="#17324d")
        box.grid(row=row, column=col, sticky="nsew", padx=6, pady=4)

        content = tk.Frame(box, bg="#f8fbff")
        content.pack(fill="both", expand=True, padx=4, pady=4)
        content.columnconfigure(0, weight=1)
        info = tk.Frame(content, bg="#f8fbff")
        info.grid(row=0, column=0, sticky="nsew")
        track = tk.Frame(content, bg="#f8fbff")
        track.grid(row=0, column=1, sticky="ne", padx=(4, 0))

        count = tk.Label(info, text="", font=("Microsoft YaHei", 10, "bold"),
                         bg="#f8fbff", fg="#0d47a1")
        count.pack(anchor="w", padx=4)
        role = tk.Label(info, text="", font=("Microsoft YaHei", 9),
                        bg="#f8fbff", fg="#455a64")
        role.pack(anchor="w", padx=4)
        last = self._make_text(info, bg="#f8fbff", fg="#37474f",
                               font=("Microsoft YaHei", 9), height=2, width=18)
        last.pack(anchor="w", padx=4, pady=(2, 2), fill="x")
        self.ai_panels[seat] = {"count": count, "role": role, "last": last}

        groups = (("single", "单张"), ("pair", "对子/拖拉机"))
        symbols = (
            ("S", "♠", CARD_BLACK),
            ("H", "♥", CARD_RED),
            ("C", "♣", CARD_BLACK),
            ("D", "♦", CARD_RED),
            ("T", "主", CARD_BLACK),
        )
        for r, (group, title) in enumerate(groups):
            tk.Label(track, text=title, font=("Microsoft YaHei", 8),
                     bg="#f8fbff", fg="#455a64").grid(
                row=r, column=0, sticky="w", padx=(0, 3), pady=1
            )
            for c, (key, sym, color) in enumerate(symbols):
                btn = tk.Button(
                    track, text=sym, width=2, font=self.track_font, fg=color,
                    bg="#f0f0f0", activebackground="#ffe082", relief="raised", bd=1,
                    command=lambda s=seat, g=group, k=key: self._toggle_track(s, g, k),
                )
                btn.grid(row=r, column=c + 1, padx=1, pady=1)
                self.track_state[(seat, group, key)] = False
                self.track_buttons[(seat, group, key)] = btn

        # 自由笔记：给自己写"这家可能没黑桃了"之类的备忘。
        # 程序不读也不校验，只是记事本；新开一局自动清空。
        note = tk.Text(box, height=2, width=22, wrap="word", bd=1, relief="solid",
                       font=("Microsoft YaHei", 9), bg="#fffde7", fg="#3e2723",
                       insertbackground="#3e2723")
        note.pack(fill="x", padx=6, pady=(0, 5))
        self.ai_panels[seat]["note"] = note

    # ------------------------------------------------------------- helpers
    def _clear_notes(self) -> None:
        """新的一局开始，把三个笔记框清空。"""
        for panel in self.ai_panels.values():
            note = panel.get("note")
            if note is not None:
                note.delete("1.0", "end")

    def _team_label(self, seat: int) -> str:
        return "你方" if self.game.team(seat) == 0 else "对方"

    def _seat_name(self, seat: int) -> str:
        return {0: "你", 1: "下家", 2: "对家", 3: "上家"}[seat]

    def _phase_text(self) -> str:
        if self.game.phase == "bid_initial":
            return "初始亮主"
        if self.game.phase == "bid_extra":
            return "抄底/换底"
        if self.game.phase == "bury_initial":
            return "初始埋底"
        if self.game.phase == "bury_extra":
            return "换底"
        return PHASE_TEXT.get(self.game.phase, self.game.phase)

    def _trump_text(self) -> str:
        if self.game.trump_suit is None:
            if self.game.phase == "bid_initial":
                return "未定"
            return "无主"
        return f"{SUIT_SYMBOLS[self.game.trump_suit]}{SUIT_NAMES[self.game.trump_suit]}"

    def _current_bid_text(self) -> str:
        return self.game.declaration.label() if self.game.declaration else "无"

    def _human_pending_bury(self) -> bool:
        return self.game.phase in ("bury_initial", "bury_extra") and self.game.pending_bury_by == 0

    def _display_cards(self) -> List[Card]:
        if self._human_pending_bury():
            return list(self.game.hands[0]) + list(self.game.bottom)
        return list(self.game.hands[0])

    def _needed_cards(self) -> Optional[int]:
        if self.game.phase == "play" and self.game.trick and self.game.trick.lead:
            return len(self.game.trick.lead.cards)
        return None

    # --------------------------------------------------------------- refresh
    def refresh(self) -> None:
        g = self.game
        zhuang = "未定" if g.zhuang is None else f"{self._seat_name(g.zhuang)}（{self._team_label(g.zhuang)}）"
        info = (
            f"第 {g.deal_no} 局   |   庄家：{zhuang}   |   级牌：{rank_label(g.level)}   |   "
            f"主牌：{self._trump_text()}   |   当前亮主：{self._current_bid_text()}   |   "
            f"你方级别：{g.levels.get(0, 3)}   对方级别：{g.levels.get(1, 3)}   |   "
            f"闲家分：{g.defender_points}   庄家分：{g.declarer_points}   |   "
            f"阶段：{self._phase_text()}"
        )
        self._set_colored_text(self.info_text, info)

        if g.deal_no != self.track_deal_no:
            self._reset_tracks()
            self.track_deal_no = g.deal_no
            self.ai_engine.begin_deal(g)
            self._clear_notes()

        self._update_track_buttons()

        for seat in (1, 2, 3):
            panel = self.ai_panels[seat]
            role = "庄家" if seat == g.zhuang else "闲家"
            panel["count"].configure(text=f"手牌 {len(g.hands[seat])} 张")
            panel["role"].configure(text=f"{role} · {self._team_label(seat)}")
            self._set_colored_text(panel["last"], self._last_play_text(seat))
        self.human_label.configure(
            text=f"手牌 {len(g.hands[0])} 张 · "
                 f"{'庄家' if g.zhuang == 0 else '闲家'} · {self._team_label(0)}"
        )

        self._set_colored_text(self.trick_text, self._trick_text())
        self.status_label.configure(text=self._status_text())
        self.selected_label.configure(text=self._selected_text())
        self._render_hand()
        self._render_bids()
        self._update_buttons()
        if g.phase in ("settle", "match_over"):
            self._save_record_once()
        self._render_seen()
        self._render_log()
        logger.debug("refresh phase=%s acting=%s", g.phase, g.acting_seat())

    def _last_play_text(self, seat: int) -> str:
        g = self.game
        if g.trick:
            for s, cards in g.trick.plays:
                if s == seat:
                    return "本墩：" + " ".join(c.label for c in cards)
        return "—"

    def _trick_text(self) -> str:
        g = self.game
        if not g.trick or not g.trick.lead:
            return "等待领出……"
        lines = [f"领出：{self._seat_name(g.trick.plays[0][0]) if g.trick.plays else '?'} "
                 f"{' '.join(c.label for c in g.trick.lead.cards)}"]
        for seat, cards in g.trick.plays[1:]:
            lines.append(f"{self._seat_name(seat)}：{' '.join(c.label for c in cards)}")
        if g.phase == "settle":
            lines.append("本局结束。")
        return "\n".join(lines)

    def _status_text(self) -> str:
        g = self.game
        if g.phase == "bid_initial":
            if g.current_bidder == 0:
                return "轮到你亮主/反主/加固；没有合适的牌就点“过”。"
            return f"等待 {self._seat_name(g.current_bidder)} 亮主……"
        if g.phase == "bid_extra":
            if g.current_bidder == 0:
                return "抄底阶段：轮到你反主/加固/自升无主；不反就点“过”。"
            return f"抄底阶段：等待 {self._seat_name(g.current_bidder)} 表态……"
        if g.phase == "bury_initial":
            if g.pending_bury_by == 0:
                return "你是庄家：请从手牌+底牌中选 8 张埋底（浅蓝色是底牌）。"
            return f"等待 {self._seat_name(g.pending_bury_by)} 埋底……"
        if g.phase == "bury_extra":
            if g.pending_bury_by == 0:
                return "你反主成功：请从手牌+底牌中选 8 张重新埋底（浅蓝色是底牌）。"
            return f"等待 {self._seat_name(g.pending_bury_by)} 换底……"
        if g.phase == "play":
            need = self._needed_cards()
            if g.current_player == 0:
                if need:
                    return f"轮到你出牌：本墩需要 {need} 张，已选 {len(self.selected)} 张。"
                return "轮到你领出：选牌后点“出牌”。"
            return f"等待 {self._seat_name(g.current_player)} 出牌……"
        if g.phase == "settle":
            r = g.deal_result or {}
            return (f"本局结算：闲家 {r.get('score', 0)} 分，{r.get('kind', '')}；"
                    f"{'下一局' if not g.match_over else '全场结束'}。")
        if g.phase == "match_over":
            winner = "你方" if g.winner_team == 0 else "对方"
            return f"全场结束：{winner}获胜！"
        return ""

    def _selected_text(self) -> str:
        g = self.game
        if g.phase in ("bury_initial", "bury_extra") and g.pending_bury_by == 0:
            return f"已选 {len(self.selected)}/8 张"
        need = self._needed_cards()
        if need:
            return f"已选 {len(self.selected)}/{need} 张"
        return f"已选 {len(self.selected)} 张"

    def _render_hand(self) -> None:
        for w in self.hand_inner.winfo_children():
            w.destroy()
        g = self.game
        cards = self._display_cards()
        # drop stale selection
        cards_set = set(cards)
        self.selected = {c for c in self.selected if c in cards_set}
        if g.phase not in ("play", "bury_initial", "bury_extra"):
            self.selected.clear()

        cards = sort_hand(cards, g.level, g.trump_suit)
        bottom_set = set(g.bottom) if self._human_pending_bury() else set()
        for i, c in enumerate(cards):
            selected = c in self.selected
            if selected:
                bg = "#ffe082"
            elif c in bottom_set:
                bg = "#d6ecff"
            else:
                bg = "#ffffff"
            fg = CARD_RED if (c.suit in ("H", "D") or c.is_big) else CARD_BLACK
            btn = tk.Button(
                self.hand_inner, text=c.label, width=4, height=1,
                font=("Microsoft YaHei", 10, "bold"), bg=bg, fg=fg,
                activebackground="#ffecb3", relief="raised", bd=1,
                command=lambda card=c: self.on_card(card),
            )
            btn.grid(row=i // 13, column=i % 13, padx=1, pady=1, sticky="nsew")
        for col in range(13):
            self.hand_inner.columnconfigure(col, weight=1)

    def _render_bids(self) -> None:
        for w in self.bid_frame.winfo_children():
            w.destroy()
        g = self.game
        if g.phase not in ("bid_initial", "bid_extra"):
            return
        if g.current_bidder != 0:
            tk.Label(self.bid_frame, text=f"等待 {self._seat_name(g.current_bidder)} 表态……",
                     font=("Microsoft YaHei", 9), bg="#eef3f8", fg="#546e7a").grid(
                row=0, column=0, sticky="w"
            )
            return
        bids = g.legal_bids(0)
        if not bids:
            tk.Label(self.bid_frame, text="没有可亮的牌；可以点“过”。",
                     font=("Microsoft YaHei", 9), bg="#eef3f8", fg="#546e7a").grid(
                row=0, column=0, sticky="w"
            )
        for i, b in enumerate(bids):
            tk.Button(
                self.bid_frame, text=b.label(), font=("Microsoft YaHei", 9),
                bg="#e8f5e9", fg=self._bid_fg(b), activebackground="#c8e6c9",
                command=lambda bid=b: self.on_bid(bid),
            ).grid(row=i // 4, column=i % 4, padx=3, pady=2, sticky="w")

    @staticmethod
    def _bid_fg(bid: Bid) -> str:
        if bid.kind == "nt_big":
            return CARD_RED
        if bid.kind == "nt_small":
            return CARD_BLACK
        return CARD_RED if bid.suit in ("H", "D") else CARD_BLACK

    def _update_buttons(self) -> None:
        g = self.game
        # action
        if g.phase in ("bury_initial", "bury_extra") and g.pending_bury_by == 0:
            self.action_button.configure(text="确认埋底", state="normal" if len(self.selected) == 8 else "disabled")
        elif g.phase == "play" and g.current_player == 0:
            self.action_button.configure(text="出牌", state="normal" if self.selected else "disabled")
        else:
            self.action_button.configure(text="出牌", state="disabled")
        # hint
        hint_ok = (g.phase == "play" and g.current_player == 0) or (
            g.phase in ("bury_initial", "bury_extra") and g.pending_bury_by == 0
        )
        self.hint_button.configure(state="normal" if hint_ok else "disabled")
        # pass
        self.pass_button.configure(
            state="normal" if (g.phase in ("bid_initial", "bid_extra") and g.current_bidder == 0) else "disabled"
        )
        # next
        if g.phase == "settle":
            self.next_button.configure(text="下一局", state="normal")
        elif g.phase == "match_over":
            self.next_button.configure(text="再来一场", state="normal")
        else:
            self.next_button.configure(text="下一局", state="disabled")

    def _render_seen(self) -> None:
        g = self.game
        lines: List[str] = []
        if g.last_burier is None:
            lines.append("尚未埋底。")
        elif g.last_burier == 0:
            lines.append("你是最后埋底者，知道最终底牌：")
            lines.append(" ".join(c.label for c in sort_hand(g.bottom, g.level, g.trump_suit)))
        else:
            lines.append(f"最终底牌由 {self._seat_name(g.last_burier)} 掌握；你不知道内容。")
        seen = g.seen_bottoms.get(0, [])
        if seen:
            lines.append("你曾看过的底牌：")
            for idx, cards in enumerate(seen, 1):
                ordered = sort_hand(list(cards), g.level, g.trump_suit)
                lines.append(f"第 {idx} 次：{' '.join(c.label for c in ordered)}")
        else:
            lines.append("你还没看过底牌。")
        self._set_colored_text(self.seen_text, "\n".join(lines))

    def _render_log(self) -> None:
        lines = self.game.log[-80:]
        self._set_colored_text(self.log_text, "\n".join(lines))

    def _make_text(self, parent: tk.Widget, **kwargs) -> tk.Text:
        kwargs.setdefault("state", "disabled")
        kwargs.setdefault("wrap", "word")
        kwargs.setdefault("bd", 0)
        kwargs.setdefault("highlightthickness", 0)
        kwargs.setdefault("takefocus", 0)
        kwargs.setdefault("cursor", "arrow")
        widget = tk.Text(parent, **kwargs)
        widget.tag_configure("card_red", foreground=CARD_RED)
        widget.tag_configure("card_black", foreground=CARD_BLACK)
        return widget

    def _set_colored_text(self, widget: tk.Text, text: str) -> None:
        widget.configure(state="normal")
        widget.delete("1.0", "end")
        pos = 0
        for match in CARD_TOKEN_RE.finditer(text):
            if match.start() > pos:
                widget.insert("end", text[pos:match.start()])
            tag = "card_red" if _token_is_red(match.group()) else "card_black"
            widget.insert("end", match.group(), tag)
            pos = match.end()
        if pos < len(text):
            widget.insert("end", text[pos:])
        widget.see("end")
        widget.configure(state="disabled")

    def _toggle_track(self, seat: int, group: str, key: str) -> None:
        state_key = (seat, group, key)
        on = not self.track_state.get(state_key, False)
        self.track_state[state_key] = on
        btn = self.track_buttons.get(state_key)
        if btn is not None:
            btn.configure(
                font=self.track_font_strike if on else self.track_font,
                bg="#ffe082" if on else "#f0f0f0",
            )

    def _reset_tracks(self) -> None:
        for key in list(self.track_state.keys()):
            self.track_state[key] = False
        for btn in self.track_buttons.values():
            btn.configure(font=self.track_font, bg="#f0f0f0")

    TRACK_SYMBOLS = {"S": "♠", "H": "♥", "C": "♣", "D": "♦", "T": "主"}

    def _update_track_buttons(self) -> None:
        """主牌花色确定后（且不是无主），把该花色那个按钮显示成"主"，并隐藏单独的"主"按钮。

        这些按钮只是给人做标记用的、系统不参与判断，所以只是**显示**变化：
        标记状态仍按原来的按钮记录，下一局随 `_reset_tracks()` 一起清空。
        无主（`trump_suit is None`）时保持 5 个按钮不变。
        """
        trump = self.game.trump_suit if self.game else None
        for (seat, group, key), btn in self.track_buttons.items():
            if trump is not None and key == "T":
                btn.grid_remove()
                continue
            if trump is not None and key == trump:
                btn.configure(text="主",
                              fg=CARD_RED if trump in ("H", "D") else CARD_BLACK)
            else:
                btn.configure(text=self.TRACK_SYMBOLS.get(key, key),
                              fg=CARD_RED if key in ("H", "D") else CARD_BLACK)
            btn.grid()

    # --------------------------------------------------------------- actions
    def on_card(self, card: Card) -> None:
        g = self.game
        if g.phase not in ("play", "bury_initial", "bury_extra"):
            return
        if g.phase == "play" and g.current_player != 0:
            return
        if g.phase in ("bury_initial", "bury_extra") and g.pending_bury_by != 0:
            return
        if card in self.selected:
            self.selected.remove(card)
        else:
            if g.phase in ("bury_initial", "bury_extra") and len(self.selected) >= 8:
                self.status_label.configure(text="埋底只能选 8 张；请先取消一张。")
                return
            self.selected.add(card)
        self.refresh()

    def on_action(self) -> None:
        g = self.game
        try:
            if g.phase in ("bury_initial", "bury_extra") and g.pending_bury_by == 0:
                if len(self.selected) != 8:
                    self._message("请选 8 张埋底。")
                    return
                ok, msg = g.submit_bury(0, list(self.selected))
                if not ok:
                    self._message(msg)
                    return
                self.selected.clear()
                self.refresh()
                self.schedule_ai()
                return
            if g.phase == "play" and g.current_player == 0:
                cards = list(self.selected)
                if not cards:
                    self._message("请先选牌。")
                    return
                lead_before = g.trick.lead if (g.trick and g.trick.lead) else None
                if lead_before is not None:
                    ok, msg = g.play_follow(0, cards)
                else:
                    ok, msg = g.play_lead(0, cards)
                if not ok:
                    self._message(msg)
                    return
                self.ai_engine.observe(g, 0, cards, lead_before)
                self.selected.clear()
                self.refresh()
                self.schedule_ai()
        except Exception:
            self.logger.exception("human action failed")
            self._message("操作失败，详见 logs/run.log。")

    def on_level_change(self, _event=None) -> None:
        """切换电脑强度。下一局生效（当前的记牌状态不重建，避免中途错乱）。"""
        name = self.level_var.get()
        for kind, label in LEVEL_NAMES.items():
            if label == name:
                self.ai_engine.set_kind(kind)
                self._message("电脑强度已切到「%s」，从下一局开始生效。" % label)
                return

    def on_hint(self) -> None:
        g = self.game
        try:
            if g.phase == "play" and g.current_player == 0:
                # 提示用**当前选中的电脑强度**算，而不是固定最弱的规则 AI
                cards = self.ai_engine.play(g, 0)
                if cards:
                    self.selected = set(cards)
                    self.refresh()
                    self._message("提示（%s）：已选中建议出的牌。"
                                  % LEVEL_NAMES[self.ai_engine.kind])
                else:
                    self._message("没有找到可出的牌。")
            elif g.phase in ("bury_initial", "bury_extra") and g.pending_bury_by == 0:
                cards = self.ai_engine.bury(g, 0)
                if cards:
                    self.selected = set(cards)
                    self.refresh()
        except Exception:
            self.logger.exception("hint failed")
            self._message("提示失败，详见 logs/run.log。")

    def on_bid(self, bid: Bid) -> None:
        g = self.game
        try:
            ok, msg = g.submit_bid(0, bid)
            if not ok:
                self._message(msg)
                return
            self.selected.clear()
            self.refresh()
            self.schedule_ai()
        except Exception:
            self.logger.exception("bid failed")
            self._message("亮主失败，详见 logs/run.log。")

    def on_pass(self) -> None:
        g = self.game
        try:
            ok, msg = g.submit_bid(0, None)
            if not ok:
                self._message(msg)
                return
            self.refresh()
            self.schedule_ai()
        except Exception:
            self.logger.exception("pass failed")
            self._message("操作失败，详见 logs/run.log。")

    def on_next(self) -> None:
        g = self.game
        if g.phase == "match_over":
            self.on_new_match()
            return
        if g.phase != "settle":
            return
        self._save_record_once()
        try:
            g.next_deal()
        except Exception:
            self.logger.exception("next deal failed")
            self._message("下一局失败，详见 logs/run.log。")
            return
        self.saved_deal_no = None
        self.ai_fail_count = 0
        self.selected.clear()
        self.refresh()
        self.schedule_ai()

    def on_new_match(self) -> None:
        if not messagebox.askyesno("新的一场", "确定放弃当前对局，重新开始一场吗？"):
            return
        if self.ai_job is not None:
            self.root.after_cancel(self.ai_job)
            self.ai_job = None
        self.game = TractorGame()
        self.selected.clear()
        self.saved_deal_no = None
        self.ai_fail_count = 0
        self.track_deal_no = -1
        self.game.start_match()
        self.refresh()
        self.schedule_ai()

    def _message(self, text: str) -> None:
        self.status_label.configure(text=text)
        self.game.add_log(text)

    def _save_record_once(self) -> None:
        g = self.game
        if g.deal_record is None or self.saved_deal_no == g.deal_no:
            return
        path = save_deal(g.deal_record, self.data_dir)
        self.saved_deal_no = g.deal_no
        if path:
            self.game.add_log(f"本局存档：{path.name}")
        else:
            self.game.add_log("本局存档失败（data 目录不可写？）")

    # --------------------------------------------------------------- AI loop
    def schedule_ai(self) -> None:
        if self.ai_job is not None:
            self.root.after_cancel(self.ai_job)
            self.ai_job = None
        g = self.game
        if g.phase in ("settle", "match_over"):
            return
        seat = g.acting_seat()
        if seat is None or seat == 0:
            return
        self.ai_job = self.root.after(450, self.ai_step)

    def ai_step(self) -> None:
        self.ai_job = None
        g = self.game
        progressed = False
        try:
            if g.phase in ("bid_initial", "bid_extra") and g.current_bidder != 0:
                seat = g.current_bidder
                bid = self.ai_engine.bid(g, seat)
                ok, msg = g.submit_bid(seat, bid)
                if not ok:
                    self.logger.warning("AI bid rejected: %s; passing", msg)
                    ok, msg = g.submit_bid(seat, None)
                progressed = ok
            elif g.phase in ("bury_initial", "bury_extra") and g.pending_bury_by not in (None, 0):
                seat = g.pending_bury_by
                cards = self.ai_engine.bury(g, seat)
                ok, msg = g.submit_bury(seat, cards)
                if ok:
                    self.ai_engine.note_buried(seat, cards)
                else:
                    self.logger.warning("AI bury rejected: %s", msg)
                    pool = g.hands[seat] + g.bottom
                    ok, msg = g.submit_bury(seat, pool[:8])
                progressed = ok
            elif g.phase == "play" and g.current_player != 0:
                seat = g.current_player
                cards = self.ai_engine.play(g, seat)
                lead_before = g.trick.lead if (g.trick and g.trick.lead) else None
                if lead_before is not None:
                    ok, msg = g.play_follow(seat, cards)
                    if not ok:
                        cards = self._fallback_follow(seat)
                        ok, msg = g.play_follow(seat, cards)
                else:
                    ok, msg = g.play_lead(seat, cards)
                    if not ok:
                        cards = [g.hands[seat][0]]
                        ok, msg = g.play_lead(seat, cards)
                progressed = ok
                if ok:
                    self.ai_engine.observe(g, seat, cards, lead_before)
                else:
                    self.logger.warning("AI play rejected: %s", msg)
                    self._message(f"电脑出牌失败：{msg}")
        except Exception:
            self.logger.exception("AI step failed")
            self._message("电脑操作失败，详见 logs/run.log。")
        if progressed:
            self.ai_fail_count = 0
        else:
            self.ai_fail_count += 1
        self.refresh()
        if self.ai_fail_count >= 4:
            self._message("电脑连续操作失败，请点“新的一场”重新开始。")
            return
        self.schedule_ai()

    def _fallback_follow(self, seat: int) -> List[Card]:
        g = self.game
        assert g.trick and g.trick.lead
        lead = g.trick.lead
        n = len(lead.cards)
        hand = g.hands[seat]
        cat = lead.category
        hand_cat = [c for c in hand if cat.contains(c)]
        if len(hand_cat) <= n:
            selected = list(hand_cat)
            rest = [c for c in hand if c not in selected]
            rest.sort(key=lambda c: (card_points(c), c.rank))
            selected.extend(rest[: max(0, n - len(selected))])
            return selected[:n]
        if len(hand_cat) <= 8:
            for combo in itertools.combinations(hand_cat, n):
                cards = list(combo)
                from .rules import is_legal_follow
                if is_legal_follow(hand, cards, lead, g.level, g.trump_suit)[0]:
                    return cards
        return hand_cat[:n]

    # ---------------------------------------------------------------- close
    def on_close(self) -> None:
        if self.ai_job is not None:
            try:
                self.root.after_cancel(self.ai_job)
            except Exception:
                pass
        try:
            geo = self.root.geometry()
            if not self._geometry_fits(geo):
                geo = self._default_geometry()
            save_window_geometry(self.cfg_dir, geo)
        except Exception:
            pass
        self.root.destroy()


def launch(project_dir: Path) -> None:
    root = tk.Tk()
    TractorApp(root, project_dir)
    root.mainloop()
