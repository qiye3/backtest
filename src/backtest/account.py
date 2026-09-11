"""运行以现金和复权持仓数量连续滚动的账户回测。"""

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
from src.backtest.rebalance import (
    EPSILON,
    constrained_rebalance,
    rebalance_weights,
)
from src.data.market_data import MarketData


ACCOUNT_TRADE_COLUMNS = [
    "date",
    "timestamp",
    "code",
    "side",
    "status",
    "reason",
    "requested_amount",
    "amount",
    "quantity",
    "price",
    "cost",
    "weight_change",
    "price_source",
    "price_date",
]
ACCOUNT_TURNOVER_COLUMNS = [
    "date",
    "timestamp",
    "initial",
    "buy_turnover",
    "sell_turnover",
    "turnover",
    "cost_rate",
    "cost_amount",
    "pretrade_assets",
    "estimated_trade_fraction",
]
HOLDING_COLUMNS = [
    "date",
    "timestamp",
    "code",
    "quantity",
    "price",
    "value",
    "weight",
    "price_source",
]


def run_account(
    target_weights: pd.DataFrame,
    market_data: MarketData,
    settings: Mapping[str, Any],
    need_daily: bool = True,
) -> dict[str, Any]:
    """
    运行一个目标组合的现金和持仓数量账户。

    输入：单组目标权重、市场数据、account 配置和是否计算每日收盘
    估值。
    输出：包含事件曲线、交易、换手和持仓明细的字典。
    """
    if settings["initial_capital"] <= 0:
        raise ValueError("account 回测的 initial_capital 必须为正数")
    price_context = prepare_price_context(market_data, settings)
    return _run_account_with_context(
        target_weights,
        price_context,
        settings,
        need_daily,
    )


