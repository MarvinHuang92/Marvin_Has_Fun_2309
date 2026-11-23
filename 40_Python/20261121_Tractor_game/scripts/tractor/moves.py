"""合法动作枚举（搜索的第二个前提）。

引擎里 `ai._build_play` 只造「最高」和「最低」两个候选，够规则型 AI 用，
但搜索需要**尽量全**的合法动作集合。本模块提供：

    legal_leads(state, seat, allow_throws=False)   # 领出：单张 / 对子 / 拖拉机
    legal_follows(state, seat)                     # 跟牌：把该填的槽位都填上
    legal_moves(state, seat)                       # 按当前是不是领出自动分派

所有结果都再用 `rules.is_legal_follow` / `decompose_lead` 校验一遍，
所以"生成的 = 引擎认可的"，不会出现自己造规则。

已知边界（骨架阶段的取舍）：

  - **甩牌默认不生成**（`allow_throws=False`）。甩牌的组合数是爆炸的，
    而 `FastState` 也还没实现"被卡改出小"，两边保持一致。
  - 跟牌在"缺门随便垫"和"多张单牌槽"时有组合爆炸，用 `max_moves` 截断，
    截断顺序按"由小到大"，保证便宜的走法先被看到。
"""
from __future__ import annotations

from itertools import combinations
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

from .cards import Card, card_points, category_of, is_trump, pairs_in
from .rules import (
    Category,
    LeadPattern,
    build_category,
    decompose_lead,
    is_legal_follow,
    pairs_by_slot,
)

MAX_TRACTOR_LEN = 8


# ---------------------------------------------------------------------------
# 内部工具
# ---------------------------------------------------------------------------

def _category_for(kind: str, level: int, trump_suit: Optional[str]) -> Category:
    if kind == "T":
        return build_category(level, trump_suit)
    return build_category(level, trump_suit, side_suit=kind)


def _groups(hand: Sequence[Card], level: int, trump_suit: Optional[str]) -> Dict[str, List[Card]]:
    out: Dict[str, List[Card]] = {}
    for c in hand:
        out.setdefault(category_of(c, level, trump_suit), []).append(c)
    return out


def _runs_of_length(pool: Sequence[Card], cat: Category, k: int) -> List[List[Card]]:
    """长度为 k 的连对（k >= 2）。"""
    pairs = pairs_by_slot(pool, cat)
    n = len(cat.slots)
    out: List[List[Card]] = []
    for start in range(0, n - k + 1):
        if all(pairs.get(start + i) for i in range(k)):
            cards: List[Card] = []
            for i in range(k):
                cards.extend(pairs[start + i][0].cards)
            out.append(cards)
    return out


def _dedupe(moves: Iterable[Sequence[Card]]) -> List[List[Card]]:
    seen = set()
    out: List[List[Card]] = []
    for mv in moves:
        key = frozenset(mv)
        if key in seen:
            continue
        seen.add(key)
        out.append(list(mv))
    return out


def _combinations_capped(pool: Sequence[Card], k: int, cap: int) -> List[List[Card]]:
    if k <= 0:
        return [[]]
    if k > len(pool):
        return []
    out: List[List[Card]] = []
    for combo in combinations(pool, k):
        out.append(list(combo))
        if len(out) >= cap:
            break
    return out


# ---------------------------------------------------------------------------
# 领出
# ---------------------------------------------------------------------------

def legal_leads(
    state,
    seat: int,
    *,
    allow_throws: bool = False,
    max_moves: int = 256,
) -> List[List[Card]]:
    """所有合法领出（甩牌默认不生成）。"""
    hand = list(state.hands[seat])
    level, trump = state.level, state.trump_suit
    cands: List[List[Card]] = []

    for kind, pool in _groups(hand, level, trump).items():
        cat = _category_for(kind, level, trump)
        # 单张
        cands.extend([[c] for c in pool])
        # 对子
        cands.extend([[a, b] for a, b in pairs_in(pool)])
        # 拖拉机（2 连对起）
        for k in range(2, min(MAX_TRACTOR_LEN, len(cat.slots)) + 1):
            cands.extend(_runs_of_length(pool, cat, k))

    if allow_throws:
        # 骨架阶段只做"同花色多张"的朴素甩牌，真正的被卡判定还没接
        for kind, pool in _groups(hand, level, trump).items():
            if len(pool) >= 2:
                for k in range(2, min(4, len(pool)) + 1):
                    cands.extend(_combinations_capped(pool, k, 16))

    good: List[List[Card]] = []
    for mv in _dedupe(cands):
        if decompose_lead(mv, level, trump) is None:
            continue
        good.append(mv)
        if len(good) >= max_moves:
            break
    good.sort(key=lambda mv: sum(cat.power_of(c) for c in mv))
    return good


