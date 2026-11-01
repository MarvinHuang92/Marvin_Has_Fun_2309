# -*- coding: utf-8 -*-
"""月度记事表的日历排版计算（纯逻辑，不涉及 Excel）。"""

import calendar
from datetime import date, timedelta

WEEKDAY_LABELS = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")
DATE_ROWS = 5                # 每个月固定 5 行日期
MONTH_ROWS = DATE_ROWS + 2   # 再加 1 行标题、1 行星期


def first_monday_of_year(year):
    """第 1 周（含 1 月 1 日的那一周）的周一日期。"""
    jan1 = date(year, 1, 1)
    return jan1 - timedelta(days=jan1.weekday())


def week_number(day, first_monday):
    """一年内的周次，从 1 开始，每周从周一起算。"""
    return (day - first_monday).days // 7 + 1


def weeks_in_year(year):
    """这一年用到的最大周次（通常 53，闰年且 1 月 1 日是周日时为 54）。"""
    return week_number(date(year, 12, 31), first_monday_of_year(year))


def build_month(year, month, first_monday):
    """返回 (第一行显示的周次, 5 行 x 7 列的日期网格)。

    网格里是当月的日号（int），空格为 None。放不进 5 行的日期写成
    (日号, 真实周次) 这样的元组，绕回第一行的空格。
    """
    first = date(year, month, 1)
    # 第一行就是 1 号所在的那一周（1 号是周一时也直接从第一行开始写）
    start_week = week_number(first, first_monday)

    rows = [[None] * 7 for _ in range(DATE_ROWS)]
    overflow = []
    for day in range(1, calendar.monthrange(year, month)[1] + 1):
        current = date(year, month, day)
        week = week_number(current, first_monday)
        row = week - start_week
        if 0 <= row < DATE_ROWS:
            rows[row][current.weekday()] = day
        else:
            overflow.append((day, week))

    for item in overflow:
        for column in range(7):
            if rows[0][column] is None:
                rows[0][column] = item
                break
    return start_week, rows


def day_number(entry):
    """网格单元里的日号；空单元格返回 None。"""
    if entry is None:
        return None
    if isinstance(entry, tuple):
        return entry[0]
    return entry


def build_year(year):
    """返回 [(月份, 第一行周次, 日期网格), ...]，共 12 个月。"""
    first_monday = first_monday_of_year(year)
    return [(month,) + build_month(year, month, first_monday)
            for month in range(1, 13)]
