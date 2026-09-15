"""运行以调仓期收益累加为定义的单位资金简易回测。"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import numpy as np
import pandas as pd

from src.backtest.events import (
    event_plan,
    event_timestamp,
    make_curve_views,
    prepare_targets,
)
from src.backtest.prices import (
    PriceContext,
    benchmark_price,
    prepare_price_context,
    required_price_row,
)
from src.backtest.rebalance import EPSILON, drift_weights, rebalance_weights
from src.backtest.returns import (
    ReturnContext,
    benchmark_period_gross_return,
    prepare_return_context,
    stock_period_gross_returns,
)
from src.data.market_data import MarketData

SIMPLE_TRADE_COLUMNS = [
    "date",
    "timestamp",
    "code",
    "side",
    "weight_change",
    "cost_rate",
    "price",
    "price_source",
    "price_date",
]
TURNOVER_COLUMNS = [
    "date",
    "timestamp",
    "initial",
    "buy_turnover",
    "sell_turnover",
    "turnover",
    "cost_rate",
    "cost_contribution",
    "estimated_trade_fraction",
]


def run_simple(
    target_weights: pd.DataFrame,
    market_data: MarketData,
    settings: Mapping[str, Any],
    need_daily: bool = True,
    return_panel: pd.DataFrame | None = None,
) -> dict[str, Any]:
    """
    运行一个目标组合的简易累加收益回测。

    输入：单组目标权重、市场数据、simple 配置、是否计算每日收盘估值，以及
    可选的外部日收益宽表。
    输出：包含事件曲线、交易明细和换手事件的字典。
    """
    if settings["initial_capital"] != 1:
        raise ValueError("simple 回测的 initial_capital 必须为 1")
    if settings["execution"]["policy"] != "ideal":
        raise ValueError("simple 回测只支持 ideal execution")
    if return_panel is not None:
        if settings["trade_price"] != "close":
            raise ValueError("外部日收益回测要求 trade_price 为 close")
        return_context = prepare_return_context(
            return_panel,
            market_data,
            settings,
        )
        return _run_simple_returns_with_context(
            target_weights,
            return_context,
            settings,
            need_daily,
        )

    price_context = prepare_price_context(market_data, settings)
    return _run_simple_with_context(
        target_weights,
        price_context,
        settings,
        need_daily,
    )


def _run_simple_with_context(
    target_weights: pd.DataFrame,
    price_context: PriceContext,
    settings: Mapping[str, Any],
    need_daily: bool,
) -> dict[str, Any]:
    """使用批量任务共享的价格上下文运行一个简易组合。"""
    targets = prepare_targets(target_weights, price_context, settings)
    target_positions = price_context.calendar.get_indexer(targets.index)
    targets_by_position = {
        date_position: targets.iloc[row_position].to_numpy(dtype=float)
        for row_position, date_position in enumerate(target_positions)
    }

    stock_count = len(price_context.stock_codes)
    weights = np.zeros(stock_count, dtype=float)
    previous_prices = None
    previous_benchmark = None
    completed_period_return = 0.0
    period_growth = 1.0
    completed_benchmark_return = 0.0
    benchmark_growth = 1.0
    curve_rows = []
    trade_frames = []
    turnover_rows = []
    is_initial_event = True

    for date_position, price_kind, is_rebalance, is_terminal in event_plan(
        targets,
        price_context,
        settings,
        need_daily,
    ):
        event_date = price_context.calendar[date_position]
        held_stocks = weights > EPSILON
        prices, price_sources, price_positions = required_price_row(
            price_context,
            date_position,
            price_kind,
            held_stocks,
        )
        if previous_prices is not None:
            weights, step_growth = drift_weights(
                weights,
                previous_prices,
                prices,
            )
            period_growth *= step_growth

        current_benchmark = benchmark_price(
            price_context,
            date_position,
            price_kind,
        )
        if previous_benchmark is not None:
            benchmark_growth *= current_benchmark / previous_benchmark

        if is_initial_event:
            curve_rows.append(_initial_simple_row(event_date, price_kind))

        event_target = targets_by_position.get(date_position) if is_rebalance else None
        if is_terminal and settings["liquidate_at_end"]:
            event_target = np.zeros(stock_count, dtype=float)

        traded = False
        if event_target is not None and not np.isnan(event_target).all():
            required_stocks = held_stocks | (event_target > EPSILON)
            prices, price_sources, price_positions = required_price_row(
                price_context,
                date_position,
                price_kind,
                required_stocks,
            )
            weights, period_growth, turnover_row, trade_frame = (
                _execute_simple_rebalance(
                    weights=weights,
                    target_weights=event_target,
                    period_growth=period_growth,
                    prices=prices,
                    price_sources=price_sources,
                    price_positions=price_positions,
                    date_position=date_position,
                    price_kind=price_kind,
                    price_context=price_context,
                    settings=settings,
                    is_initial_event=is_initial_event,
                )
            )
            turnover_rows.append(turnover_row)
            if not trade_frame.empty:
                trade_frames.append(trade_frame)
            traded = True

        cumulative_return = completed_period_return + period_growth - 1
        benchmark_cumulative_return = (
            completed_benchmark_return + benchmark_growth - 1
        )
        curve_rows.append(
            {
                "date": event_date,
                "timestamp": event_timestamp(event_date, price_kind),
                "price_kind": price_kind,
                "event": "rebalance" if traded else "valuation",
                "is_rebalance": is_rebalance,
                "is_terminal": is_terminal,
                "cumulative_return": cumulative_return,
                "benchmark_cumulative_return": benchmark_cumulative_return,
                "cash_weight": 1 - weights.sum(),
            }
        )

        # hold 只是不交易，调仓点仍然结束当前收益段。
        if is_rebalance:
            completed_period_return = cumulative_return
            period_growth = 1.0
            completed_benchmark_return = benchmark_cumulative_return
            benchmark_growth = 1.0
        previous_prices = prices
        previous_benchmark = current_benchmark
        is_initial_event = False

    trades = (
        pd.concat(trade_frames, ignore_index=True)
        if trade_frames
        else pd.DataFrame(columns=SIMPLE_TRADE_COLUMNS)
    )
    turnover = pd.DataFrame(turnover_rows, columns=TURNOVER_COLUMNS)
    return {
        "curves": make_curve_views(curve_rows, need_daily),
        "trades": trades,
        "turnover": turnover,
    }


def _run_simple_returns_with_context(
    target_weights: pd.DataFrame,
    return_context: ReturnContext,
    settings: Mapping[str, Any],
    need_daily: bool,
) -> dict[str, Any]:
    """使用外部收盘到收盘日收益运行简易回测。"""
    targets = prepare_targets(target_weights, return_context, settings)
    target_positions = return_context.calendar.get_indexer(targets.index)
    targets_by_position = {
        date_position: targets.iloc[row_position].to_numpy(dtype=float)
        for row_position, date_position in enumerate(target_positions)
    }

    stock_count = len(return_context.stock_codes)
    weights = np.zeros(stock_count, dtype=float)
    previous_position = None
    completed_period_return = 0.0
    period_growth = 1.0
    completed_benchmark_return = 0.0
    benchmark_growth = 1.0
    curve_rows = []
    trade_frames = []
    turnover_rows = []
    is_initial_event = True

    for date_position, price_kind, is_rebalance, is_terminal in event_plan(
        targets,
        return_context,
        settings,
        need_daily,
    ):
        event_date = return_context.calendar[date_position]
        held_stocks = weights > EPSILON
        if previous_position is not None:
            stock_gross_returns = stock_period_gross_returns(
                return_context,
                previous_position,
                date_position,
                held_stocks,
            )
            portfolio_growth = float(
                1 - weights.sum() + weights @ stock_gross_returns
            )
            weights = weights * stock_gross_returns / portfolio_growth
            period_growth *= portfolio_growth
            benchmark_growth *= benchmark_period_gross_return(
                return_context,
                previous_position,
                date_position,
            )

        if is_initial_event:
            curve_rows.append(_initial_simple_row(event_date, price_kind))

        event_target = targets_by_position.get(date_position) if is_rebalance else None
        if is_terminal and settings["liquidate_at_end"]:
            event_target = np.zeros(stock_count, dtype=float)

        traded = False
        if event_target is not None and not np.isnan(event_target).all():
            missing_prices = np.full(stock_count, np.nan)
            return_sources = np.full(stock_count, "external_return", dtype=object)
            return_positions = np.full(stock_count, date_position, dtype=int)
            weights, period_growth, turnover_row, trade_frame = (
                _execute_simple_rebalance(
                    weights=weights,
                    target_weights=event_target,
                    period_growth=period_growth,
                    prices=missing_prices,
                    price_sources=return_sources,
                    price_positions=return_positions,
                    date_position=date_position,
                    price_kind=price_kind,
                    price_context=return_context,
                    settings=settings,
                    is_initial_event=is_initial_event,
                )
            )
            turnover_rows.append(turnover_row)
            if not trade_frame.empty:
                trade_frames.append(trade_frame)
            traded = True

        cumulative_return = completed_period_return + period_growth - 1
        benchmark_cumulative_return = (
            completed_benchmark_return + benchmark_growth - 1
        )
        curve_rows.append(
            {
                "date": event_date,
                "timestamp": event_timestamp(event_date, price_kind),
                "price_kind": price_kind,
                "event": "rebalance" if traded else "valuation",
                "is_rebalance": is_rebalance,
                "is_terminal": is_terminal,
                "cumulative_return": cumulative_return,
                "benchmark_cumulative_return": benchmark_cumulative_return,
                "cash_weight": 1 - weights.sum(),
            }
        )

        if is_rebalance:
            completed_period_return = cumulative_return
            period_growth = 1.0
            completed_benchmark_return = benchmark_cumulative_return
            benchmark_growth = 1.0
        previous_position = date_position
        is_initial_event = False

    trades = (
        pd.concat(trade_frames, ignore_index=True)
        if trade_frames
        else pd.DataFrame(columns=SIMPLE_TRADE_COLUMNS)
    )
    turnover = pd.DataFrame(turnover_rows, columns=TURNOVER_COLUMNS)
    return {
        "curves": make_curve_views(curve_rows, need_daily),
        "trades": trades,
        "turnover": turnover,
    }


def _execute_simple_rebalance(
    weights: np.ndarray,
    target_weights: np.ndarray,
    period_growth: float,
    prices: np.ndarray,
    price_sources: np.ndarray,
    price_positions: np.ndarray,
    date_position: int,
    price_kind: str,
    price_context: PriceContext | ReturnContext,
    settings: Mapping[str, Any],
    is_initial_event: bool,
) -> tuple[np.ndarray, float, dict[str, Any], pd.DataFrame]:
    """执行一次简易调仓，并生成对应换手和交易明细。"""
    transaction_cost_rate = settings["transaction_cost_rate"]
    if is_initial_event and not settings["charge_initial_cost"]:
        transaction_cost_rate = 0.0

    posttrade_values, _, weight_changes, cost_fraction = rebalance_weights(
        weights,
        target_weights,
        transaction_cost_rate,
    )
    pretrade_growth = period_growth
    period_growth *= 1 - cost_fraction
    weights = posttrade_values / (1 - cost_fraction)
    buy_turnover = float(weight_changes[weight_changes > 0].sum())
    sell_turnover = float(-weight_changes[weight_changes < 0].sum())
    event_date = price_context.calendar[date_position]
    turnover_row = {
        "date": event_date,
        "timestamp": event_timestamp(event_date, price_kind),
        "initial": is_initial_event,
        "buy_turnover": buy_turnover,
        "sell_turnover": sell_turnover,
        "turnover": (buy_turnover + sell_turnover) / 2,
        "cost_rate": cost_fraction,
        "cost_contribution": pretrade_growth * cost_fraction,
        "estimated_trade_fraction": float(
            np.abs(weight_changes)[price_sources == "previous_close"].sum()
        ),
    }
    trade_frame = _simple_trade_frame(
        weight_changes=weight_changes,
        prices=prices,
        price_sources=price_sources,
        price_positions=price_positions,
        date_position=date_position,
        price_kind=price_kind,
        transaction_cost_rate=transaction_cost_rate,
        price_context=price_context,
    )
    return weights, period_growth, turnover_row, trade_frame


def _simple_trade_frame(
    weight_changes: np.ndarray,
    prices: np.ndarray,
    price_sources: np.ndarray,
    price_positions: np.ndarray,
    date_position: int,
    price_kind: str,
    transaction_cost_rate: float,
    price_context: PriceContext | ReturnContext,
) -> pd.DataFrame:
    """通过非零成交坐标构造一次简易调仓的交易表。"""
    stock_positions = np.flatnonzero(np.abs(weight_changes) > EPSILON)
    if not len(stock_positions):
        return pd.DataFrame(columns=SIMPLE_TRADE_COLUMNS)

    event_date = price_context.calendar[date_position]
    actual_price_positions = price_positions[stock_positions]
    return pd.DataFrame(
        {
            "date": event_date,
            "timestamp": event_timestamp(event_date, price_kind),
            "code": price_context.stock_codes.to_numpy()[stock_positions],
            "side": np.where(
                weight_changes[stock_positions] > 0,
                "buy",
                "sell",
            ),
            "weight_change": weight_changes[stock_positions],
            "cost_rate": (
                np.abs(weight_changes[stock_positions]) * transaction_cost_rate
            ),
            "price": prices[stock_positions],
            "price_source": price_sources[stock_positions],
            "price_date": price_context.calendar.to_numpy()[
                actual_price_positions
            ],
        },
        columns=SIMPLE_TRADE_COLUMNS,
    )


def _initial_simple_row(event_date: pd.Timestamp, price_kind: str) -> dict[str, Any]:
    """构造首次成交前的零收益曲线起点。"""
    return {
        "date": event_date,
        "timestamp": event_timestamp(event_date, price_kind),
        "price_kind": price_kind,
        "event": "initial",
        "is_rebalance": False,
        "is_terminal": False,
        "cumulative_return": 0.0,
        "benchmark_cumulative_return": 0.0,
        "cash_weight": 1.0,
    }