# ---------------------------------------------------------------------------
# 跟牌
# ---------------------------------------------------------------------------

def _slot_choices(pool: Sequence[Card], slot, cat: Category) -> List[List[Card]]:
    """能填上这个槽位的所有牌组合。"""
    if slot.kind == "single":
        return [[c] for c in pool]
    if slot.kind == "pair":
        return [[a, b] for a, b in pairs_in(pool)]
    return _runs_of_length(pool, cat, slot.length)


def _fill_slots(
    pool: List[Card],
    idx_list: List[int],
    slots,
    cat: Category,
    cap: int,
    budget: List[int],
) -> List[List[Card]]:
    """递归地把所有"必须填"的槽位填满，返回所有填法。"""
    if not idx_list:
        return [[]]
    if budget[0] <= 0:
        return []
    i, rest_idx = idx_list[0], idx_list[1:]
    out: List[List[Card]] = []
    for comp in _slot_choices(pool, slots[i], cat):
        used = set(comp)
        left = [c for c in pool if c not in used]
        for sub in _fill_slots(left, rest_idx, slots, cat, cap, budget):
            out.append(list(comp) + sub)
            budget[0] -= 1
            if budget[0] <= 0:
                return out
    return out


def legal_follows(state, seat: int, *, max_moves: int = 256) -> List[List[Card]]:
    """所有合法跟牌。"""
    lead: Optional[LeadPattern] = state.lead
    if lead is None:
        return []
    hand = list(state.hands[seat])
    cat = lead.category
    n = len(lead.cards)
    level, trump = state.level, state.trump_suit
    hand_cat = [c for c in hand if cat.contains(c)]
    cands: List[List[Card]] = []

    if not hand_cat:
        # 缺门：任意 n 张
        pool = sorted(hand, key=lambda c: c.rank)
        cands = _combinations_capped(pool, n, max_moves)
    elif len(hand_cat) < n:
        # 必须把手里的该花色全出掉，再垫 (n - len) 张
        rest = sorted([c for c in hand if not cat.contains(c)], key=lambda c: c.rank)
        fill = n - len(hand_cat)
        for extra in _combinations_capped(rest, fill, max_moves):
            cands.append(list(hand_cat) + list(extra))
    else:
        # 够跟：必须填满"手里填得出来"的那些槽位
        from .rules import match_slots

        req = match_slots(hand_cat, lead.slots, cat, require_all=False, allow_partial=True)
        fillable = [i for i, r in enumerate(req) if r is not None]
        budget = [max_moves]
        for filled in _fill_slots(hand_cat, fillable, lead.slots, cat, max_moves, budget):
            used = set(filled)
            left = [c for c in hand_cat if c not in used]
            need = n - len(filled)
            if need < 0:
                continue
            # **先给一个"凑够对子"的构造**：组合枚举有 max_moves 上限，
            # 是按字典序截断的，很可能把"含对子"的组合全部截掉，于是下面
            # `is_legal_follow` 一过滤就变成 0 个合法动作（实测过）。
            from .rules import pair_count as _pc
            slot_pairs = 0
            for sl in lead.slots:
                if sl.kind == "pair":
                    slot_pairs += 1
                elif sl.kind == "tractor":
                    slot_pairs += sl.length
            np_ = min(slot_pairs, _pc(list(hand_cat), cat)) - _pc(list(filled), cat)
            if np_ > 0:
                cands.append(list(filled) + _low_fill(left, need, np_, cat,
                                                      level, trump))
            for extra in _combinations_capped(left, need, max_moves):
                cands.append(list(filled) + list(extra))

    good: List[List[Card]] = []
    for mv in _dedupe(cands):
        if len(mv) != n:
            continue
        ok, _ = is_legal_follow(hand, mv, lead, level, trump)
        if not ok:
            continue
        good.append(mv)
        if len(good) >= max_moves:
            break
    good.sort(key=lambda mv: sum(cat.power_of(c) for c in mv))
    return good


def legal_moves(state, seat: int, **kwargs) -> List[List[Card]]:
    """按当前阶段分派。"""
    if state.lead is None:
        return legal_leads(state, seat, **kwargs)
    return legal_follows(state, seat, **kwargs)


