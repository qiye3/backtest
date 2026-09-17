"""绘制单组合策略回测和目标权重偏离度。"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

import matplotlib.pyplot as plt
import pandas as pd
from matplotlib.ticker import PercentFormatter

from src.plotter.style import save_figure, set_figure_title, style_axis, style_date_axis


def plot_strategy_backtest(
    strategy_name: str,
    backtest_result: Mapping[str, Any],
    mode: str,
    interval: int,
    settings: Mapping[str, Any],
    output_stem: Path,
    backtest_settings: Mapping[str, Any],
    benchmark_index: str,
) -> list[Path]:
    """绘制一个策略、一个调仓周期和一种账户模式的增强回测图。"""
    period_result = backtest_result["periods"][interval]
    curve = period_result["groups"]["strategy"]["curves"][
        settings["curve_frequency"]
    ]
    strategy_return, benchmark_return, excess_return = _return_curves(
        curve,
        mode,
    )
    strategy_drawdown = _drawdown(strategy_return, mode == "account")
    excess_drawdown = _drawdown(excess_return, mode == "account")

    figure = plt.figure(
        figsize=(settings["width"], settings["row_height"] * 2.25),
        layout="constrained",
    )
    grid = figure.add_gridspec(3, 1, height_ratios=[1.8, 1.0, 0.55])
    return_axis = figure.add_subplot(grid[0, 0])
    drawdown_axis = figure.add_subplot(grid[1, 0], sharex=return_axis)
    table_axis = figure.add_subplot(grid[2, 0])

    set_figure_title(
        figure,
        f"{strategy_name} | {mode.capitalize()} index enhancement",
        settings,
        annotation=_strategy_config_label(
            backtest_result["rebalance_frequency"],
            interval,
            backtest_settings,
            benchmark_index,
        ),
    )
    return_axis.plot(
        curve["timestamp"],
        strategy_return,
        color="#C62828",
        linewidth=1.7,
        label="Strategy",
    )
    return_axis.plot(
        curve["timestamp"],
        benchmark_return,
        color="#777777",
        linewidth=1.6,
        linestyle="--",
        label="Benchmark",
    )
    return_axis.plot(
        curve["timestamp"],
        excess_return,
        color="#238B45",
        linewidth=1.6,
        label="Excess",
    )
    return_axis.axhline(0, color="#555555", linewidth=0.6)
    return_axis.set_ylabel("Cumulative return")
    return_axis.yaxis.set_major_formatter(PercentFormatter(1))
    return_axis.legend(loc="upper left", frameon=False, ncol=3)

    _draw_drawdown_curve(
        drawdown_axis,
        curve["timestamp"],
        strategy_drawdown,
        "#C62828",
        "Strategy drawdown",
    )
    _draw_drawdown_curve(
        drawdown_axis,
        curve["timestamp"],
        excess_drawdown,
        "#238B45",
        "Excess drawdown",
    )
    drawdown_axis.set_ylabel("Drawdown")
    drawdown_axis.yaxis.set_major_formatter(PercentFormatter(1))
    drawdown_axis.legend(loc="lower left", frameon=False, ncol=2)

    for axis in [return_axis, drawdown_axis]:
        style_axis(axis)
        axis.grid(axis="x", alpha=0.18)
        style_date_axis(axis)
    plt.setp(return_axis.get_xticklabels(), visible=False)
    _draw_metrics_table(
        table_axis,
        backtest_result["metrics"],
        interval,
    )
    return save_figure(figure, output_stem, settings)


def plot_weight_deviation(
    strategy_name: str,
    deviation: pd.DataFrame,
    settings: Mapping[str, Any],
    output_stem: Path,
    rebalance_label: str,
) -> list[Path]:
    """绘制目标 Active Share 以及单票最大超配和低配。"""
    figure, axes = plt.subplots(
        2,
        1,
        figsize=(settings["width"], settings["row_height"] * 1.8),
        sharex=True,
        layout="constrained",
    )
    set_figure_title(
        figure,
        f"{strategy_name} | Target weight deviation",
        settings,
        annotation=rebalance_label,
    )
    axes[0].plot(
        deviation["date"],
        deviation["active_share"],
        color="#174A73",
        linewidth=1.6,
    )
    axes[0].set_ylabel("Active Share")
    axes[1].plot(
        deviation["date"],
        deviation["max_overweight"],
        color="#C62828",
        linewidth=1.5,
        label="Max overweight",
    )
    axes[1].plot(
        deviation["date"],
        deviation["max_underweight"],
        color="#238B45",
        linewidth=1.5,
        label="Max underweight",
    )
    axes[1].axhline(0, color="#555555", linewidth=0.6)
    axes[1].set_ylabel("Active weight")
    axes[1].legend(loc="upper left", frameon=False, ncol=2)
    for axis in axes:
        axis.yaxis.set_major_formatter(PercentFormatter(1))
        style_axis(axis)
        axis.grid(axis="x", alpha=0.18)
        style_date_axis(axis)
    return save_figure(figure, output_stem, settings)


def _return_curves(
    curve: pd.DataFrame,
    mode: str,
) -> tuple[pd.Series, pd.Series, pd.Series]:
    """按 simple 加法或 account 复合口径构造三条累计收益。"""
    if mode == "simple":
        strategy_return = curve["cumulative_return"]
        benchmark_return = curve["benchmark_cumulative_return"]
        return (
            strategy_return,
            benchmark_return,
            strategy_return - benchmark_return,
        )
    strategy_return = curve["nav"] - 1
    benchmark_return = curve["benchmark_nav"] - 1
    excess_return = curve["nav"].div(curve["benchmark_nav"]) - 1
    return strategy_return, benchmark_return, excess_return


def _drawdown(cumulative_return: pd.Series, compound: bool) -> pd.Series:
    """按回测模式计算策略或超额收益的完整回撤序列。"""
    if compound:
        nav = 1 + cumulative_return
        return nav.div(nav.cummax()) - 1
    return cumulative_return - cumulative_return.cummax()


def _draw_drawdown_curve(
    axis: plt.Axes,
    timestamps: pd.Series,
    drawdown: pd.Series,
    color: str,
    label: str,
) -> None:
    """绘制回撤实线及同色半透明阴影。"""
    axis.plot(timestamps, drawdown, color=color, linewidth=1.3, label=label)
    axis.fill_between(timestamps, drawdown, 0, color=color, alpha=0.18)


def _draw_metrics_table(
    axis: plt.Axes,
    metrics: pd.DataFrame,
    interval: int,
) -> None:
    """在单周期策略图底部展示核心绩效指标。"""
    metric_row = metrics.loc[
        metrics["rebalance_interval"] == interval
    ].iloc[0]
    metric_names = [
        "total_return",
        "annual_return",
        "sharpe",
        "max_drawdown",
        "annual_turnover",
        "benchmark_total_return",
        "excess_total_return",
        "tracking_error",
        "information_ratio",
    ]
    labels = [
        "Total",
        "Annual",
        "Sharpe",
        "Max DD",
        "Turnover",
        "Benchmark",
        "Excess",
        "Tracking error",
        "Information ratio",
    ]
    percent_metrics = {
        "total_return",
        "annual_return",
        "max_drawdown",
        "benchmark_total_return",
        "excess_total_return",
        "tracking_error",
    }
    values = []
    for metric_name in metric_names:
        value = metric_row[metric_name]
        if metric_name in percent_metrics:
            values.append(f"{value:.1%}")
        elif metric_name == "annual_turnover":
            values.append(f"{value:.2f}x")
        else:
            values.append(f"{value:.2f}")
    axis.axis("off")
    table = axis.table(
        cellText=[values],
        colLabels=labels,
        loc="center",
        cellLoc="center",
    )
    table.auto_set_font_size(False)
    table.set_fontsize(7.5)
    table.scale(1, 1.25)


def _strategy_config_label(
    frequency: str,
    interval: int,
    settings: Mapping[str, Any],
    benchmark_index: str,
) -> str:
    """格式化策略图的调仓、成交和基准参数标注。"""
    return (
        f"rebalance: {frequency}-{interval} | "
        f"benchmark: {benchmark_index} | "
        f"trade_price: {settings['trade_price']} | "
        f"transaction_cost_rate: {settings['transaction_cost_rate']}"
    )
