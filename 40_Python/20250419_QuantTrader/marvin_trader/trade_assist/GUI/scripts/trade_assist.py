# -*- coding: utf-8 -*-

import logging
import os
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

import gui as ui
from common_config import *


def _parse_decimal(value):
    text = (value or "").strip()
    if text == "":
        return None
    if "," in text:
        text = text.replace(",", "")
    if text.startswith("."):
        text = "0" + text
    try:
        return Decimal(text)
    except InvalidOperation:
        return None


def _format_decimal_var(var, places, minimum=None, label=""):
    raw_text = (var.get() or "").strip()
    if raw_text in {"", "."} and minimum is not None:
        if label:
            logging.info("%s was empty or '.', normalized to minimum %s", label, minimum)
        value = Decimal(str(minimum))
    else:
        value = _parse_decimal(raw_text)
    if value is None:
        return None
    if minimum is not None and value == 0:
        if label:
            logging.info("%s was 0, normalized to minimum %s", label, minimum)
        value = Decimal(str(minimum))
    quant = Decimal("1").scaleb(-places)
    value = value.quantize(quant, rounding=ROUND_HALF_UP)
    var.set(f"{value:.{places}f}")
    return value


def _normalize_numeric_fields():
    _format_decimal_var(ui.ta.stock_buy_price_var, 3, minimum="0.001", label="股票买入价")
    _format_decimal_var(ui.ta.stock_current_price_var, 3, minimum="0.001", label="股票当前价")
    _format_decimal_var(ui.ta.option_strike_price_var, 3, minimum="0.001", label="期权行权价")
    _format_decimal_var(ui.ta.option_buy_price_var, 4, minimum="0.0001", label="期权买入价")
    _format_decimal_var(ui.ta.option_current_price_var, 4, minimum="0.0001", label="期权当前价")
    _format_decimal_var(ui.ta.total_funds_var, 2, minimum=None, label="资金总量")
    _format_decimal_var(ui.ta.trade_loss_var, 2, minimum="0.00", label="交易损耗")


def _update_target_code():
    ui.ta.target_code = dict(TARGET_CODE_MAP).get(ui.ta.target_var.get(), "")


def _thousands_text(value, places):
    text = f"{value:.{places}f}"
    sign = "-" if text.startswith("-") else ""
    if sign:
        text = text[1:]
    integer_part, dot, fraction_part = text.partition(".")
    integer_part = f"{int(integer_part):,}"
    return sign + integer_part + (dot + fraction_part if dot else "")


def _percent_text(value, places):
    text = f"{value:.{places}f}"
    return f"{text}%"


def _estimate_option_price(stock_price):
    """
    简化版线性期权定价模型。
    锚点:
    - 2.166 -> 0.0812
    - 2.328 -> 0.0369
    """
    if stock_price is None:
        return None

    x1 = Decimal("2.166")
    y1 = Decimal("0.0812")
    x2 = Decimal("2.328")
    y2 = Decimal("0.0369")

    if x2 == x1:
        return y1.quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)

    slope = (y2 - y1) / (x2 - x1)
    estimated = y1 + slope * (stock_price - x1)
    if estimated < Decimal("0.0001"):
        estimated = Decimal("0.0001")
    return estimated.quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)


def estimate_option_price_model():
    stock_current = _parse_decimal(ui.ta.stock_current_price_var.get())
    if stock_current in {None, Decimal("0")}:
        logging.info("Cannot estimate option price: stock current price is empty or zero")
        return

    estimated = _estimate_option_price(stock_current)
    if estimated is None:
        logging.info("Cannot estimate option price: model returned empty result")
        return

    ui.ta.option_current_price_var.set(f"{estimated:.4f}")
    logging.info("Estimated option current price: %s", ui.ta.option_current_price_var.get())


def _save_current_state():
    save_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "data"))
    os.makedirs(save_dir, exist_ok=True)
    save_path = os.path.join(save_dir, "last_saved.txt")

    fields = [
        "target_var",
        "direction_var",
        "stock_buy_price_var",
        "stock_current_price_var",
        "stock_shares_var",
        "option_type_var",
        "option_strike_price_var",
        "option_buy_price_var",
        "option_current_price_var",
        "option_moneyness_var",
        "option_contracts_var",
        "total_funds_var",
        "trade_loss_var",
        "actual_usage_var",
        "stock_funds_var",
        "option_cost_var",
        "stock_pnl_var",
        "option_pnl_var",
        "total_pnl_var",
        "return_rate_var",
        "stock_gain_var",
        "option_gain_var",
        "target_code",
    ]

    try:
        with open(save_path, "w", encoding="utf-8") as fh:
            for name in fields:
                if name == "target_code":
                    value = getattr(ui.ta, name, "")
                else:
                    var = getattr(ui.ta, name, None)
                    value = var.get() if var is not None else ""
                fh.write(f"{name}={value}\n")
        logging.info("Saved current GUI state to %s", save_path)
    except Exception as exc:
        logging.info("Failed to save current GUI state to %s: %s", save_path, exc)


