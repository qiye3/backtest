"""准备两套回测共享的股票参考价格、补价信息和基准价格。"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Literal

import numpy as np
import pandas as pd

from src.data.market_data import MarketData


@dataclass(frozen=True)
class PriceContext:
    """保存按统一日历和股票列排列的只读价格及成交限制数组。"""

    calendar: pd.DatetimeIndex
    stock_codes: pd.Index
    trade_prices: np.ndarray
    trade_price_filled: np.ndarray
    trade_price_positions: np.ndarray
    close_prices: np.ndarray
    close_price_filled: np.ndarray
    close_price_positions: np.ndarray
    raw_open_prices: np.ndarray | None
    raw_close_prices: np.ndarray | None
    trade_status: np.ndarray | None
    limit_up: np.ndarray | None
    limit_down: np.ndarray | None
    benchmark_open: np.ndarray
    benchmark_close: np.ndarray


def build_reference_prices(
    raw_prices: np.ndarray,
    adjusted_close: np.ndarray,
    missing_price_policy: str,
    max_stale_days: int | None,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """
    构造指定时点的参考价格、补价标记和真实价格日期位置。

    ``previous_close`` 严格读取当前交易日以前最后一个正复权收盘；
    当天收盘即使已经存在，也不能用于补当天缺失的开盘或收盘参考价。
    """
    valid_raw_prices = np.isfinite(raw_prices) & (raw_prices > 0)
    valid_close_prices = np.isfinite(adjusted_close) & (adjusted_close > 0)
    date_positions = np.arange(raw_prices.shape[0], dtype=np.int32)

    last_close_positions = np.maximum.accumulate(
        np.where(valid_close_prices, date_positions[:, None], -1),
        axis=0,
    )
    previous_close_positions = np.full_like(last_close_positions, -1)
    previous_close_positions[1:] = last_close_positions[:-1]

    reference_prices = np.where(valid_raw_prices, raw_prices, np.nan)
    price_positions = np.where(
        valid_raw_prices,
        date_positions[:, None],
        -1,
    ).astype(np.int32)
    price_filled = np.zeros_like(valid_raw_prices)
    if missing_price_policy == "previous_close":
        fill_prices = ~valid_raw_prices & (previous_close_positions >= 0)
        stale_days = date_positions[:, None] - previous_close_positions
        if max_stale_days is not None:
            fill_prices &= stale_days <= max_stale_days

        safe_positions = np.maximum(previous_close_positions, 0)
        previous_close_values = np.take_along_axis(
            adjusted_close,
            safe_positions,
            axis=0,
        )
        reference_prices[fill_prices] = previous_close_values[fill_prices]
        price_positions[fill_prices] = previous_close_positions[fill_prices]
        price_filled[fill_prices] = True

    return reference_prices, price_filled, price_positions


def prepare_price_context(
    market_data: MarketData,
    settings: Mapping[str, Any],
) -> PriceContext:
    """
    为一批分组组合准备一次股票行情和基准价格。

    股票交易与估值使用复权价格；原始价格、状态和涨跌停仅在
    account 的 ``tradability`` 模式用于判断能否成交。
    """
    calendar = market_data.calendar
    stock_codes = market_data.membership.columns
    adjusted_close = _stock_field(
        market_data,
        "S_DQ_ADJCLOSE",
        calendar,
        stock_codes,
        dtype=float,
    )
    trade_kind = settings["trade_price"]
    if trade_kind not in {"open", "close"}:
        raise ValueError(f"未知 trade_price: {trade_kind}")
    execution_policy = settings["execution"]["policy"]
    if execution_policy not in {"ideal", "tradability"}:
        raise ValueError(f"未知 execution.policy: {execution_policy}")
    if trade_kind == "open":
        adjusted_trade = _stock_field(
            market_data,
            "S_DQ_ADJOPEN",
            calendar,
            stock_codes,
            dtype=float,
        )
    else:
        adjusted_trade = adjusted_close
    trade_prices, trade_price_filled, trade_price_positions = (
        build_reference_prices(
            raw_prices=adjusted_trade,
            adjusted_close=adjusted_close,
            missing_price_policy=settings["missing_price_policy"],
            max_stale_days=settings["max_stale_days"],
        )
    )
    close_prices, close_price_filled, close_price_positions = (
        build_reference_prices(
            raw_prices=adjusted_close,
            adjusted_close=adjusted_close,
            missing_price_policy=settings["missing_price_policy"],
            max_stale_days=settings["max_stale_days"],
        )
    )

    raw_open_prices = None
    raw_close_prices = None
    trade_status = None
    limit_up = None
    limit_down = None
    if execution_policy == "tradability":
        if trade_kind == "open":
            raw_open_prices = _stock_field(
                market_data,
                "S_DQ_OPEN",
                calendar,
                stock_codes,
                dtype=float,
            )
        if trade_kind == "close" or settings["liquidate_at_end"]:
            raw_close_prices = _stock_field(
                market_data,
                "S_DQ_CLOSE",
                calendar,
                stock_codes,
                dtype=float,
            )
        trade_status = _stock_field(
            market_data,
            "S_DQ_TRADESTATUS",
            calendar,
            stock_codes,
            dtype=object,
        )
        limit_up = _stock_field(
            market_data,
            "S_DQ_LIMIT",
            calendar,
            stock_codes,
            dtype=float,
        )
        limit_down = _stock_field(
            market_data,
            "S_DQ_STOPPING",
            calendar,
            stock_codes,
            dtype=float,
        )

    benchmark_open, benchmark_close = _benchmark_prices(market_data, settings)
    return PriceContext(
        calendar=calendar,
        stock_codes=stock_codes,
        trade_prices=trade_prices,
        trade_price_filled=trade_price_filled,
        trade_price_positions=trade_price_positions,
        close_prices=close_prices,
        close_price_filled=close_price_filled,
        close_price_positions=close_price_positions,
        raw_open_prices=raw_open_prices,
        raw_close_prices=raw_close_prices,
        trade_status=trade_status,
        limit_up=limit_up,
        limit_down=limit_down,
        benchmark_open=benchmark_open,
        benchmark_close=benchmark_close,
    )


def required_price_row(
    context: PriceContext,
    date_position: int,
    kind: Literal["open", "close"],
    required_mask: np.ndarray,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """
    读取事件的全股票参考价格，并检查实际需要估值或成交的股票。

    输出来源使用 ``open``、``close``、``previous_close`` 或 ``missing``；
    日期位置为 -1 时表示仍无可用价格。
    """
    if kind == "open":
        prices = context.trade_prices[date_position]
        price_filled = context.trade_price_filled[date_position]
        price_positions = context.trade_price_positions[date_position]
    else:
        prices = context.close_prices[date_position]
        price_filled = context.close_price_filled[date_position]
        price_positions = context.close_price_positions[date_position]

    missing_required_prices = required_mask & (
        ~np.isfinite(prices) | (prices <= 0)
    )
    if missing_required_prices.any():
        missing_codes = context.stock_codes[missing_required_prices].tolist()[:8]
        event_date = context.calendar[date_position]
        raise ValueError(f"{event_date.date()} 缺少 {kind} 价格: {missing_codes}")

    price_sources = np.full(len(context.stock_codes), "missing", dtype=object)
    valid_prices = np.isfinite(prices) & (prices > 0)
    price_sources[valid_prices] = kind
    price_sources[price_filled] = "previous_close"
    return prices, price_sources, price_positions


def benchmark_price(
    context: PriceContext,
    date_position: int,
    kind: Literal["open", "close"],
) -> float:
    """读取一个事件时点的正基准点位。"""
    benchmark_values = (
        context.benchmark_open if kind == "open" else context.benchmark_close
    )
    benchmark_value = benchmark_values[date_position]
    if not np.isfinite(benchmark_value) or benchmark_value <= 0:
        event_date = context.calendar[date_position]
        raise ValueError(f"{event_date.date()} 缺少基准 {kind} 价格")
    return float(benchmark_value)


def _stock_field(
    market_data: MarketData,
    field_name: str,
    calendar: pd.DatetimeIndex,
    stock_codes: pd.Index,
    dtype: type,
) -> np.ndarray:
    """读取并固定一个股票行情字段的日期和股票顺序。"""
    return market_data.get_panel("stock_quote", field_name).reindex(
        index=calendar,
        columns=stock_codes,
    ).to_numpy(dtype=dtype)


def _benchmark_prices(
    market_data: MarketData,
    settings: Mapping[str, Any],
) -> tuple[np.ndarray, np.ndarray]:
    """按显式来源构造单位一致的基准开盘和收盘序列。"""
    benchmark_code = market_data.benchmark_index
    benchmark_source = settings["benchmark"]["source"]
    if benchmark_source not in {"index_price", "index_total_return"}:
        raise ValueError(f"未知 benchmark.source: {benchmark_source}")
    benchmark_close = market_data.get_panel(
        benchmark_source,
        "S_DQ_CLOSE",
    )[benchmark_code].reindex(market_data.calendar).to_numpy(dtype=float)

    if settings["trade_price"] == "close":
        return benchmark_close.copy(), benchmark_close

    price_index_open = market_data.get_panel(
        "index_price",
        "S_DQ_OPEN",
    )[benchmark_code].reindex(market_data.calendar).to_numpy(dtype=float)
    if benchmark_source == "index_price":
        benchmark_open = price_index_open
    elif benchmark_source == "index_total_return":
        price_index_close = market_data.get_panel(
            "index_price",
            "S_DQ_CLOSE",
        )[benchmark_code].reindex(market_data.calendar).to_numpy(dtype=float)
        benchmark_open = benchmark_close * price_index_open / price_index_close
    return benchmark_open, benchmark_close
