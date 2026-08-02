# -*- coding: utf-8 -*-

import logging
import os
import tkinter as tk
from tkinter import ttk

from common_config import *
import img_gen as ig


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


# def refresh_ui_state():
#     if hasattr(ta, "target_var"):
#         ig.target_code = dict(TARGET_CODE_MAP).get(ig.target_var.get(), "")

#     if not hasattr(ta, "direction_var") or not hasattr(ta, "option_type_var"):
#         return

#     direction = ig.direction_var.get()
#     if direction == "看涨":
#         ig.option_type_var.set("买入认沽期权")
#     elif direction == "看跌":
#         ig.option_type_var.set("买入认购期权")
#     else:
#         ig.option_type_var.set("")


# def _wire_live_refresh():
#     watched_vars = [
#         "target_var",
#         "direction_var",
#         "stock_buy_price_var",
#         "stock_current_price_var",
#         "stock_shares_var",
#         "option_strike_price_var",
#         "option_buy_price_var",
#         "option_current_price_var",
#         "option_expiry_var",
#         "option_volatility_var",
#         "option_rho_var",
#         "option_moneyness_var",
#         "option_contracts_var",
#         "total_funds_var",
#         "trade_loss_var",
#         "stock_funds_var",
#         "option_cost_var",
#         "stock_pnl_var",
#         "option_pnl_var",
#         "total_pnl_var",
#         "return_rate_var",
#         "stock_gain_var",
#         "option_gain_var",
#         "actual_usage_var",
#     ]

#     for var_name in watched_vars:
#         var = getattr(ta, var_name, None)
#         if var is not None:
#             var.trace_add("write", lambda *_: refresh_ui_state())


def _build_daily_reward_tab(parent):
    parent.columnconfigure(0, weight=1)
    parent.columnconfigure(1, weight=1)
    parent.rowconfigure(0, weight=1)

    style = ttk.Style(parent)
    style.configure("Section.TLabel", font=("Microsoft YaHei UI", 10, "bold"))

    # to be implemented: add widgets

    # _wire_live_refresh()
    # refresh_ui_state()
    _load_last_saved()


def create_main_window():
    root = tk.Tk()
    root.title(GUI_TITLE)
    root.geometry(f"{WINDOW_WIDTH}x{WINDOW_HEIGHT}")

    notebook = ttk.Notebook(root)
    notebook.pack(fill="both", expand=True, padx=10, pady=10)

    for tab_name in TAB_NAMES:
        frame = ttk.Frame(notebook)
        notebook.add(frame, text=tab_name)
        if tab_name == "日收益":
            _build_daily_reward_tab(frame)
        else:
            placeholder = ttk.Label(frame, text=f"{tab_name} 页面内容", anchor="center")
            placeholder.pack(expand=True, fill="both", padx=20, pady=20)

    button_frame = ttk.Frame(root)
    button_frame.pack(side="bottom", fill="x", padx=10, pady=10)

    extract_button = ttk.Button(button_frame, text=BUTTON_EXTRACT_TEXT, command=ig.extract_data)
    calculate_button = ttk.Button(button_frame, text=BUTTON_CALCULATE_TEXT, command=ig.calculate_new_data)
    gen_image_button = ttk.Button(button_frame, text=BUTTON_GEN_IMAGE_TEXT, command=ig.generate_image)
    export_button = ttk.Button(button_frame, text=BUTTON_EXPORT_TEXT, command=ig.export_report)

    extract_button.pack(side="left", expand=True, fill="x", padx=(0, 5))
    calculate_button.pack(side="left", expand=True, fill="x", padx=(5, 5))
    gen_image_button.pack(side="left", expand=True, fill="x", padx=(5, 5))
    export_button.pack(side="right", expand=True, fill="x", padx=(5, 0))

    return root


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
    logging.info("Launching Marvin Trade Assist GUI")
    main_window = create_main_window()
    main_window.mainloop()
