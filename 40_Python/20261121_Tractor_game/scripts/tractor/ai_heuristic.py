"""阶段 1 骨架：会记牌的规则型 AI。

和 `ai.py` 的区别（也是它现在的主要短板）：

  1. **会记牌**：知道哪些牌已经出现、谁缺哪门（`memory.CardTracker`）
  2. **会给队友送分**：队友当前领先时主动垫分牌（10 / K / 5）
  3. **会算"能不能赢"**：用 1 层评估判断这一手打完本墩谁领先，而不是只看自己手牌大小
  4. **领出会挑大的**：优先兑现"已经确定最大"的牌，避免白送分

仍然是**启发式，不含搜索**。真正的搜索（双明手 + 定约采样）在阶段 2/3 接进来，
接口就开在 `choose_play()` 里 —— 到时候把这里的 1 层评估换成 `search.py` 的调用即可。

TODO（留给阶段 2/3）：
  - [ ] 用 `search.expectimax` / 双明手求解器替换 `_score_play` 的 1 层评估
  - [ ] 亮主阶段引入对手建模（现在只是按手牌打分）
  - [ ] 埋底考虑"造缺门"的长期价值，而不只是保留价值
  - [ ] 尾局（最后 3~5 墩）单独处理：抠底倍数 ×1~64，权重完全不同
"""
from __future__ import annotations

import random
from typing import List, Optional, Sequence, Tuple

from . import moves
from .cards import Card, card_points, is_trump, power
from .engine import Bid, TractorGame
from .fast_state import FastState
from .rules import bottom_multiplier, decompose_lead
from .memory import CardTracker, card_id

POINT_RANKS = (5, 10, 13)


def _points(cards: Sequence[Card]) -> int:
    return sum(card_points(c) for c in cards)