def any_legal_move(state, seat: int) -> Optional[List[Card]]:
    """兜底：至少给一个合法动作（搜索截断时用）。"""
    moves = legal_moves(state, seat, max_moves=8)
    return moves[0] if moves else None


# ---------------------------------------------------------------------------
# 快速路径（给搜索的中间节点用）
# ---------------------------------------------------------------------------
#
# `legal_moves` 是"全枚举 + 逐个用引擎判罚校验"，正确但很贵（实测 0.6 ms/节点），
# 导致限时搜索只能搜到 3~4 手牌深。搜索的中间节点不需要全枚举，
# 只需要**少量、合法、有代表性**的候选：
#
#   - 领出：最低/最高的单张、对子、拖拉机
#   - 跟牌：最省 / 最贵两种填法（必须填的槽位用最低或最高的组合）
#
# 这里**不再调 is_legal_follow**：动作是按规则构造出来的，天然合法；
# 万一构造错了，`FastState.play()` 会拒绝它，不会污染搜索。

def _pick_slot(pool: List[Card], slot, cat: Category, high: bool) -> Optional[List[Card]]:
    choices = _slot_choices(pool, slot, cat)
    if not choices:
        return None
    key = lambda mv: sum(cat.power_of(c) for c in mv)
    return max(choices, key=key) if high else min(choices, key=key)


def _fast_leads(state, seat: int, limit: int) -> List[List[Card]]:
    hand = list(state.hands[seat])
    level, trump = state.level, state.trump_suit
    out: List[List[Card]] = []
    for kind, pool in _groups(hand, level, trump).items():
        cat = _category_for(kind, level, trump)
        ordered = sorted(pool, key=lambda c: cat.power_of(c))
        out.append([ordered[0]])
        out.append([ordered[-1]])
        pairs = pairs_in(pool)
        if pairs:
            pairs.sort(key=lambda p: cat.power_of(p[0]))
            out.append([pairs[0][0], pairs[0][1]])
            out.append([pairs[-1][0], pairs[-1][1]])
        for k in (2, 3):
            runs = _runs_of_length(pool, cat, k)
            if runs:
                runs.sort(key=lambda mv: sum(cat.power_of(c) for c in mv))
                out.append(runs[0])
                out.append(runs[-1])
    return _dedupe(out)[:limit]


def discard_key(c: Card, level: int, trump, hand: Sequence[Card]) -> float:
    """垫牌时"先垫哪张"的排序键（越小越先垫）。

    不能只用点数（早先就是 `c.rank`）：那样会**先垫主 2、主 3 这种低点主牌**，
    也会把分牌当成"小牌"垫掉。用户 2026-11-23 人工对局里看到的
    「垫了两张主牌」「垫了一对 10」都是这么来的。

    优先级：非主牌 > 非分牌 > 不拆对子 > 点数小。
    """
    v = float(c.rank)
    if is_trump(c, level, trump):
        v += 1000.0                      # 主牌尽量别垫
    if card_points(c) > 0:
        v += 200.0                       # 分牌尽量别垫
    if sum(1 for x in hand if x.suit == c.suit and x.rank == c.rank) >= 2:
        v += 500.0                       # 别拆对子
    return v


def _low_fill(pool: List[Card], need: int, need_pairs: int, cat,
              level=None, trump=None) -> List[Card]:
    """从 `pool` 里取 `need` 张，**先尽量凑出 `need_pairs` 个对子**，剩下用最低的单张。

    为什么必须这样：拖拉机/对子领出时，即使凑不出同款，规则也要求**优先跟对子**。
    早先这里直接 `pool[:need]`（纯按点数从低拿），于是手里有对子也会全出单张 ——
    用户 2026-11-23 人工对局第 7 局第 4 墩抓到的就是这个。
    """
    from .rules import pair_count

    pool = list(pool)
    out: List[Card] = []
    if need_pairs > 0:
        # **按 (花色,点数) 分组**，不能用槽位：主牌里副 2 / 副级牌一个槽位横跨多花色，
        # 用槽位会把 D3+S3 当成一对。
        by_slot: Dict[Tuple[str, int], List[Card]] = {}
        for c in pool:
            if cat.slot_of(c) is None:
                continue
            by_slot.setdefault((c.suit, c.rank), []).append(c)
        # 先用**点数最低**的对子（和"垫小牌"的取向一致）
        order = sorted(by_slot.values(),
                       key=lambda cs: min(discard_key(y, level, trump, pool)
                                          for y in cs)
                       if level is not None
                       else min(card_rank_key(y) for y in cs))
        for cs in order:
            if len(out) + 2 > need:
                break
            if len(cs) >= 2:
                pair = sorted(cs, key=lambda x: discard_key(x, level, trump, pool))[:2]
                out.extend(pair)
                for c in pair:
                    pool.remove(c)
                if pair_count(out, cat) >= need_pairs:
                    break
    if level is None:
        rest = sorted(pool, key=card_rank_key)
    else:
        rest = sorted(pool, key=lambda c: discard_key(c, level, trump, pool))
    out.extend(rest[:need - len(out)])
    return out


