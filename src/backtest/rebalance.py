"""提供两套回测共用的持仓漂移、精确费用和受限成交计算。"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import numpy as np
import pandas as pd

EPSILON = 1e-12


def rebalance_weights(
    before_weights: np.ndarray,
    target_weights: np.ndarray,
    transaction_cost_rate: float,
) -> tuple[np.ndarray, float, np.ndarray, float]:
    """
    按调仓前资产归一，求解扣费后的目标持仓和现金。

    费用比例满足 ``k = c * sum(abs((1-k) * target - before))``。
    二分法直接求连续单调残差的唯一根，不增加外部优化依赖。
    """
    before_values = np.asarray(before_weights, dtype=float)
    target_values = np.asarray(target_weights, dtype=float)
    if not 0 <= transaction_cost_rate < 1:
        raise ValueError("transaction_cost_rate 必须位于 [0, 1)")

    if transaction_cost_rate == 0:
        cost_fraction = 0.0
    else:
        lower_bound = 0.0
        upper_bound = 1.0
        # 60 次二分已经达到 float64 在 [0, 1] 上的数值分辨率。
        for _ in range(60):
            candidate = (lower_bound + upper_bound) / 2
            residual = candidate - transaction_cost_rate * np.abs(
                (1 - candidate) * target_values - before_values
            ).sum()
            if residual > 0:
                upper_bound = candidate
            else:
                lower_bound = candidate
        cost_fraction = (lower_bound + upper_bound) / 2

    posttrade_values = (1 - cost_fraction) * target_values
    weight_changes = posttrade_values - before_values
    cash_fraction = 1 - cost_fraction - posttrade_values.sum()
    return (
        posttrade_values,
        max(0.0, float(cash_fraction)),
        weight_changes,
        float(cost_fraction),
    )


def drift_weights(
    weights: np.ndarray,
    prices_before: np.ndarray,
    prices_after: np.ndarray,
) -> tuple[np.ndarray, float]:
    """
    在现金不计息、股票数量不变的口径下更新持仓权重。

    输出为漂移后的股票权重，以及本次相对上次估值的组合增长倍数。
    """
    held_stocks = weights > EPSILON
    relative_prices = np.ones(len(weights), dtype=float)
    relative_prices[held_stocks] = (
        prices_after[held_stocks] / prices_before[held_stocks]
    )
    stock_values = weights * relative_prices
    portfolio_growth = 1 - weights.sum() + stock_values.sum()
    return stock_values / portfolio_growth, float(portfolio_growth)


def execution_block_reasons(
    requested_changes: np.ndarray,
    price_sources: np.ndarray,
    trade_status: np.ndarray,
    raw_trade_prices: np.ndarray,
    limit_up: np.ndarray,
    limit_down: np.ndarray,
    execution: Mapping[str, Any],
) -> np.ndarray:
    """
    矩阵化判断受限账户每只股票的成交拒绝原因。

    判断优先级固定为缺少当前参考价、交易状态、涨跌停；没有交易请求
    的股票保持空原因。
    """
    requested_orders = np.abs(requested_changes) > EPSILON
    buy_orders = requested_changes > EPSILON
    sell_orders = requested_changes < -EPSILON
    reasons = np.full(len(requested_changes), "", dtype=object)

    missing_reference = requested_orders & (price_sources == "previous_close")
    reasons[missing_reference] = "missing_reference_price"

    if execution["block_suspended"]:
        unknown_status = requested_orders & pd.isna(trade_status)
        suspended = requested_orders & pd.Series(
            trade_status,
            dtype="string",
        ).str.contains("停", na=False).to_numpy()
        reasons[(reasons == "") & unknown_status] = "unknown_trade_status"
        reasons[(reasons == "") & suspended] = "suspended"

    if execution["block_buy_limit_up"]:
        invalid_buy_limit = buy_orders & (
            ~np.isfinite(raw_trade_prices)
            | ~np.isfinite(limit_up)
            | (raw_trade_prices <= 0)
            | (limit_up <= 0)
        )
        buy_limit_reached = buy_orders & (
            raw_trade_prices >= limit_up * (1 - 1e-10)
        )
        reasons[(reasons == "") & invalid_buy_limit] = "unknown_price_limit"
        reasons[(reasons == "") & buy_limit_reached] = "limit_up"

    if execution["block_sell_limit_down"]:
        invalid_sell_limit = sell_orders & (
            ~np.isfinite(raw_trade_prices)
            | ~np.isfinite(limit_down)
            | (raw_trade_prices <= 0)
            | (limit_down <= 0)
        )
        sell_limit_reached = sell_orders & (
            raw_trade_prices <= limit_down * (1 + 1e-10)
        )
        reasons[(reasons == "") & invalid_sell_limit] = "unknown_price_limit"
        reasons[(reasons == "") & sell_limit_reached] = "limit_down"
    return reasons


def constrained_rebalance(
    before_weights: np.ndarray,
    target_weights: np.ndarray,
    transaction_cost_rate: float,
    price_sources: np.ndarray,
    trade_status: np.ndarray,
    raw_trade_prices: np.ndarray,
    limit_up: np.ndarray,
    limit_down: np.ndarray,
    execution: Mapping[str, Any],
) -> tuple[np.ndarray, float, np.ndarray, float, np.ndarray, np.ndarray]:
    """
    执行先卖后买的受限账户调仓。

    被拒绝订单保持原持仓；完成可成交卖单后，现金不足的可成交买单按
    同一比例缩减。输出同时保留请求和实际权重变化，用于区分 filled、
    partial、rejected。
    """
    _, _, requested_changes, _ = rebalance_weights(
        before_weights,
        target_weights,
        transaction_cost_rate,
    )
    reasons = execution_block_reasons(
        requested_changes=requested_changes,
        price_sources=price_sources,
        trade_status=trade_status,
        raw_trade_prices=raw_trade_prices,
        limit_up=limit_up,
        limit_down=limit_down,
        execution=execution,
    )

    actual_weights = before_weights.copy()
    actual_changes = np.zeros_like(before_weights)
    cash_fraction = float(1 - before_weights.sum())

    sell_orders = requested_changes < -EPSILON
    executable_sells = sell_orders & (reasons == "")
    sold_weights = -requested_changes[executable_sells]
    actual_weights[executable_sells] -= sold_weights
    actual_changes[executable_sells] = requested_changes[executable_sells]
    cash_fraction += sold_weights.sum() * (1 - transaction_cost_rate)

    buy_orders = requested_changes > EPSILON
    executable_buys = buy_orders & (reasons == "")
    wanted_buys = np.where(executable_buys, requested_changes, 0.0)
    required_cash = wanted_buys.sum() * (1 + transaction_cost_rate)
    buy_scale = (
        min(1.0, max(0.0, cash_fraction) / required_cash)
        if required_cash
        else 0.0
    )
    actual_buys = wanted_buys * buy_scale
    actual_weights += actual_buys
    actual_changes += actual_buys
    cash_fraction -= actual_buys.sum() * (1 + transaction_cost_rate)
    if buy_scale < 1 - 1e-10:
        reasons[executable_buys] = "cash_constraint"

    cost_fraction = transaction_cost_rate * np.abs(actual_changes).sum()
    return (
        actual_weights,
        max(0.0, cash_fraction),
        actual_changes,
        float(cost_fraction),
        requested_changes,
        reasons,
    )