class HeuristicAI:
    """会记牌的启发式 AI。一个实例可以当作一队的策略。"""

    name = "heuristic"

    def __init__(self, rng: Optional[random.Random] = None, verbose: bool = False,
                 opts: Optional[dict] = None) -> None:
        self.rng = rng or random.Random(20261121)
        self.verbose = verbose
        # 中前盘的开关（默认全关 = 旧行为，便于 A/B 对照）
        self.opts = {
            "bury_void": False,      # 埋底时整门埋掉、造缺门
            "lead_master": False,    # 领出时优先兑现确定最大牌、避开被毙
            "keep_pairs": False,     # 拆对子扣分（对子在拖拉机里很贵）
            "trump_void": True,      # 用「领主牌没跟」推断某人缺主牌
            "use_bottom": True,      # 我是最后埋底的人时，用确知的底牌收紧推断
            # 反主要等庄家埋完底再反（为了拿到换底，而不是只换主牌花色）。
            # 实测强度中性（1500 局 +0.012±0.039），但**行为上更合理**：
            # 开着它 AI 才会真的换底（约 33% 的局），便于观察它的埋底习惯。
            "bid_wait_bury": True,
            # 「牌权」值多少分：赢下一个没分的墩本身没收益，但能拿到下一轮的领出权。
            # 注意 _cost 里主牌成本约 45 分，所以这个数要同量级才有意义；
            # 80 以上会饱和（等价于"只要能赢就赢"）。1500 局 A/B 实测 +0.055±0.038。
            "tempo": 80.0,
            "kitty_aware": True,     # 最后一墩考虑抠底倍数（x1~x64）
            "bid_mode": "basic",     # basic / trump / conservative（见 _trump_strength）
            "bid_min": 26.0,         # conservative 模式的开门门槛
        }
        if opts:
            self.opts.update(opts)
        self.tracker: Optional[CardTracker] = None
        self._my_buried: dict = {}       # seat -> 我最近一次埋下去的那 8 张
        self._seen_kitty: dict = {}      # seat -> 我这局看过的所有底牌（并集）
        self._deal_key: Optional[Tuple] = None

    # ------------------------------------------------------------------ 生命周期
    def begin_deal(self, game: TractorGame) -> None:
        """庄家/闲家定了之后调用一次：重置记忆。"""
        self.tracker = CardTracker(game.level, game.trump_suit, my_seat=0)
        # **必须一并清掉"我埋过什么"**：这两个字典是跨局累积的，
        # 不清的话上一局埋过底的座位会被当成"这一局也看过底牌"，
        # 甚至让 known_bottom 装进上一局的牌（错误信息比没有信息更糟）。
        self._my_buried.clear()
        self._seen_kitty.clear()
        self._deal_key = (game.deal_no, game.level, game.trump_suit, game.zhuang)

    def _ensure(self, game: TractorGame, seat: int) -> CardTracker:
        if self.tracker is None:
            self.tracker = CardTracker(game.level, game.trump_suit, my_seat=seat)
        self.tracker.my_seat = seat
        self.tracker.observe_hand(game.hands[seat])
        return self.tracker

    def observe(self, game: TractorGame, seat: int, cards: Sequence[Card], lead=None) -> None:
        """别人出完牌后喂给记忆（评估台会调用）。"""
        if self.tracker is None:
            return
        self.tracker.observe_play(seat, cards, lead)

    # ------------------------------------------------------------------ 亮主
    def bid(self, game: TractorGame, seat: int) -> Optional[Bid]:
        bids = game.legal_bids(seat)
        if not bids:
            return None
        hand = game.hands[seat]
        cur = game.declaration
        mode = self.opts.get("bid_mode", "basic")
        level = game.level

        def strength(b: Bid) -> float:
            if mode == "basic":
                n = sum(1 for c in hand if c.suit == b.suit) if b.suit else 0
                honors = sum(1 for c in hand if c.suit == b.suit and c.rank >= 11) if b.suit else 0
                jokers = sum(1 for c in hand if c.is_joker)
                points = _points(hand)
                base = n * 1.0 + honors * 1.5 + jokers * 2.0 + points * 0.05
                if b.kind == "pair":
                    base += 3.0
                elif b.kind in ("nt_small", "nt_big"):
                    base += 2.0
                return base
            # trump 模式：庄家真正需要的是**主牌的长度和顶上那几张**，
            # 而不是手牌总分。手牌分（5/10/K）留在手里对庄家是中性的。
            base = _trump_strength(hand, b.suit, level)
            if b.kind == "pair":
                base += 4.0
            elif b.kind in ("nt_small", "nt_big"):
                base += 2.0
            return base

        if cur is None:
            best = max(bids, key=strength)
            if mode == "conservative" and strength(best) < self.opts.get("bid_min", 26.0):
                return None                  # 手牌不够硬就先过，别硬抢庄
            return best

        # **等庄家埋完底再反主**（bid_wait_bury）。
        # 在 `bid_initial` 反主只会改主牌花色，庄家照常自己埋底 —— 等于把
        # **换底**的机会浪费掉了。改到 `bid_extra`（庄家已经埋完）再反主，
        # 就能拿底牌重新埋 8 张：造断门、加强副牌，而且庄家不知道你断了哪门。
        if (self.opts.get("bid_wait_bury", False)
                and game.phase == "bid_initial"
                and game.team(cur.seat) != game.team(seat)):
            return None
        if cur.seat == seat:
            streng = [b for b in bids if b.strengthen]
            if streng:
                return max(streng, key=strength)
            return None
        if game.team(cur.seat) == game.team(seat):
            return None                      # 队友已经亮了，不抢
        counters = [b for b in bids if b.level > cur.level]
        if not counters:
            return None
        best = max(counters, key=strength)
        # 只有分数明显更强才反主，避免无谓换底
        margin = 1.5 if mode == "basic" else 3.0
        if strength(best) >= strength_of_bid(cur, hand) + margin:
            return best
        return None

    # ------------------------------------------------------------------ 埋底
    def bury(self, game: TractorGame, seat: int) -> List[Card]:
        pool = list(game.hands[seat]) + list(game.bottom)
        level, trump = game.level, game.trump_suit
        groups: dict = {}
        for c in pool:
            groups.setdefault((c.suit, c.rank), []).append(c)

        def keep(c: Card) -> float:
            v = 0.0
            if c.is_joker:
                v += 140
            elif c.rank == level:
                v += 130
            elif c.rank == 2:
                v += 120
            elif is_trump(c, level, trump):
                v += 90
            v += c.rank * 2
            v += card_points(c) * 4          # 分牌尽量别埋
            if len(groups[(c.suit, c.rank)]) >= 2:
                v += 18                       # 成对留着
            return v

        chosen: List[Card] = []
        if self.opts.get("bury_void"):
            # 造缺门：找一门最短的副牌，如果整门都能埋掉（<=8 张、无分牌、无主），
            # 就整门埋掉 —— 之后这门就能用主牌毙，是拖拉机最值钱的打法之一
            shortest = None
            for suit in ("S", "H", "C", "D"):
                if suit == trump:
                    continue
                cards = [c for c in pool
                         if c.suit == suit and not is_trump(c, level, trump)]
                if not cards or _points(cards) > 0:
                    continue
                if any(len(groups[(c.suit, c.rank)]) >= 2 and c.rank >= 11 for c in cards):
                    continue
                if shortest is None or len(cards) < len(shortest):
                    shortest = cards
            if shortest is not None and len(shortest) <= 8:
                chosen = list(shortest)

        rest = [c for c in pool if c not in chosen]
        rest.sort(key=lambda c: (keep(c), c.suit, c.rank))
        chosen.extend(rest[: max(0, 8 - len(chosen))])
        chosen = chosen[:8]
        return chosen

    def note_buried(self, seat: int, cards) -> None:
        """**真的把牌埋下去了**才调用（提示算法算出的不算）。

        只有最后埋底的人才知道最终底牌；如果把"提示建议的埋法"也记成自己埋的，
        AI 就会错误地以为自己知道底牌。
        """
        self._my_buried[seat] = list(cards)
        self._seen_kitty.setdefault(seat, set()).update(card_id(c) for c in cards)

    def sync_bottom(self, st: FastState, seat: int) -> None:
        """把"我是否知道底牌"同步给记牌器。

        只有当**最后埋底的人是我**时，底牌才是确凿信息；否则一律当作不知道
        （我可能看过更早的底牌，但已经被别人换掉了，不能用）。
        """
        if self.tracker is None:
            return
        # **每次都先全部清空**：这几个字段是按座位算的，上一个座位算完的残留
        # 会让下一个座位读到别人的信息（早先就是漏清 stale_holders 才出的问题）。
        self.tracker.known_bottom = set()
        self.tracker.stale_kitty = set()
        self.tracker.stale_holders = set()
        if not self.opts.get("use_bottom", True):
            return
        mine = self._my_buried.get(seat)
        if mine and st.last_burier == seat:
            self.tracker.set_known_bottom(mine)
            return

        if not self.opts.get("stale_kitty", True):
            return
        seen = self._seen_kitty.get(seat)
        if not seen or st.last_burier is None or st.last_burier == seat:
            return
        # 我埋底之后还换过底的人 —— 只有他们（和底牌）可能拿着我看过的牌。
        # **换底可以连续发生多次**，所以要用完整的埋底顺序，不是只看最后一个。
        order = list(getattr(st, "buriers", ()) or ())
        if seat in order:
            after = set(order[order.index(seat) + 1:])
        else:
            after = set(order)          # 不知道我埋在第几次，保守放行全部
        after.discard(seat)
        if not after:
            return                      # 之后没人换过底 → 那几张只可能在底牌里
        self.tracker.stale_kitty = set(seen)
        self.tracker.stale_holders = after

    # ------------------------------------------------------------------ 出牌
    def play(self, game: TractorGame, seat: int) -> List[Card]:
        self._ensure(game, seat)
        return self.choose(FastState.from_game(game), seat)

    def choose(self, st: FastState, seat: int) -> List[Card]:
        """在给定的轻量状态上决策（评测台 / 搜索 / 双明手对账都能直接用）。"""
        tr = self.tracker or CardTracker(st.level, st.trump_suit, seat)
        tr.my_seat = seat
        self.sync_bottom(st, seat)          # 缺门信息是公开的，视角切到当前决策者
        moves_list = moves.legal_moves(st, seat, max_moves=120)
        if not moves_list:
            return list(st.hands[seat])[:1]

        scored = [(self._score_play(st, seat, mv, tr), mv) for mv in moves_list]
        scored.sort(key=lambda x: -x[0])
        best = scored[0][1]
        if self.verbose:
            print("  [AI] 座位%d 选 %s（分 %.1f）" % (
                seat, " ".join(c.label for c in best), scored[0][0]))
        return best

    # ------------------------------------------------------------------ 评估
    def _score_play(self, st: FastState, seat: int, cards: Sequence[Card], tr: CardTracker) -> float:
        """1 层评估：这一手打完之后，本墩归谁、能捞多少分。"""
        tmp = st.clone()
        ok, _, result = tmp.play(seat, cards)
        if not ok:
            return -1e9

        my_team = st.team(seat)
        if result is not None:
            # 这一手直接结束本墩
            win = st.team(result.winner) == my_team
            gain = result.points if win else -result.points
            return gain * 2.0 - self._cost(st, seat, cards)

        winner = tmp.winner_so_far()
        leading = winner is not None and st.team(winner) == my_team
        will_win = winner == seat
        stake = tmp.points_on_table()
        val = (stake * 1.5 if leading else -stake * 1.5) if stake else 0.0

        # **本墩的结果已经不受我影响**：我赢不了，或者队友已经赢着。
        # 这种时候唯一该做的就是把最没用的牌扔掉：不送分、不动大牌、不拆对子。
        decided = (not will_win) and winner is not None

        # 队友已经领先 → 尽量把分垫出去（分牌留在手里是浪费）
        if leading and winner != seat:
            val += _points(cards) * 3.0
        # 自己领先但可能被别人毙/压 → 稍微保守
        if leading and will_win:
            val += _points(cards) * 0.5

        # 会浪费大牌要扣分；本墩已定时加重 3 倍
        cost = self._cost(st, seat, cards)
        if self.opts.get("waste_fix", True):
            val -= cost * (3.0 if decided else 1.0)
        else:
            val -= cost

        # 确定最大的牌给额外奖励（兑现）—— 但**只有这一手真的赢了本墩才给**。
        # 否则会把"剩下最大的牌"扔进一个已经输掉的墩（用户实测到的就是这种）。
        if self._is_master(st, cards, tr):
            if not self.opts.get("waste_fix", True) or will_win:
                val += 25.0

        # **牌权**：赢下一个没分的墩本身没收益，但能拿到下一轮的领出权。
        # 人类玩家会为了"抢牌权"去打一个零分墩（好兑现手里的拖拉机/甩牌，
        # 或者测试对方的主牌强度）。这里用一个**可调的软奖励**近似它，
        # 而不是写死"必须抢" —— 大牌的成本仍然由 _cost 扣，所以不会乱花。
        tempo = self.opts.get("tempo", 0.0)
        if tempo:
            # "抢牌权"= 出手前是对方领先，出手后变成我领先。
            # （注意不能用 `not leading`：will_win 本身就蕴含 leading，那样条件永远不成立。）
            prev_winner = st.winner_so_far() if st.plays else None
            if (will_win and prev_winner is not None
                    and st.team(prev_winner) != my_team):
                val += tempo
        if self.opts.get("lead_master") and st.lead is None:
            val += self._lead_adjust(st, seat, cards, tr)
        val += self._kitty_term(st, seat, cards, winner)
        return val

    # ------------------------------------------------------------------ 抠底
    def _kitty_term(self, st: FastState, seat: int, cards: Sequence[Card],
                    winner: Optional[int]) -> float:
        """最后一墩的**抠底倍数**。

        规则：闲家赢下最后一墩时，底牌分 x 倍数；倍数由这一墩**领出的牌型**决定
        （单张 x1、对子 x2、k 连对 x2^k，封顶 64）。

        杠杆极大：底牌平均约 15 分，若最后一墩是 4 连对就是 15x16=240 分，
        足以把整局翻过来。**原来的 AI 完全没考虑这件事。**

        - 我队是闲家、且能赢最后一墩 -> 尽量把牌型做大（拉高倍数）
        - 我队是庄家 -> 尽量别让闲家用大牌型赢走最后一墩
        """
        if not self.opts.get("kitty_aware", True):
            return 0.0
        if not _is_last_trick(st) or winner is None:
            return 0.0

        team = st.team(seat)
        defender_team = 1 - st.team(st.zhuang)
        winner_team = st.team(winner)

        lead = st.lead if st.lead is not None else decompose_lead(
            cards, st.level, st.trump_suit)
        if lead is None:
            return 0.0
        mult = bottom_multiplier(lead)

        if self.tracker is not None and self.tracker.known_bottom:
            pts = float(sum(card_points(Card(*cid))
                            for cid in self.tracker.known_bottom))
        else:
            pts = 15.0                       # 8 张底牌的平均分值

        if winner_team != defender_team:
            return 0.0                       # 庄家赢下最后一墩，底牌不结算给闲家
        swing = pts * (mult - 1)             # 相对"x1"的额外收益
        return swing if team == defender_team else -swing

    def _lead_adjust(self, st: FastState, seat: int, cards: Sequence[Card],
                     tr: CardTracker) -> float:
        """领出专用修正（1 层评估对领出几乎无效，必须单独给信号）。

        - 领出确定最大的牌（能兑现分数）→ 加分
        - 领出会被对手毙掉的副牌 → 扣分
        - 领出分牌而自己又不是最大 → 扣分（白送）
        """
        from .cards import is_trump

        kind = "T"
        for c in cards:
            if not is_trump(c, st.level, st.trump_suit):
                kind = c.suit
                break
        attackers = [s for s in range(4) if st.team(s) != st.team(seat)]
        adj = 0.0
        if self._is_master(st, cards, tr):
            adj += 30.0 + _points(cards) * 4.0        # 兑现：越大越赚
        else:
            if kind != "T" and tr.can_be_ruffed(kind, attackers):
                adj -= 20.0                            # 会被毙
            if _points(cards) > 0:
                adj -= 6.0 * _points(cards)            # 分牌送人
        return adj

    def _cost(self, st: FastState, seat: int, cards: Sequence[Card]) -> float:
        """打掉这些牌的代价：牌力越高越贵，主牌更贵；开了 keep_pairs 时拆对子也贵。"""
        total = 0.0
        for c in cards:
            p = power(c, st.level, st.trump_suit)
            total += p * (0.08 if is_trump(c, st.level, st.trump_suit) else 0.05)
        if self.opts.get("keep_pairs"):
            hand = st.hands[seat]
            have: dict = {}
            for c in hand:
                have[(c.suit, c.rank)] = have.get((c.suit, c.rank), 0) + 1
            used: dict = {}
            for c in cards:
                used[(c.suit, c.rank)] = used.get((c.suit, c.rank), 0) + 1
            for key, n in used.items():
                # 手里有对子/拖拉机组件，却只打出一部分 → 拆了
                if have.get(key, 0) >= 2 and n < have[key]:
                    total += 9.0 * n
        return total

    def _is_master(self, st: FastState, cards: Sequence[Card], tr: CardTracker) -> bool:
        """粗略判断：这手牌在它的花色里已经无人能压（且没人能毙）。"""
        from .rules import build_category

        kind = None
        for c in cards:
            k = tr.category_letter(
                None if is_trump(c, st.level, st.trump_suit) else c.suit
            )
            if kind is None:
                kind = k
            elif kind != k:
                return False
        if kind is None:
            return False
        cat = build_category(st.level, st.trump_suit) if kind == "T" else \
            build_category(st.level, st.trump_suit, side_suit=kind)
        if all(cat.slot_of(c) is not None and cat.power_of(c) >= tr.top_remaining_power(cat) for c in cards):
            if kind == "T":
                return True
            attackers = [s for s in range(4) if st.team(s) != st.team(tr.my_seat)]
            tv = self.opts.get("trump_void", True)
            # 对手已经暴露过缺主牌 → 谁也不能毙
            if tv and tr.trumps_dead_for(attackers):
                return True
            return not tr.can_be_ruffed(kind, attackers, respect_trump_void=tv)
        return False