def _run_account_with_context(
    target_weights: pd.DataFrame,
    price_context: PriceContext,
    settings: Mapping[str, Any],
    need_daily: bool,
) -> dict[str, Any]:
    """使用批量任务共享的价格上下文运行一个连续账户。"""
    targets = prepare_targets(target_weights, price_context, settings)
    target_positions = price_context.calendar.get_indexer(targets.index)
    targets_by_position = {
        date_position: targets.iloc[row_position].to_numpy(dtype=float)
        for row_position, date_position in enumerate(target_positions)
    }

    stock_count = len(price_context.stock_codes)
    quantities = np.zeros(stock_count, dtype=float)
    cash = float(settings["initial_capital"])
    benchmark_basis = None
    curve_rows = []
    trade_frames = []
    turnover_rows = []
    holding_frames = []
    is_initial_event = True

    for date_position, price_kind, is_rebalance, is_terminal in event_plan(
        targets,
        price_context,
        settings,
        need_daily,
    ):
        event_date = price_context.calendar[date_position]
        held_stocks = quantities > EPSILON
        prices, price_sources, price_positions = required_price_row(
            price_context,
            date_position,
            price_kind,
            held_stocks,
        )
        holding_values = np.where(
            held_stocks,
            quantities * prices,
            0.0,
        )
        pretrade_assets = float(cash + holding_values.sum())
        current_benchmark = benchmark_price(
            price_context,
            date_position,
            price_kind,
        )
        if is_initial_event:
            benchmark_basis = current_benchmark
            curve_rows.append(
                _initial_account_row(
                    event_date,
                    price_kind,
                    pretrade_assets,
                    cash,
                )
            )

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
            cash, quantities, turnover_row, trade_frame = (
                _execute_account_rebalance(
                    holding_values=holding_values,
                    pretrade_assets=pretrade_assets,
                    target_weights=event_target,
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

        held_stocks = quantities > EPSILON
        holding_values = np.where(
            held_stocks,
            quantities * prices,
            0.0,
        )
        account_assets = float(cash + holding_values.sum())
        curve_rows.append(
            {
                "date": event_date,
                "timestamp": event_timestamp(event_date, price_kind),
                "price_kind": price_kind,
                "event": "rebalance" if traded else "valuation",
                "is_rebalance": is_rebalance,
                "is_terminal": is_terminal,
                "assets": account_assets,
                "nav": account_assets / settings["initial_capital"],
                "benchmark_nav": current_benchmark / benchmark_basis,
                "cash": cash,
                "cash_weight": cash / account_assets,
            }
        )
        holding_frame = _account_holdings_frame(
            quantities=quantities,
            prices=prices,
            holding_values=holding_values,
            account_assets=account_assets,
            price_sources=price_sources,
            date_position=date_position,
            price_kind=price_kind,
            price_context=price_context,
        )
        if not holding_frame.empty:
            holding_frames.append(holding_frame)
        is_initial_event = False

    trades = (
        pd.concat(trade_frames, ignore_index=True)
        if trade_frames
        else pd.DataFrame(columns=ACCOUNT_TRADE_COLUMNS)
    )
    holdings = (
        pd.concat(holding_frames, ignore_index=True)
        if holding_frames
        else pd.DataFrame(columns=HOLDING_COLUMNS)
    )
    return {
        "curves": make_curve_views(curve_rows, need_daily),
        "trades": trades,
        "turnover": pd.DataFrame(
            turnover_rows,
            columns=ACCOUNT_TURNOVER_COLUMNS,
        ),
        "holdings": holdings,
    }


def _execute_account_rebalance(
    holding_values: np.ndarray,
    pretrade_assets: float,
    target_weights: np.ndarray,
    prices: np.ndarray,
    price_sources: np.ndarray,
    price_positions: np.ndarray,
    date_position: int,
    price_kind: str,
    price_context: PriceContext,
    settings: Mapping[str, Any],
    is_initial_event: bool,
) -> tuple[float, np.ndarray, dict[str, Any], pd.DataFrame]:
    """执行一次账户调仓并生成成交、换手和费用记录。"""
    transaction_cost_rate = settings["transaction_cost_rate"]
    if is_initial_event and not settings["charge_initial_cost"]:
        transaction_cost_rate = 0.0

    pretrade_weights = holding_values / pretrade_assets
    if settings["execution"]["policy"] == "ideal":
        (
            posttrade_weights,
            cash_fraction,
            weight_changes,
            cost_fraction,
        ) = rebalance_weights(
            pretrade_weights,
            target_weights,
            transaction_cost_rate,
        )
        requested_changes = weight_changes.copy()
        reasons = np.full(len(weight_changes), "", dtype=object)
    else:
        event_trade_status = price_context.trade_status[date_position]
        raw_price_matrix = (
            price_context.raw_open_prices
            if price_kind == "open"
            else price_context.raw_close_prices
        )
        event_raw_prices = raw_price_matrix[date_position]
        event_limit_up = price_context.limit_up[date_position]
        event_limit_down = price_context.limit_down[date_position]
        (
            posttrade_weights,
            cash_fraction,
            weight_changes,
            cost_fraction,
            requested_changes,
            reasons,
        ) = constrained_rebalance(
            before_weights=pretrade_weights,
            target_weights=target_weights,
            transaction_cost_rate=transaction_cost_rate,
            price_sources=price_sources,
            trade_status=event_trade_status,
            raw_trade_prices=event_raw_prices,
            limit_up=event_limit_up,
            limit_down=event_limit_down,
            execution=settings["execution"],
        )

    cash = pretrade_assets * cash_fraction
    quantities = np.divide(
        pretrade_assets * posttrade_weights,
        prices,
        out=np.zeros_like(posttrade_weights),
        where=np.isfinite(prices) & (prices > 0),
    )
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
        "cost_amount": pretrade_assets * cost_fraction,
        "pretrade_assets": pretrade_assets,
        "estimated_trade_fraction": float(
            np.abs(weight_changes)[price_sources == "previous_close"].sum()
        ),
    }
    trade_frame = _account_trade_frame(
        weight_changes=weight_changes,
        requested_changes=requested_changes,
        pretrade_assets=pretrade_assets,
        reasons=reasons,
        prices=prices,
        price_sources=price_sources,
        price_positions=price_positions,
        transaction_cost_rate=transaction_cost_rate,
        date_position=date_position,
        price_kind=price_kind,
        price_context=price_context,
    )
    return cash, quantities, turnover_row, trade_frame


def _account_trade_frame(
    weight_changes: np.ndarray,
    requested_changes: np.ndarray,
    pretrade_assets: float,
    reasons: np.ndarray,
    prices: np.ndarray,
    price_sources: np.ndarray,
    price_positions: np.ndarray,
    transaction_cost_rate: float,
    date_position: int,
    price_kind: str,
    price_context: PriceContext,
) -> pd.DataFrame:
    """批量展开一次调仓的请求金额、实际成交和成交状态。"""
    stock_positions = np.flatnonzero(
        (np.abs(weight_changes) > EPSILON)
        | (np.abs(requested_changes) > EPSILON)
    )
    if not len(stock_positions):
        return pd.DataFrame(columns=ACCOUNT_TRADE_COLUMNS)

    trade_amounts = pretrade_assets * weight_changes[stock_positions]
    requested_amounts = pretrade_assets * requested_changes[stock_positions]
    filled_amounts = np.abs(trade_amounts)
    requested_absolute_amounts = np.abs(requested_amounts)
    statuses = np.full(len(stock_positions), "filled", dtype=object)
    statuses[filled_amounts <= EPSILON] = "rejected"
    partial_orders = (
        filled_amounts > EPSILON
    ) & (np.abs(trade_amounts - requested_amounts) > EPSILON)
    statuses[partial_orders] = "partial"

    event_date = price_context.calendar[date_position]
    return pd.DataFrame(
        {
            "date": event_date,
            "timestamp": event_timestamp(event_date, price_kind),
            "code": price_context.stock_codes.to_numpy()[stock_positions],
            "side": np.where(requested_amounts > 0, "buy", "sell"),
            "status": statuses,
            "reason": reasons[stock_positions],
            "requested_amount": requested_absolute_amounts,
            "amount": filled_amounts,
            "quantity": filled_amounts / prices[stock_positions],
            "price": prices[stock_positions],
            "cost": filled_amounts * transaction_cost_rate,
            "weight_change": weight_changes[stock_positions],
            "price_source": price_sources[stock_positions],
            "price_date": price_context.calendar.to_numpy()[
                price_positions[stock_positions]
            ],
        },
        columns=ACCOUNT_TRADE_COLUMNS,
    )


def _account_holdings_frame(
    quantities: np.ndarray,
    prices: np.ndarray,
    holding_values: np.ndarray,
    account_assets: float,
    price_sources: np.ndarray,
    date_position: int,
    price_kind: str,
    price_context: PriceContext,
) -> pd.DataFrame:
    """批量展开一个事件结束后的非零持仓。"""
    stock_positions = np.flatnonzero(quantities > EPSILON)
    if not len(stock_positions):
        return pd.DataFrame(columns=HOLDING_COLUMNS)

    event_date = price_context.calendar[date_position]
    return pd.DataFrame(
        {
            "date": event_date,
            "timestamp": event_timestamp(event_date, price_kind),
            "code": price_context.stock_codes.to_numpy()[stock_positions],
            "quantity": quantities[stock_positions],
            "price": prices[stock_positions],
            "value": holding_values[stock_positions],
            "weight": holding_values[stock_positions] / account_assets,
            "price_source": price_sources[stock_positions],
        },
        columns=HOLDING_COLUMNS,
    )


def _initial_account_row(
    event_date: pd.Timestamp,
    price_kind: str,
    pretrade_assets: float,
    cash: float,
) -> dict[str, Any]:
    """构造首次成交前的账户净值起点。"""
    return {
        "date": event_date,
        "timestamp": event_timestamp(event_date, price_kind),
        "price_kind": price_kind,
        "event": "initial",
        "is_rebalance": False,
        "is_terminal": False,
        "assets": pretrade_assets,
        "nav": 1.0,
        "benchmark_nav": 1.0,
        "cash": cash,
        "cash_weight": 1.0,
    }
