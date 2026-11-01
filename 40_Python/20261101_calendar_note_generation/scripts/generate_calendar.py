# -*- coding: utf-8 -*-
"""生成《月度记事表_年份.xlsx》：以 template 目录里的表格为模板，填入某一年的日历。"""

import os
import subprocess
import sys
from datetime import date
from pathlib import Path

from openpyxl import load_workbook
from openpyxl.styles import Alignment

import calendar_layout as layout
import lunar_labels

TOOL_ROOT = Path(__file__).resolve().parent.parent
OUTPUT_DIR = TOOL_ROOT / "output"
TEMPLATE_DIR = TOOL_ROOT / "template"
TEMPLATE_NAME = "月度记事表_2026.xlsx"

MIN_YEAR = 1970
MAX_YEAR = 2100

TITLE_TEMPLATE = "%d 年 %d 月    事件记录"

# 日期格是「日号 农历」，比模板原来的纯日号长，允许换行防止长文本被隔壁格子截断
ALIGN_DAY = Alignment(horizontal="left", vertical="top", wrap_text=True)

# 打印设置：A4 横向 + 模板第二页记录的自定义页边距（单位 cm）
PAPER_SIZE_A4 = 9
PAGE_MARGINS_CM = (
    ("header", 0.8),
    ("footer", 0.3),
    ("top", 2.4),
    ("bottom", 0.9),
    ("left", 0.6),
    ("right", 0.6),
)
# 用这套页边距后，一页正好放得下一个月（7 行），所以保持 100% 不缩放
PRINT_SCALE = 100


def template_path():
    preferred = TEMPLATE_DIR / TEMPLATE_NAME
    if preferred.exists():
        return preferred
    candidates = sorted(TEMPLATE_DIR.glob("*.xlsx"))
    if candidates:
        return candidates[0]
    raise FileNotFoundError("template 目录里找不到模板 xlsx：%s" % TEMPLATE_DIR)


def _day_text(entry, year, month, labels):
    """日期格的文字：`日号 农历`；绕回第一行的日期末尾再加 ` (w周次)`。"""
    if entry is None:
        return None
    label = labels.get(date(year, month, layout.day_number(entry)))
    if isinstance(entry, tuple):
        return "%d %s (w%d)" % (entry[0], label, entry[1])
    return "%d %s" % (entry, label)


def _write_month(ws, first_row, year, month, start_week, grid, labels):
    title_row = first_row
    weekday_row = first_row + 1

    ws.cell(row=title_row, column=2).value = TITLE_TEMPLATE % (year, month)
    for index, label in enumerate(layout.WEEKDAY_LABELS):
        ws.cell(row=weekday_row, column=2 + index).value = label

    for offset, entries in enumerate(grid):
        row = weekday_row + 1 + offset
        ws.cell(row=row, column=1).value = "Week\n%02d" % (start_week + offset)
        for index, entry in enumerate(entries):
            cell = ws.cell(row=row, column=2 + index)
            cell.value = _day_text(entry, year, month, labels)
            cell.alignment = ALIGN_DAY


def _apply_page_setup(ws):
    ws.page_setup.paperSize = PAPER_SIZE_A4
    ws.page_setup.orientation = "landscape"
    ws.page_setup.scale = PRINT_SCALE
    margins = ws.page_margins
    for name, centimeters in PAGE_MARGINS_CM:
        setattr(margins, name, centimeters / 2.54)


def build_workbook(year):
    workbook = load_workbook(str(template_path()))
    calendar_sheet = workbook.worksheets[0]

    labels = lunar_labels.YearLabels(year)
    for index, (month, start_week, grid) in enumerate(layout.build_year(year)):
        _write_month(calendar_sheet, 1 + index * layout.MONTH_ROWS,
                     year, month, start_week, grid, labels)
    _apply_page_setup(calendar_sheet)
    return workbook


def output_path(year):
    return OUTPUT_DIR / ("月度记事表_%d.xlsx" % year)


def _ask_year():
    prompt = "请输入年份（%d-%d，直接回车退出）： " % (MIN_YEAR, MAX_YEAR)
    while True:
        try:
            answer = input(prompt).strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return None
        if not answer:
            return None
        if not answer.isdigit():
            print("  请只输入数字。")
            continue
        year = int(answer)
        if not MIN_YEAR <= year <= MAX_YEAR:
            print("  年份需要在 %d 到 %d 之间。" % (MIN_YEAR, MAX_YEAR))
            continue
        return year


def _ask_yes_no(prompt, default):
    hint = "Y/n" if default else "y/N"
    try:
        answer = input("%s（%s）： " % (prompt, hint)).strip().lower()
    except (EOFError, KeyboardInterrupt):
        print()
        return False
    if not answer:
        return default
    return answer in ("y", "yes", "是", "好", "1")


def _open_file(path):
    try:
        if hasattr(os, "startfile"):
            os.startfile(str(path))
        elif sys.platform == "darwin":
            subprocess.Popen(["open", str(path)])
        else:
            subprocess.Popen(["xdg-open", str(path)])
    except Exception as exc:                     # noqa: BLE001 - 只是提示，不中断
        print("  无法自动打开（%s），请手动打开上面的路径。" % exc)


def _quit():
    try:
        input("按回车键结束 ...")
    except (EOFError, KeyboardInterrupt):
        print()


def main():
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(errors="replace")
        except AttributeError:
            pass

    print("=" * 48)
    print("      月度记事表（纸质年度规划表）生成器")
    print("=" * 48)
    print("输入年份后生成当年的日历表格，打印出来即可手写安排全年。")
    print()

    year = _ask_year()
    if year is None:
        print("已退出。")
        return 0

    path = output_path(year)
    if path.exists() and not _ask_yes_no("文件已存在，要覆盖吗", default=False):
        print("已取消，没有改动任何文件。")
        return 0

    try:
        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        build_workbook(year).save(str(path))
    except PermissionError:
        print()
        print("[出错] 无法写入文件，它可能正在 Excel 里打开着：%s" % path)
        print("       请先关闭这个文件再试一次。")
        return 1
    except Exception as exc:                     # noqa: BLE001 - 控制台里给出可读的提示
        print()
        print("[出错] 生成失败：%s" % exc)
        return 1

    print()
    print("已生成：%s" % path)
    print("  12 个月 x 7 行（1 行标题 + 1 行星期 + 5 行日期），全年共 %d 周。"
          % layout.weeks_in_year(year))
    print("  每个日期格第二行是农历，节日 / 节气会顶替农历。")
    print()
    if _ask_yes_no("现在打开这个文件吗", default=True):
        _open_file(path)
    _quit()
    return 0


if __name__ == "__main__":
    sys.exit(main())