def _is_last_trick(st: FastState) -> bool:
    """当前这一墩是不是全盘最后一墩。

    判据：剩下要打的牌数 == 这一墩还没打的张数（张数 = 领出牌型的张数）。
    """
    k = len(st.lead.cards) if st.lead is not None else 1
    remaining = sum(len(st.hands[s]) for s in range(4))
    return remaining == k * (4 - len(st.plays))


def strength_of_bid(bid: Bid, hand: Sequence[Card]) -> float:
    """给 `bid()` 里比较"当前声明"用。"""
    n = sum(1 for c in hand if c.suit == bid.suit) if bid.suit else 0
    honors = sum(1 for c in hand if c.suit == bid.suit and c.rank >= 11) if bid.suit else 0
    jokers = sum(1 for c in hand if c.is_joker)
    base = n * 1.0 + honors * 1.5 + jokers * 2.0
    if bid.kind == "pair":
        base += 3.0
    elif bid.kind in ("nt_small", "nt_big"):
        base += 2.0
    return base


def _trump_strength(hand: Sequence[Card], suit, level: int) -> float:
    """这手牌打 `suit` 为主时，主牌有多硬。

    庄家靠的是**主牌长度 + 顶上那几张**（王/级牌/2/主 A、K），
    不是手牌里的 5/10/K 分数 —— 那些留在手里对庄家是中性的。
    """
    if suit is None:
        # 无主：只有 王 / 级牌 / 常主 2 是主
        return sum(3.0 for c in hand if c.is_joker or c.rank in (level, 2))
    n = sum(1 for c in hand if c.suit == suit)
    top = sum(1 for c in hand
              if (c.suit == suit and c.rank >= 11) or c.is_joker or c.rank in (level, 2))
    return 2.5 * n + 3.0 * top
