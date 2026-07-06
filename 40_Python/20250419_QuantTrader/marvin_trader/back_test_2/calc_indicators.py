"""
Demo script for calculating market indicators from simulated price data.
"""


# 说明：这个脚本接收行情数据输入（收盘价，当日最高价，最低价）然后计算KDJ和MACD指标
# 如果下载的行情数据自带这些指标，可以直接用，如果不带，这个脚本帮忙计算
# 后续可以补充更多指标计算函数

from __future__ import annotations

import random
from dataclasses import dataclass
from typing import List

# KDJ计算使用的默认参数，可以修改
ParaKDJ_N = 9
ParaKDJ_K_INIT = 50.0
ParaKDJ_D_INIT = 50.0

# MACD计算使用的默认参数，可以修改
ParaMACD_FAST = 12
ParaMACD_SLOW = 26
ParaMACD_SIGNAL = 9

# 是否打印计算结果
ParaPrintResult = True

# 装饰器的作用是把下面这个类自动变成“数据容器类”。
# 具体来说，它会帮你自动生成这些常用方法：
# __init__：自动生成构造函数
# __repr__：打印对象时更清晰
# __eq__：支持按字段比较对象
# 用户不需要手动编写这些方法，减少了样板代码，提高了代码可读性和可维护性。
@dataclass
class KDJRecord:
    day: int
    close: float
    high: float
    low: float
    rsv: float
    k: float
    d: float
    j: float


@dataclass
class MACDRecord:
    day: int
    close: float
    ema_fast: float
    ema_slow: float
    dif: float
    dea: float
    macd: float


# 生成模拟收盘价数据
def generate_close_prices(days: int = 30, seed: int = 42) -> List[float]:
    random.seed(seed)
    prices = [100.0]
    for _ in range(days - 1):
        drift = random.uniform(-2.5, 2.5)
        prices.append(round(max(1.0, prices[-1] + drift), 2))
    return prices


# 生成模拟的最高价和最低价数据
def build_synthetic_ohlc(close_prices: List[float], seed: int = 42):
    random.seed(seed + 1)
    highs = []
    lows = []
    for close_price in close_prices:
        high_offset = random.uniform(0.2, 3.0)
        low_offset = random.uniform(0.2, 3.0)
        highs.append(round(close_price + high_offset, 2))
        lows.append(round(max(0.01, close_price - low_offset), 2))
    return highs, lows


def calculate_kdj(close_prices: List[float], highs: List[float], lows: List[float]) -> List[KDJRecord]:
    """Calculate KDJ:
    The classic KDJ formula uses high, low, and close prices. This script first
    generates 30 days of simulated close prices, then derives matching synthetic
    high/low prices around each close so KDJ can be calculated day by day.
    """

    k_value = ParaKDJ_K_INIT
    d_value = ParaKDJ_D_INIT
    records: List[KDJRecord] = []

    for index, close_price in enumerate(close_prices):
        start = max(0, index - ParaKDJ_N + 1)
        recent_high = max(highs[start : index + 1])
        recent_low = min(lows[start : index + 1])

        if recent_high == recent_low:
            rsv = 50.0
        else:
            rsv = (close_price - recent_low) / (recent_high - recent_low) * 100

        k_value = (2 / 3) * k_value + (1 / 3) * rsv
        d_value = (2 / 3) * d_value + (1 / 3) * k_value
        j_value = 3 * k_value - 2 * d_value

        records.append(
            KDJRecord(
                day=index + 1,
                close=close_price,
                high=recent_high,
                low=recent_low,
                rsv=round(rsv, 2),
                k=round(k_value, 2),
                d=round(d_value, 2),
                j=round(j_value, 2),
            )
        )

    return records


def calculate_macd(close_prices: List[float]) -> List[MACDRecord]:
    """Calculate MACD values for a list of close prices.

    The function uses the common parameters 12, 26, and 9 by default:
    DIF = EMA(12) - EMA(26)
    DEA = EMA(9) of DIF
    MACD = 2 * (DIF - DEA)
    """

    if not close_prices:
        return []

    alpha_fast = 2 / (ParaMACD_FAST + 1)
    alpha_slow = 2 / (ParaMACD_SLOW + 1)
    alpha_signal = 2 / (ParaMACD_SIGNAL + 1)

    ema_fast = close_prices[0]
    ema_slow = close_prices[0]
    dif = 0.0
    dea = 0.0
    records: List[MACDRecord] = []

    for index, close_price in enumerate(close_prices):
        if index == 0:
            ema_fast = close_price
            ema_slow = close_price
        else:
            ema_fast = alpha_fast * close_price + (1 - alpha_fast) * ema_fast
            ema_slow = alpha_slow * close_price + (1 - alpha_slow) * ema_slow

        dif = ema_fast - ema_slow
        dea = alpha_signal * dif + (1 - alpha_signal) * dea
        macd = 2 * (dif - dea)

        records.append(
            MACDRecord(
                day=index + 1,
                close=close_price,
                ema_fast=round(ema_fast, 2),
                ema_slow=round(ema_slow, 2),
                dif=round(dif, 2),
                dea=round(dea, 2),
                macd=round(macd, 2),
            )
        )

    return records


def main() -> None:
    close_prices = generate_close_prices(days=30, seed=42)
    highs, lows = build_synthetic_ohlc(close_prices, seed=42)
    kdj_records = calculate_kdj(close_prices, highs, lows)
    macd_records = calculate_macd(close_prices)

    if not ParaPrintResult:
        return

    print("Day  Close    High     Low      RSV      K       D       J")
    print("-" * 68)
    for record in kdj_records:
        print(
            f"{record.day:>3}  "
            f"{record.close:>6.2f}  "
            f"{record.high:>7.2f}  "
            f"{record.low:>7.2f}  "
            f"{record.rsv:>7.2f}  "
            f"{record.k:>7.2f}  "
            f"{record.d:>7.2f}  "
            f"{record.j:>7.2f}"
        )

    print()
    print("Day  Close    EMA12    EMA26     DIF      DEA     MACD")
    print("-" * 60)
    for record in macd_records:
        print(
            f"{record.day:>3}  "
            f"{record.close:>6.2f}  "
            f"{record.ema_fast:>7.2f}  "
            f"{record.ema_slow:>7.2f}  "
            f"{record.dif:>7.2f}  "
            f"{record.dea:>7.2f}  "
            f"{record.macd:>7.2f}"
        )


if __name__ == "__main__":
    main()
