"""准备 simple backtest 使用的外部日收益和区间复合收益。"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd

from src.backtest.prices import benchmark_prices
from src.data.market_data import MarketData


@dataclass(frozen=True)
class ReturnContext:
    """保存按市场日历对齐的股票累计收益和基准点位。"""

    calendar: pd.DatetimeIndex
    stock_codes: pd.Index
    cumulative_log_returns: np.ndarray
    cumulative_missing_counts: np.ndarray
    benchmark_close: np.ndarray


def prepare_return_context(
    return_panel: pd.DataFrame,
    market_data: MarketData,
    settings: Mapping[str, Any],
) -> ReturnContext:
    """把 t-1 至 t 的日收益整理为可快速查询任意事件区间的累计量。"""
    calendar = market_data.calendar
    stock_codes = market_data.membership.columns
    aligned_returns = return_panel.reindex(
        index=calendar,
        columns=stock_codes,
    ).to_numpy(dtype=float)
    valid_returns = np.isfinite(aligned_returns)
    cumulative_log_returns = np.cumsum(
        np.where(valid_returns, np.log1p(aligned_returns), 0.0),
        axis=0,
    )
    cumulative_missing_counts = np.cumsum(~valid_returns, axis=0)
    _, benchmark_close = benchmark_prices(market_data, settings)
    return ReturnContext(
        calendar=calendar,
        stock_codes=stock_codes,
        cumulative_log_returns=cumulative_log_returns,
        cumulative_missing_counts=cumulative_missing_counts,
        benchmark_close=benchmark_close,
    )


def stock_period_gross_returns(
    context: ReturnContext,
    start_position: int,
    end_position: int,
    required_stocks: np.ndarray,
) -> np.ndarray:
    """复合 start 收盘之后至 end 收盘的逐股收益并检查当前持仓。"""
    interval_log_returns = (
        context.cumulative_log_returns[end_position]
        - context.cumulative_log_returns[start_position]
    )
    interval_missing_counts = (
        context.cumulative_missing_counts[end_position]
        - context.cumulative_missing_counts[start_position]
    )
    missing_required_returns = required_stocks & (interval_missing_counts > 0)
    if missing_required_returns.any():
        missing_codes = context.stock_codes[missing_required_returns].tolist()[:8]
        event_date = context.calendar[end_position]
        raise ValueError(f"{event_date.date()} 缺少外部日收益: {missing_codes}")
    return np.exp(interval_log_returns)


def benchmark_period_gross_return(
    context: ReturnContext,
    start_position: int,
    end_position: int,
) -> float:
    """计算与股票外部收益区间一致的基准复合收益。"""
    start_value = context.benchmark_close[start_position]
    end_value = context.benchmark_close[end_position]
    if not np.isfinite(start_value) or not np.isfinite(end_value):
        event_date = context.calendar[end_position]
        raise ValueError(f"{event_date.date()} 缺少基准收盘价")
    return float(end_value / start_value)
