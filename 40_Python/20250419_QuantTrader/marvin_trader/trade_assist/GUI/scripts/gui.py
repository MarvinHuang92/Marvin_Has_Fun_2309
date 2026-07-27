# -*- coding: utf-8 -*-

import logging
import os
import tkinter as tk
from tkinter import ttk

from common_config import *
import trade_assist as ta


def _add_labeled_widget(parent, row, label_text, widget, *, label_style=None):
    kwargs = {"sticky": "w", "padx": (12, 8), "pady": 6}
    if label_style:
        ttk.Label(parent, text=label_text, style=label_style).grid(row=row, column=0, **kwargs)
    else:
        ttk.Label(parent, text=label_text).grid(row=row, column=0, **kwargs)
    widget.grid(row=row, column=1, sticky="ew", padx=(8, 12), pady=6)


def _section_header(parent, row, text):
    ttk.Separator(parent, orient="horizontal").grid(
        row=row, column=0, columnspan=2, sticky="ew", padx=12, pady=(14, 6)
    )
    ttk.Label(parent, text=text, style="Section.TLabel").grid(
        row=row + 1, column=0, columnspan=2, sticky="w", padx=12, pady=(0, 6)
    )
    return row + 2


def _build_decimal_validator(root):
    def validate_decimal(text):
        if text == "":
            return True
        if text.startswith("-"):
            return False
        if text.count(".") > 1:
            return False
        if text == ".":
            return True
        if text.startswith("."):
            return text[1:].isdigit()
        return all(ch.isdigit() or ch == "." for ch in text)

    return root.register(validate_decimal), "%P"


def _strip_thousands_format(var):
    text = (var.get() or "").strip()
    if "," in text:
        var.set(text.replace(",", ""))


