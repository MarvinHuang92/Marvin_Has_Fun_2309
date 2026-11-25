# -*- coding: utf-8 -*-
"""名次/距离/最快圈的计算与 4 行显示选择（纯数学）。"""


class Standing(object):
    __slots__ = ("rank", "name", "distance", "best_lap", "is_player", "gap_m")

    def __init__(self, name, distance, best_lap, is_player=False):
        self.name = str(name)
        self.distance = float(distance)
        self.best_lap = best_lap
        self.is_player = bool(is_player)
        self.rank = 0
        self.gap_m = 0.0


def ordinal(rank):
    if 10 <= rank % 100 <= 20:
        suffix = "th"
    else:
        suffix = {1: "st", 2: "nd", 3: "rd"}.get(rank % 10, "th")
    return "%d%s" % (rank, suffix)


def build_standings(player_distance, player_best, ai_entries, max_rows=4):
    """``ai_entries``: [(name, distance, best_lap), ...]。

    返回 ``(visible_rows, player_row)``；每行已带 rank/gap_m。
    gap_m 是相对玩家的距离（正=在玩家前方），玩家自己为 0。
    """
    rows = [Standing("Player", player_distance, player_best, True)]
    for name, distance, best in ai_entries:
        rows.append(Standing(name, distance, best, False))
    rows.sort(key=lambda item: (-item.distance, item.name))
    player_row = None
    for index, row in enumerate(rows):
        row.rank = index + 1
        if row.is_player:
            player_row = row
    if player_row is None:
        return [], None
    for row in rows:
        row.gap_m = row.distance - player_row.distance
    if len(rows) <= max_rows:
        return rows, player_row
    player_index = rows.index(player_row)
    if player_index < 3:
        indices = list(range(max_rows))
    elif player_index == len(rows) - 1:
        indices = [0] + list(range(player_index - 2, player_index + 1))
    else:
        indices = [0] + list(range(player_index - 1, player_index + 2))
    visible = []
    for index in indices:
        if index not in [item.rank - 1 for item in visible]:
            visible.append(rows[index])
    return visible, player_row


def format_gap(row, player_row, lap_length_m=None):
    """显示相对玩家的差距。

    符号约定：领先 AI 为负（-100m / -1LAP），落后为正（+40m / +1LAP）；
    玩家自己为 "--"。差距达到一圈后改为 LAP 显示。
    """
    if row is player_row:
        return "--"
    gap = row.gap_m
    lap_length = float(lap_length_m or 0.0)
    if lap_length > 1.0 and abs(gap) >= lap_length:
        laps = int(abs(gap) // lap_length)
        if gap > 0.0:  # AI 领先玩家
            return "-%dLAP" % laps
        return "+%dLAP" % laps
    if abs(gap) < 0.5:
        return "+0m"
    if gap > 0.0:  # AI 领先玩家 -> 负号
        return "-%dm" % int(round(gap))
    return "+%dm" % int(round(-gap))