def _fast_follows(state, seat: int, limit: int,
                  variants: int = 2) -> List[List[Card]]:
    """跟牌候选。variants=2 是原来的"全低/全高"，4 会再加两个混合方案。"""
    from .rules import match_slots

    lead: LeadPattern = state.lead
    hand = list(state.hands[seat])
    cat = lead.category
    n = len(lead.cards)
    hand_cat = [c for c in hand if cat.contains(c)]
    out: List[List[Card]] = []

    if not hand_cat:
        pool = sorted(hand, key=lambda c: discard_key(c, state.level,
                                                      state.trump_suit, hand))
        if len(pool) >= n:
            out.append(pool[:n])                 # 最该垫的 n 张
            # 对照变体：不拆对子、但同样避开主牌/分牌（早先用 card_rank_key
            # 会把 常主 2 当最小牌垫掉）
            out.append(pool[-n:])                # 最不该垫的 n 张（多样性）
        return _dedupe(out)[:limit]

    if len(hand_cat) < n:
        rest = sorted([c for c in hand if not cat.contains(c)],
                      key=lambda c: discard_key(c, state.level,
                                                state.trump_suit, hand))
        fill = n - len(hand_cat)
        if fill <= len(rest):
            out.append(list(hand_cat) + rest[:fill])
            if fill:
                out.append(list(hand_cat) + rest[-fill:])
        return _dedupe(out)[:limit]

    req = match_slots(hand_cat, lead.slots, cat, require_all=False, allow_partial=True)
    fillable = [i for i, r in enumerate(req) if r is not None]
    # (首个槽位是否取高, 其余槽位是否取高)
    if variants >= 4 and len(fillable) >= 2:
        plans = ((False, False), (True, True), (False, True), (True, False))
    else:
        plans = ((False, False), (True, True))
    for first_high, rest_high in plans:
        pool = list(hand_cat)
        chosen: List[Card] = []
        ok = True
        for pos, i in enumerate(fillable):
            high = first_high if pos == 0 else rest_high
            comp = _pick_slot(pool, lead.slots[i], cat, high)
            if comp is None:
                ok = False
                break
            chosen.extend(comp)
            for c in comp:
                pool.remove(c)
        if not ok:
            continue
        need = n - len(chosen)
        if need < 0:
            continue
        # 还缺几个对子：领出要求的对子数（对子槽 1 个、拖拉机槽 k 个）
        # vs 手里能组成的对子数，再减去已经出掉的对子。
        from .rules import pair_count
        slot_pairs = 0
        for sl in lead.slots:
            if sl.kind == "pair":
                slot_pairs += 1
            elif sl.kind == "tractor":
                slot_pairs += sl.length
        need_pairs = min(slot_pairs, pair_count(hand_cat + chosen, cat))
        need_pairs -= pair_count(chosen, cat)
        out.append(chosen + _low_fill(pool, need, max(0, need_pairs), cat,
                                      state.level, state.trump_suit))
    return _dedupe(out)[:limit]


def card_rank_key(c: Card) -> float:
    """“小牌优先”的排序键（越小 = 越先打出/垫掉）。

    **2 是常主，不能按点数当小牌**（用户 2026-11-23 指出）：它的实际牌力比 A 还大。
    所以这里把 2 抬到 A(14) 之上；有 level/trump 的地方会直接用 `cat.power_of`
    （真实牌力），那个更准。
    """
    if c.is_joker:
        return 100.0 + float(c.rank)
    if c.rank == 2:
        return 15.0                      # 常主 2：比 A(14) 大
    return float(c.rank)


def legal_moves_fast(state, seat: int, limit: int = 8,
                     follow_variants: int = 2) -> List[List[Card]]:
    """搜索中间节点用的少量候选（不是全枚举，但都是合法构造）。"""
    if state.lead is None:
        return _fast_leads(state, seat, limit)
    return _fast_follows(state, seat, limit, follow_variants)