def _load_last_saved():
    file_path = os.path.abspath(os.path.join(os.path.dirname(__file__), LAST_SAVED_RELATIVE_PATH))
    if not os.path.exists(file_path):
        logging.info("No saved data file found: %s", file_path)
        return

    try:
        values = {}
        with open(file_path, "r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line or "=" not in line:
                    continue
                key, value = line.split("=", 1)
                values[key.strip()] = value.strip()

        for name, value in values.items():
            var = getattr(ta, name, None)
            if var is not None:
                var.set(value)

        logging.info("Loaded saved data from %s", file_path)
    except Exception as exc:
        logging.info("Failed to load saved data from %s: %s", file_path, exc)


def refresh_ui_state():
    if hasattr(ta, "target_var"):
        ta.target_code = dict(TARGET_CODE_MAP).get(ta.target_var.get(), "")

    if not hasattr(ta, "direction_var") or not hasattr(ta, "option_type_var"):
        return

    direction = ta.direction_var.get()
    if direction == "看涨":
        ta.option_type_var.set("买入认沽期权")
    elif direction == "看跌":
        ta.option_type_var.set("买入认购期权")
    else:
        ta.option_type_var.set("")


def _wire_live_refresh():
    watched_vars = [
        "target_var",
        "direction_var",
        "stock_buy_price_var",
        "stock_current_price_var",
        "stock_shares_var",
        "option_strike_price_var",
        "option_buy_price_var",
        "option_current_price_var",
        "option_expiry_var",
        "option_volatility_var",
        "option_rho_var",
        "option_moneyness_var",
        "option_contracts_var",
        "total_funds_var",
        "trade_loss_var",
        "stock_funds_var",
        "option_cost_var",
        "stock_pnl_var",
        "option_pnl_var",
        "total_pnl_var",
        "return_rate_var",
        "stock_gain_var",
        "option_gain_var",
        "actual_usage_var",
    ]

    for var_name in watched_vars:
        var = getattr(ta, var_name, None)
        if var is not None:
            var.trace_add("write", lambda *_: refresh_ui_state())


def _build_option_insurance_tab(parent, decimal_vcmd):
    parent.columnconfigure(0, weight=1)
    parent.columnconfigure(1, weight=1)
    parent.rowconfigure(0, weight=1)

    style = ttk.Style(parent)
    style.configure("Section.TLabel", font=("Microsoft YaHei UI", 10, "bold"))

    left = ttk.Frame(parent)
    right = ttk.Frame(parent)
    left.grid(row=0, column=0, sticky="nsew", padx=(0, 8))
    right.grid(row=0, column=1, sticky="nsew", padx=(8, 0))
    left.columnconfigure(0, weight=0)
    left.columnconfigure(1, weight=1)
    right.columnconfigure(0, weight=0)
    right.columnconfigure(1, weight=1)

    lrow = 0
    rrow = 0

    ta.target_var = tk.StringVar(value=TARGET_CODE_MAP[0][0])
    target_combo = ttk.Combobox(left, textvariable=ta.target_var, values=[item[0] for item in TARGET_CODE_MAP], state="readonly")
    _add_labeled_widget(left, lrow, "标的", target_combo)
    lrow += 1

    lrow = _section_header(left, lrow, "股票账户")

    ta.direction_var = tk.StringVar(value="看涨")
    direction_combo = ttk.Combobox(left, textvariable=ta.direction_var, values=["看涨", "看跌"], state="readonly")
    _add_labeled_widget(left, lrow, "方向", direction_combo)
    lrow += 1

    ta.stock_buy_price_var = tk.StringVar()
    ta.stock_current_price_var = tk.StringVar()
    ta.stock_gain_var = tk.StringVar()
    ta.stock_shares_var = tk.StringVar()
    stock_buy_entry = ttk.Entry(left, textvariable=ta.stock_buy_price_var, validate="key", validatecommand=decimal_vcmd)
    stock_current_entry = ttk.Entry(left, textvariable=ta.stock_current_price_var, validate="key", validatecommand=decimal_vcmd)
    _add_labeled_widget(left, lrow, "买入价", stock_buy_entry)
    lrow += 1
    _add_labeled_widget(left, lrow, "当前价", stock_current_entry)
    lrow += 1
    _add_labeled_widget(left, lrow, "涨幅", ttk.Entry(left, textvariable=ta.stock_gain_var, state="readonly"))
    lrow += 1
    _add_labeled_widget(left, lrow, "份数", ttk.Entry(left, textvariable=ta.stock_shares_var, state="readonly"))
    lrow += 1

    lrow = _section_header(left, lrow, "期权账户")

    ta.option_type_var = tk.StringVar(value="")
    _add_labeled_widget(left, lrow, "类型", ttk.Entry(left, textvariable=ta.option_type_var, state="readonly"))
    lrow += 1

    ta.option_strike_price_var = tk.StringVar()
    ta.option_buy_price_var = tk.StringVar()
    ta.option_current_price_var = tk.StringVar()
    ta.option_expiry_var = tk.StringVar()
    ta.option_volatility_var = tk.StringVar()
    ta.option_rho_var = tk.StringVar()
    ta.option_gain_var = tk.StringVar()
    ta.option_moneyness_var = tk.StringVar()
    ta.option_contracts_var = tk.StringVar()
    option_strike_entry = ttk.Entry(left, textvariable=ta.option_strike_price_var, validate="key", validatecommand=decimal_vcmd)
    option_buy_entry = ttk.Entry(left, textvariable=ta.option_buy_price_var, validate="key", validatecommand=decimal_vcmd)
    option_current_entry = ttk.Entry(left, textvariable=ta.option_current_price_var, validate="key", validatecommand=decimal_vcmd)
    option_time_entry = ttk.Entry(left, textvariable=ta.option_expiry_var, validate="key", validatecommand=decimal_vcmd)
    option_volatility_entry = ttk.Entry(left, textvariable=ta.option_volatility_var, validate="key", validatecommand=decimal_vcmd)
    option_rho_entry = ttk.Entry(left, textvariable=ta.option_rho_var, validate="key", validatecommand=decimal_vcmd)
    _add_labeled_widget(left, lrow, "行权价", option_strike_entry)
    lrow += 1
    _add_labeled_widget(left, lrow, "虚实度", ttk.Entry(left, textvariable=ta.option_moneyness_var, state="readonly"))
    lrow += 1
    _add_labeled_widget(left, lrow, "买入价", option_buy_entry)
    lrow += 1
    _add_labeled_widget(left, lrow, "当前价", option_current_entry)
    lrow += 1
    _add_labeled_widget(left, lrow, "到期日", option_time_entry)
    lrow += 1
    _add_labeled_widget(left, lrow, "波动率", option_volatility_entry)
    lrow += 1
    _add_labeled_widget(left, lrow, "RHO", option_rho_entry)
    lrow += 1
    _add_labeled_widget(left, lrow, "涨幅", ttk.Entry(left, textvariable=ta.option_gain_var, state="readonly"))
    lrow += 1
    _add_labeled_widget(left, lrow, "张数", ttk.Entry(left, textvariable=ta.option_contracts_var, state="readonly"))
    lrow += 1

    model_button = ttk.Button(left, text="期权定价模型估算", command=ta.estimate_option_price_model)
    model_button.grid(row=lrow, column=0, columnspan=2, sticky="ew", padx=12, pady=(12, 6))

    # empty row for spacing
    spacer = ttk.Frame(right)
    spacer.grid(row=rrow, column=0, columnspan=2, sticky="ew", pady=17)
    rrow += 1

    rrow = _section_header(right, rrow, "资金")

    ta.total_funds_var = tk.StringVar()
    ta.trade_loss_var = tk.StringVar(value="1000.00")
    ta.actual_usage_var = tk.StringVar()
    ta.stock_funds_var = tk.StringVar()
    ta.option_cost_var = tk.StringVar()
    ta.stock_pnl_var = tk.StringVar()
    ta.option_pnl_var = tk.StringVar()
    ta.total_pnl_var = tk.StringVar()
    ta.return_rate_var = tk.StringVar()

    total_funds_entry = ttk.Entry(right, textvariable=ta.total_funds_var, validate="key", validatecommand=decimal_vcmd)
    trade_loss_entry = ttk.Entry(right, textvariable=ta.trade_loss_var, validate="key", validatecommand=decimal_vcmd)
    actual_usage_entry = ttk.Entry(right, textvariable=ta.actual_usage_var, state="readonly")
    total_funds_entry.bind("<FocusIn>", lambda _e: _strip_thousands_format(ta.total_funds_var))
    trade_loss_entry.bind("<FocusIn>", lambda _e: _strip_thousands_format(ta.trade_loss_var))
    _add_labeled_widget(right, rrow, "资金总量", total_funds_entry)
    rrow += 1
    _add_labeled_widget(right, rrow, "交易损耗", trade_loss_entry)
    rrow += 1
    _add_labeled_widget(right, rrow, "实际使用", actual_usage_entry)
    rrow += 1
    _add_labeled_widget(right, rrow, "持股资金", ttk.Entry(right, textvariable=ta.stock_funds_var, state="readonly"))
    rrow += 1
    _add_labeled_widget(right, rrow, "期权成本", ttk.Entry(right, textvariable=ta.option_cost_var, state="readonly"))
    rrow += 1

    rrow = _section_header(right, rrow, "收益")
    _add_labeled_widget(right, rrow, "股票收益", ttk.Entry(right, textvariable=ta.stock_pnl_var, state="readonly"))
    rrow += 1
    _add_labeled_widget(right, rrow, "期权收益", ttk.Entry(right, textvariable=ta.option_pnl_var, state="readonly"))
    rrow += 1
    _add_labeled_widget(right, rrow, "总收益", ttk.Entry(right, textvariable=ta.total_pnl_var, state="readonly"))
    rrow += 1
    _add_labeled_widget(right, rrow, "收益率", ttk.Entry(right, textvariable=ta.return_rate_var, state="readonly"))

    _wire_live_refresh()
    refresh_ui_state()
    _load_last_saved()


def create_main_window():
    root = tk.Tk()
    root.title(GUI_TITLE)
    root.geometry(f"{WINDOW_WIDTH}x{WINDOW_HEIGHT}")

    decimal_vcmd = _build_decimal_validator(root)

    notebook = ttk.Notebook(root)
    notebook.pack(fill="both", expand=True, padx=10, pady=10)

    for tab_name in TAB_NAMES:
        frame = ttk.Frame(notebook)
        notebook.add(frame, text=tab_name)
        if tab_name == "期权保险":
            _build_option_insurance_tab(frame, decimal_vcmd)
        else:
            placeholder = ttk.Label(frame, text=f"{tab_name} 页面内容", anchor="center")
            placeholder.pack(expand=True, fill="both", padx=20, pady=20)

    button_frame = ttk.Frame(root)
    button_frame.pack(side="bottom", fill="x", padx=10, pady=10)

    calculate_button = ttk.Button(button_frame, text=BUTTON_CALCULATE_TEXT, command=ta.calculate)
    export_button = ttk.Button(button_frame, text=BUTTON_EXPORT_TEXT, command=ta.export_report)

    calculate_button.pack(side="left", expand=True, fill="x", padx=(0, 5))
    export_button.pack(side="right", expand=True, fill="x", padx=(5, 0))

    return root


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
    logging.info("Launching Marvin Trade Assist GUI")
    main_window = create_main_window()
    main_window.mainloop()
