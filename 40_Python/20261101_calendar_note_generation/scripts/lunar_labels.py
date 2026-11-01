# -*- coding: utf-8 -*-
"""日期格子里的第二行：节日 / 节气 / 农历日期。"""

from datetime import date, timedelta

from lunar_python import Solar

# 公历节日：(月, 日)
SOLAR_FESTIVALS = {
    (1, 1): "元旦",
    (3, 8): "妇女节",
    (3, 12): "植树节",
    (5, 1): "劳动节",
    (5, 4): "青年节",
    (6, 1): "儿童节",
    (7, 1): "建党节",
    (8, 1): "建军节",
    (9, 10): "教师节",
    (10, 1): "国庆节",
}

# 农历节日：(月, 日)，闰月不算节日
LUNAR_FESTIVALS = {
    (1, 1): "春节",
    (1, 15): "元宵节",
    (2, 2): "龙抬头",
    (5, 5): "端午节",
    (7, 7): "七夕节",
    (8, 15): "中秋节",
    (9, 9): "重阳节",
    (12, 8): "腊八节",
}


def _lunar_of(day):
    return Solar.fromYmd(day.year, day.month, day.day).getLunar()


def _festival_name(day, lunar, next_lunar):
    """节日优先：公历节日 > 农历节日 > 除夕。"""
    name = SOLAR_FESTIVALS.get((day.month, day.day))
    if name:
        return name
    if lunar.getMonth() > 0:
        name = LUNAR_FESTIVALS.get((lunar.getMonth(), lunar.getDay()))
        if name:
            return name
    if next_lunar.getMonth() == 1 and next_lunar.getDay() == 1:
        return "除夕"
    return None


def day_label(day, lunar=None, next_lunar=None):
    """节日 / 节气 / 农历日期。

    优先级：节日 > 节气 > 农历日期；节日和节气撞在同一天时两个都显示，
    节日在前，中间用空格分隔（比如「重阳节 霜降」）。
    """
    if lunar is None:
        lunar = _lunar_of(day)
    if next_lunar is None:
        next_lunar = _lunar_of(day + timedelta(days=1))

    parts = []
    festival = _festival_name(day, lunar, next_lunar)
    if festival:
        parts.append(festival)
    solar_term = lunar.getJieQi()
    if solar_term:
        parts.append(solar_term)
    if parts:
        return " ".join(parts)
    return lunar.getMonthInChinese() + "月" + lunar.getDayInChinese()


class YearLabels(object):
    """一年的第二行文字，一次算好，后面直接取。"""

    def __init__(self, year):
        first_day = date(year, 1, 1)
        last_day = date(year, 12, 31)
        days = [first_day + timedelta(days=offset)
                for offset in range((last_day - first_day).days + 1)]
        # 多算一天，用来判断最后一天是不是除夕
        lunars = [_lunar_of(day) for day in days] + [_lunar_of(last_day + timedelta(days=1))]
        self._labels = {}
        for index, day in enumerate(days):
            self._labels[day] = day_label(day, lunars[index], lunars[index + 1])

    def get(self, day):
        return self._labels[day]
