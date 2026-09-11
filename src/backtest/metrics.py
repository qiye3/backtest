"""按简易累加收益或账户复合净值口径计算统一回测指标。"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import numpy as np
import pandas as pd


def annualize_return(total_return: float, years: float, method: str) -> float:
    """按线性或复合方法将区间总收益年化。"""
    if years <= 0:
        return np.nan
    if method == "linear":
        return total_return / years
    if total_return <= -1:
        return np.nan
    return float(np.expm1(np.log1p(total_return) / years))


def calculate_metrics(
    result: Mapping[str, Any],
    gross_result: Mapping[str, Any],
    mode: str,
    metrics_settings: Mapping[str, Any],
    weeks: int,
) -> dict[str, Any]:
    """
    汇总一个分组组合的费后、费前、风险和换手指标。

    输入：费后结果、零费率对照结果、回测模式、指标配置和调仓
    周数。
    输出：字段顺序固定的一行指标字典。
    """
    full_curve = result["curves"]["all"]
    start_time = full_curve["timestamp"].iloc[0]
    end_time = full_curve["timestamp"].iloc[-1]
    years = (end_time - start_time).total_seconds() / (365.25 * 86400)

    metrics = {
        "actual_start": str(start_time),
        "actual_end": str(end_time),
        "years": years,
    }
    metrics.update(
        _return_metrics(
            result=result,
            gross_result=gross_result,
            mode=mode,
            metrics_settings=metrics_settings,
            years=years,
        )
    )
    metrics.update(
        _risk_metrics(
            result=result,
            mode=mode,
            metrics_settings=metrics_settings,
            weeks=weeks,
        )
    )
    metrics.update(
        _turnover_metrics(
            turnover_events=result["turnover"],
            mode=mode,
            metrics_settings=metrics_settings,
            years=years,
        )
    )
    metric_columns = [
        "actual_start",
        "actual_end",
        "years",
        "metric_frequency",
        "risk_periods",
        "risk_periods_per_year",
        "gross_total_return",
        "net_total_return",
        "total_return",
        "annual_return",
        "gross_annual_return",
        "annual_return_method",
        "sharpe",
        "max_drawdown",
        "drawdown_method",
        "annual_volatility",
        "mean_turnover",
        "annual_turnover",
        "buy_turnover",
        "sell_turnover",
        "total_cost",
        "total_cost_rate",
        "annual_cost_rate",
        "estimated_trade_fraction",
        "benchmark_total_return",
        "excess_total_return",
        "tracking_error",
        "information_ratio",
    ]
    return {column: metrics[column] for column in metric_columns}


def _curve_returns(
    curve: pd.DataFrame,
    mode: str,
    benchmark: bool = False,
) -> pd.Series:
    """从对应模式的曲线提取逐期策略或基准收益。"""
    if mode == "simple":
        column = (
            "benchmark_cumulative_return"
            if benchmark
            else "cumulative_return"
        )
        return curve[column].diff()
    column = "benchmark_nav" if benchmark else "nav"
    return curve[column].pct_change(fill_method=None)


def _return_metrics(
    result: Mapping[str, Any],
    gross_result: Mapping[str, Any],
    mode: str,
    metrics_settings: Mapping[str, Any],
    years: float,
) -> dict[str, Any]:
    """计算总收益、年化、回撤、基准和超额收益。"""
    net_curve = result["curves"]["all"]
    gross_curve = gross_result["curves"]["all"]
    if mode == "simple":
        net_values = net_curve["cumulative_return"]
        net_total_return = float(net_values.iloc[-1])
        gross_total_return = float(
            gross_curve["cumulative_return"].iloc[-1]
        )
        benchmark_total_return = float(
            net_curve["benchmark_cumulative_return"].iloc[-1]
        )
        excess_total_return = net_total_return - benchmark_total_return
        max_drawdown = float((net_values - net_values.cummax()).min())
        drawdown_method = "additive_return_points"
        annual_return_method = metrics_settings["simple_annual_return"]
    else:
        net_values = net_curve["nav"]
        net_total_return = float(net_values.iloc[-1] - 1)
        gross_total_return = float(gross_curve["nav"].iloc[-1] - 1)
        benchmark_total_return = float(net_curve["benchmark_nav"].iloc[-1] - 1)
        excess_total_return = float(
            net_values.iloc[-1] / net_curve["benchmark_nav"].iloc[-1] - 1
        )
        max_drawdown = float((net_values / net_values.cummax() - 1).min())
        drawdown_method = "relative_nav"
        annual_return_method = metrics_settings["account_annual_return"]

    annual_net_basis = net_total_return
    annual_gross_basis = gross_total_return
    if mode == "simple" and annual_return_method == "compound":
        net_period_returns = _curve_returns(
            result["curves"]["rebalance"],
            mode,
        ).dropna()
        gross_period_returns = _curve_returns(
            gross_result["curves"]["rebalance"],
            mode,
        ).dropna()
        annual_net_basis = float(np.prod(1 + net_period_returns) - 1)
        annual_gross_basis = float(np.prod(1 + gross_period_returns) - 1)

    return {
        "gross_total_return": gross_total_return,
        "net_total_return": net_total_return,
        "total_return": net_total_return,
        "annual_return": annualize_return(
            annual_net_basis,
            years,
            annual_return_method,
        ),
        "gross_annual_return": annualize_return(
            annual_gross_basis,
            years,
            annual_return_method,
        ),
        "annual_return_method": annual_return_method,
        "max_drawdown": max_drawdown,
        "drawdown_method": drawdown_method,
        "benchmark_total_return": benchmark_total_return,
        "excess_total_return": excess_total_return,
    }


def _risk_metrics(
    result: Mapping[str, Any],
    mode: str,
    metrics_settings: Mapping[str, Any],
    weeks: int,
) -> dict[str, Any]:
    """按配置频率计算波动率、Sharpe 和相对基准风险。"""
    frequency = metrics_settings["return_frequency"]
    curve = result["curves"][frequency].copy()
    if frequency == "daily":
        first_timestamp = curve["timestamp"].iloc[0]
        curve = curve.loc[
            (curve["event"] == "initial")
            | curve["timestamp"].gt(first_timestamp)
        ].reset_index(drop=True)

    period_returns = _curve_returns(curve, mode)
    benchmark_returns = _curve_returns(curve, mode, benchmark=True)
    valid_observations = period_returns.notna()
    if frequency == "rebalance":
        valid_observations &= curve["is_rebalance"] & curve[
            "timestamp"
        ].diff().gt(pd.Timedelta(0))
    period_returns = period_returns.loc[valid_observations]
    benchmark_returns = benchmark_returns.loc[valid_observations]

    if frequency == "daily":
        periods_per_year = metrics_settings["annual_trading_days"]
    else:
        periods_per_year = metrics_settings["annual_weeks"] / weeks
    period_risk_free = np.expm1(
        np.log1p(metrics_settings["risk_free_rate"]) / periods_per_year
    )
    strategy_excess_returns = period_returns - period_risk_free
    excess_standard_deviation = strategy_excess_returns.std(ddof=1)
    active_returns = period_returns - benchmark_returns
    tracking_error = active_returns.std(ddof=1) * np.sqrt(periods_per_year)

    sharpe = np.nan
    if excess_standard_deviation > 0:
        sharpe = float(
            strategy_excess_returns.mean()
            / excess_standard_deviation
            * np.sqrt(periods_per_year)
        )
    information_ratio = np.nan
    if tracking_error > 0:
        information_ratio = float(
            active_returns.mean() * periods_per_year / tracking_error
        )
    return {
        "metric_frequency": frequency,
        "risk_periods": len(period_returns),
        "risk_periods_per_year": periods_per_year,
        "sharpe": sharpe,
        "annual_volatility": float(
            period_returns.std(ddof=1) * np.sqrt(periods_per_year)
        ),
        "tracking_error": float(tracking_error),
        "information_ratio": information_ratio,
    }


def _turnover_metrics(
    turnover_events: pd.DataFrame,
    mode: str,
    metrics_settings: Mapping[str, Any],
    years: float,
) -> dict[str, float]:
    """计算换手、费用和历史收盘补价成交比例。"""
    selected_events = turnover_events
    if not metrics_settings["include_initial_turnover"]:
        selected_events = turnover_events.loc[~turnover_events["initial"]]

    metrics = {
        "mean_turnover": 0.0,
        "annual_turnover": 0.0,
        "buy_turnover": 0.0,
        "sell_turnover": 0.0,
        "total_cost": np.nan,
        "total_cost_rate": 0.0,
        "annual_cost_rate": 0.0,
        "estimated_trade_fraction": 0.0,
    }
    if mode == "account":
        metrics["total_cost"] = 0.0
    if not selected_events.empty:
        metrics["mean_turnover"] = float(selected_events["turnover"].mean())
        metrics["buy_turnover"] = float(
            selected_events["buy_turnover"].sum()
        )
        metrics["sell_turnover"] = float(
            selected_events["sell_turnover"].sum()
        )
        if years > 0:
            metrics["annual_turnover"] = float(
                selected_events["turnover"].sum() / years
            )
    if not turnover_events.empty:
        metrics["total_cost_rate"] = float(
            turnover_events["cost_rate"].sum()
        )
        metrics["estimated_trade_fraction"] = float(
            turnover_events["estimated_trade_fraction"].sum()
        )
        if years > 0:
            metrics["annual_cost_rate"] = float(
                turnover_events["cost_rate"].sum() / years
            )
        if mode == "account":
            metrics["total_cost"] = float(turnover_events["cost_amount"].sum())
    return metrics