def _compute_position():
    stock_buy = _parse_decimal(ui.ta.stock_buy_price_var.get())
    option_buy = _parse_decimal(ui.ta.option_buy_price_var.get())
    total_funds = _parse_decimal(ui.ta.total_funds_var.get())
    trade_loss = _parse_decimal(ui.ta.trade_loss_var.get())
    stock_current = _parse_decimal(ui.ta.stock_current_price_var.get())
    option_current = _parse_decimal(ui.ta.option_current_price_var.get())
    option_strike = _parse_decimal(ui.ta.option_strike_price_var.get())

    if stock_buy in {None, Decimal("0")}:
        stock_buy = Decimal("0.001")
    if option_buy in {None, Decimal("0")}:
        option_buy = Decimal("0.0001")
    if total_funds in {None, Decimal("0")}:
        total_funds = Decimal("0.00")
    if trade_loss in {None, Decimal("0")}:
        trade_loss = Decimal("0.00")
    if stock_current in {None, Decimal("0")}:
        stock_current = stock_buy
    if option_current in {None, Decimal("0")}:
        option_current = option_buy
    if option_strike in {None, Decimal("0")}:
        option_strike = option_buy

    usable_funds = total_funds - trade_loss
    if usable_funds < 0:
        usable_funds = Decimal("0.00")

    if stock_buy <= 0 or option_buy <= 0:
        return

    stock_unit_cost = stock_buy * Decimal("10000")
    option_unit_cost = option_buy * Decimal("10000")
    bundle_cost = stock_unit_cost + option_unit_cost

    if bundle_cost <= 0:
        return

    option_contracts = int(usable_funds // bundle_cost)
    stock_lots = option_contracts

    while option_contracts > 0:
        stock_funds = stock_unit_cost * stock_lots
        option_cost = option_unit_cost * option_contracts
        total_cost = stock_funds + option_cost
        if total_cost <= usable_funds:
            break
        option_contracts -= 1
        stock_lots = option_contracts

    stock_shares = stock_lots * 10000
    stock_funds = stock_unit_cost * stock_lots
    option_cost = option_unit_cost * option_contracts
    actual_usage = stock_funds + option_cost

    stock_pnl = (stock_current - stock_buy) * Decimal("10000") * stock_lots
    option_pnl = (option_current - option_buy) * Decimal("10000") * option_contracts
    total_pnl = stock_pnl + option_pnl
    return_rate = Decimal("0.00")
    if total_funds != 0:
        return_rate = (total_pnl / total_funds) * Decimal("100")

    stock_gain = Decimal("0.00")
    option_gain = Decimal("0.00")
    option_moneyness = Decimal("0.00")
    if stock_buy != 0:
        stock_gain = ((stock_current - stock_buy) / stock_buy) * Decimal("100")
    if option_buy != 0:
        option_gain = ((option_current - option_buy) / option_buy) * Decimal("100")
    if ui.ta.option_type_var.get() == "买入认购期权":
        if option_strike != 0:
            option_moneyness = ((stock_current / option_strike) - Decimal("1")) * Decimal("100")
    else:
        if stock_current != 0:
            option_moneyness = ((option_strike / stock_current) - Decimal("1")) * Decimal("100")

    ui.ta.stock_shares_var.set(str(stock_shares))
    ui.ta.option_contracts_var.set(str(option_contracts))
    ui.ta.total_funds_var.set(_thousands_text(total_funds, 2))
    ui.ta.trade_loss_var.set(_thousands_text(trade_loss, 2))
    ui.ta.stock_funds_var.set(_thousands_text(stock_funds, 2))
    ui.ta.stock_pnl_var.set(_thousands_text(stock_pnl, 2))
    ui.ta.stock_gain_var.set(_percent_text(stock_gain, 2))
    ui.ta.option_cost_var.set(_thousands_text(option_cost, 2))
    ui.ta.option_pnl_var.set(_thousands_text(option_pnl, 2))
    ui.ta.option_gain_var.set(_percent_text(option_gain, 2))
    ui.ta.option_moneyness_var.set(_percent_text(option_moneyness, 2))
    ui.ta.actual_usage_var.set(_thousands_text(actual_usage, 2))
    ui.ta.total_pnl_var.set(_thousands_text(total_pnl, 2))
    ui.ta.return_rate_var.set(_percent_text(return_rate, 2))


def calculate():
    """计算按钮的回调函数。"""
    logging.info("calculate() called")
    _update_target_code()
    _normalize_numeric_fields()
    _compute_position()
    _save_current_state()


def export_report():
    """导出报告按钮的回调函数。"""
    logging.info("export_report() called")
    pass
