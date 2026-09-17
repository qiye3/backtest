"""绘制指数增强回测总览和目标权重偏离诊断。"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib.ticker import MaxNLocator, PercentFormatter

from src.plotter.style import save_figure, set_figure_title, style_axis, style_date_axis
from src.strategy.evaluation import calculate_weight_deviation

STRATEGY_COLOR = "#174A73"
BENCHMARK_COLOR = "#777777"
EXCESS_COLOR = "#C66B2E"
POSITIVE_COLOR = "#24577A"
NEGATIVE_COLOR = "#D79A6A"
NEUTRAL_BAR_COLOR = "#B8CFE3"
OUTLIER_COLOR = "#D26A2E"


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
    """绘制策略、相对收益、双回撤、主动收益尖峰和指标摘要。"""
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
    active_returns = _active_returns(curve, mode)

    figure = plt.figure(
        figsize=(settings["width"], settings["row_height"] * 3.15),
        layout="constrained",
    )
    grid = figure.add_gridspec(
        5,
        1,
        height_ratios=[1.75, 1.0, 1.0, 0.9, 0.95],
    )
    strategy_axis = figure.add_subplot(grid[0, 0])
    excess_axis = figure.add_subplot(grid[1, 0], sharex=strategy_axis)
    drawdown_axis = figure.add_subplot(grid[2, 0], sharex=strategy_axis)
    active_axis = figure.add_subplot(grid[3, 0], sharex=strategy_axis)
    table_axis = figure.add_subplot(grid[4, 0])

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
    _draw_strategy_and_benchmark(
        strategy_axis,
        curve["timestamp"],
        strategy_return,
        benchmark_return,
    )
    _draw_excess_return(
        excess_axis,
        curve["timestamp"],
        excess_return,
    )
    _draw_drawdowns(
        drawdown_axis,
        curve["timestamp"],
        strategy_drawdown,
        excess_drawdown,
    )
    _draw_active_returns(active_axis, curve["timestamp"], active_returns)

    time_axes = [strategy_axis, excess_axis, drawdown_axis, active_axis]
    _draw_rebalance_markers(time_axes, period_result["actions"])
    _style_time_axes(time_axes)
    for axis in time_axes[:-1]:
        plt.setp(axis.get_xticklabels(), visible=False)
    _draw_metrics_table(table_axis, backtest_result["metrics"], interval)
    return save_figure(figure, output_stem, settings)


def plot_weight_deviation(
    strategy_name: str,
    target_weights: pd.DataFrame,
    benchmark_weights: pd.DataFrame,
    settings: Mapping[str, Any],
    output_stem: Path,
    rebalance_label: str,
) -> list[Path]:
    """绘制最新主动权重、Active Share、偏离极值和目标组合集中度。"""
    aligned_benchmark = benchmark_weights.reindex(
        index=target_weights.index,
        columns=target_weights.columns,
        fill_value=0.0,
    ).fillna(0.0)
    active_weights = target_weights - aligned_benchmark
    deviation = calculate_weight_deviation(target_weights, benchmark_weights)

    figure = plt.figure(
        figsize=(settings["width"], settings["row_height"] * 2.15),
        layout="constrained",
    )
    grid = figure.add_gridspec(2, 2, width_ratios=[0.95, 1.35])
    latest_axis = figure.add_subplot(grid[0, 0])
    active_share_axis = figure.add_subplot(grid[0, 1])
    extremes_axis = figure.add_subplot(grid[1, 0])
    concentration_axis = figure.add_subplot(grid[1, 1])

    set_figure_title(
        figure,
        f"{strategy_name} | Target weight deviation",
        settings,
        annotation=rebalance_label,
    )
    _draw_latest_active_weights(latest_axis, active_weights.iloc[-1])
    _draw_active_share(active_share_axis, deviation)
    _draw_active_weight_extremes(extremes_axis, deviation)
    _draw_target_concentration(concentration_axis, target_weights)
    return save_figure(figure, output_stem, settings)


def _draw_strategy_and_benchmark(
    axis: plt.Axes,
    timestamps: pd.Series,
    strategy_return: pd.Series,
    benchmark_return: pd.Series,
) -> None:
    """绘制策略和基准累计收益，避免将较小的超额曲线挤在同一尺度。"""
    axis.plot(
        timestamps,
        strategy_return,
        color=STRATEGY_COLOR,
        linewidth=1.8,
        label="Strategy",
    )
    axis.plot(
        timestamps,
        benchmark_return,
        color=BENCHMARK_COLOR,
        linewidth=1.5,
        linestyle="--",
        label="Benchmark",
    )
    axis.axhline(0, color="#555555", linewidth=0.6)
    axis.set_title("Strategy and benchmark", loc="left", fontsize=10.5)
    axis.set_ylabel("Cumulative return")
    axis.yaxis.set_major_formatter(PercentFormatter(1))
    axis.legend(loc="upper left", frameon=False, ncol=2)


def _draw_excess_return(
    axis: plt.Axes,
    timestamps: pd.Series,
    excess_return: pd.Series,
) -> None:
    """用独立坐标轴绘制超额收益并对零轴之间区域填色。"""
    axis.plot(
        timestamps,
        excess_return,
        color=EXCESS_COLOR,
        linewidth=1.6,
        label="Excess",
    )
    axis.fill_between(
        timestamps,
        excess_return,
        0,
        color=EXCESS_COLOR,
        alpha=0.13,
    )
    axis.axhline(0, color="#555555", linewidth=0.7)
    axis.set_title("Excess performance", loc="left", fontsize=10.5)
    axis.set_ylabel("Excess")
    axis.yaxis.set_major_formatter(PercentFormatter(1))


def _draw_drawdowns(
    axis: plt.Axes,
    timestamps: pd.Series,
    strategy_drawdown: pd.Series,
    excess_drawdown: pd.Series,
) -> None:
    """在同一面板对照策略回撤和超额回撤。"""
    axis.plot(
        timestamps,
        strategy_drawdown,
        color=STRATEGY_COLOR,
        linewidth=1.3,
        label="Strategy drawdown",
    )
    axis.fill_between(
        timestamps,
        strategy_drawdown,
        0,
        color=STRATEGY_COLOR,
        alpha=0.12,
    )
    axis.plot(
        timestamps,
        excess_drawdown,
        color=EXCESS_COLOR,
        linewidth=1.3,
        label="Excess drawdown",
    )
    axis.fill_between(
        timestamps,
        excess_drawdown,
        0,
        color=EXCESS_COLOR,
        alpha=0.12,
    )
    axis.axhline(0, color="#555555", linewidth=0.6)
    axis.set_title("Strategy and excess drawdown", loc="left", fontsize=10.5)
    axis.set_ylabel("Drawdown")
    axis.yaxis.set_major_formatter(PercentFormatter(1))
    axis.legend(loc="lower left", frameon=False, ncol=2)


def _draw_active_returns(
    axis: plt.Axes,
    timestamps: pd.Series,
    active_returns: pd.Series,
) -> None:
    """绘制逐期主动收益，并用橙色突出四倍标准差尖峰。"""
    valid_active_returns = active_returns.dropna()
    valid_timestamps = timestamps.loc[valid_active_returns.index]
    active_mean = valid_active_returns.mean()
    active_std = valid_active_returns.std(ddof=1)
    anomaly_threshold = 4 * active_std
    anomalies = (valid_active_returns - active_mean).abs() >= anomaly_threshold
    bar_colors = np.where(anomalies, OUTLIER_COLOR, NEUTRAL_BAR_COLOR)

    axis.bar(
        valid_timestamps,
        valid_active_returns,
        width=1.0,
        color=bar_colors,
        edgecolor="none",
    )
    axis.axhline(0, color="#555555", linewidth=0.7)
    if active_std > 0:
        axis.axhline(
            active_mean + anomaly_threshold,
            color=OUTLIER_COLOR,
            linewidth=0.8,
            linestyle="--",
        )
        axis.axhline(
            active_mean - anomaly_threshold,
            color=OUTLIER_COLOR,
            linewidth=0.8,
            linestyle="--",
        )
    axis.set_title(
        "Active return and concentration spikes (orange: |z| >= 4)",
        loc="left",
        fontsize=10.5,
    )
    axis.set_ylabel("Active return")
    axis.yaxis.set_major_formatter(PercentFormatter(1))


def _draw_rebalance_markers(
    axes: list[plt.Axes],
    actions: pd.DataFrame,
) -> None:
    """用淡竖线标记数量可读的调仓日。"""
    rebalance_dates = pd.DatetimeIndex(actions["date"].drop_duplicates())
    if len(rebalance_dates) > 24:
        return
    for axis in axes:
        for rebalance_date in rebalance_dates:
            axis.axvline(
                rebalance_date,
                color="#9AA7B2",
                linewidth=0.55,
                linestyle=":",
                alpha=0.55,
            )


def _style_time_axes(axes: list[plt.Axes]) -> None:
    """统一四个时序面板的边框、横纵网格和日期格式。"""
    for axis in axes:
        style_axis(axis)
        axis.grid(axis="x", alpha=0.14)
        style_date_axis(axis)


def _return_curves(
    curve: pd.DataFrame,
    mode: str,
) -> tuple[pd.Series, pd.Series, pd.Series]:
    """按 simple 加法或 account 复合口径构造累计收益。"""
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


def _active_returns(curve: pd.DataFrame, mode: str) -> pd.Series:
    """从展示曲线计算与同频基准可比的逐期主动收益。"""
    if mode == "simple":
        strategy_returns = curve["cumulative_return"].diff()
        benchmark_returns = curve["benchmark_cumulative_return"].diff()
    else:
        strategy_returns = curve["nav"].pct_change(fill_method=None)
        benchmark_returns = curve["benchmark_nav"].pct_change(fill_method=None)
    return strategy_returns - benchmark_returns


def _drawdown(cumulative_return: pd.Series, compound: bool) -> pd.Series:
    """按回测模式计算策略或超额收益的完整回撤序列。"""
    if compound:
        nav = 1 + cumulative_return
        return nav.div(nav.cummax()) - 1
    return cumulative_return - cumulative_return.cummax()


def _draw_metrics_table(
    axis: plt.Axes,
    metrics: pd.DataFrame,
    interval: int,
) -> None:
    """按策略、交易和相对表现三组展示核心绩效指标。"""
    metric_row = metrics.loc[
        metrics["rebalance_interval"] == interval
    ].iloc[0]
    metric_blocks = [
        (
            "Strategy",
            [
                ("Annual return", "annual_return"),
                ("Annual volatility", "annual_volatility"),
                ("Sharpe", "sharpe"),
                ("Max drawdown", "max_drawdown"),
            ],
        ),
        (
            "Trading",
            [
                ("Gross total", "gross_total_return"),
                ("Net total", "total_return"),
                ("Annual turnover", "annual_turnover"),
                ("Total cost rate", "total_cost_rate"),
            ],
        ),
        (
            "Relative",
            [
                ("Benchmark return", "benchmark_total_return"),
                ("Excess return", "excess_total_return"),
                ("Tracking error", "tracking_error"),
                ("Information ratio", "information_ratio"),
            ],
        ),
    ]
    percent_metrics = {
        "annual_return",
        "annual_volatility",
        "max_drawdown",
        "gross_total_return",
        "total_return",
        "total_cost_rate",
        "benchmark_total_return",
        "excess_total_return",
        "tracking_error",
    }
    axis.axis("off")
    for block_position, (block_name, block_metrics) in enumerate(metric_blocks):
        left = block_position / 3 + 0.01
        width = 0.31
        axis.text(
            left,
            0.96,
            block_name,
            transform=axis.transAxes,
            fontsize=10.5,
            fontweight="bold",
            color="black",
            verticalalignment="top",
        )
        rows = [
            [
                label,
                _format_metric(metric_row[metric_name], metric_name, percent_metrics),
            ]
            for label, metric_name in block_metrics
        ]
        table = axis.table(
            cellText=rows,
            bbox=[left, 0.02, width, 0.78],
            colWidths=[0.64, 0.36],
            cellLoc="left",
        )
        table.auto_set_font_size(False)
        table.set_fontsize(9.5)
        for (_, column_position), cell in table.get_celld().items():
            cell.set_edgecolor("black")
            cell.set_linewidth(0.6)
            cell.set_facecolor("white")
            cell.get_text().set_color("black")
            if column_position == 1:
                cell.get_text().set_horizontalalignment("right")


def _format_metric(
    value: Any,
    metric_name: str,
    percent_metrics: set[str],
) -> str:
    """按百分比、倍数或普通比率格式化指标表单元格。"""
    if pd.isna(value):
        return "-"
    if metric_name in percent_metrics:
        return f"{value:.1%}"
    if metric_name == "annual_turnover":
        return f"{value:.2f}x"
    return f"{value:.2f}"


def _draw_latest_active_weights(
    axis: plt.Axes,
    latest_active_weights: pd.Series,
) -> None:
    """展示最新调仓日绝对值最大的超配和低配股票。"""
    display_count = min(5, len(latest_active_weights))
    selected_codes = latest_active_weights.nsmallest(display_count).index.union(
        latest_active_weights.nlargest(display_count).index,
        sort=False,
    )
    displayed_weights = latest_active_weights.loc[selected_codes].sort_values()
    colors = np.where(displayed_weights >= 0, POSITIVE_COLOR, NEGATIVE_COLOR)
    axis.barh(displayed_weights.index, displayed_weights, color=colors)
    axis.axvline(0, color="#555555", linewidth=0.7)
    axis.set_title("Latest overweight and underweight", loc="left", fontsize=10.5)
    axis.set_xlabel("Active weight")
    axis.xaxis.set_major_locator(MaxNLocator(nbins=5))
    axis.xaxis.set_major_formatter(PercentFormatter(1))
    style_axis(axis)
    axis.grid(axis="x", alpha=0.18)


def _draw_active_share(axis: plt.Axes, deviation: pd.DataFrame) -> None:
    """绘制 Active Share 时序、均值线和面积。"""
    axis.plot(
        deviation["date"],
        deviation["active_share"],
        color=STRATEGY_COLOR,
        linewidth=1.6,
        marker="o",
        markersize=3,
        label="Active Share",
    )
    axis.fill_between(
        deviation["date"],
        deviation["active_share"],
        0,
        color=STRATEGY_COLOR,
        alpha=0.10,
    )
    mean_active_share = deviation["active_share"].mean()
    axis.axhline(
        mean_active_share,
        color=EXCESS_COLOR,
        linewidth=1.0,
        linestyle="--",
        label=f"Mean {mean_active_share:.1%}",
    )
    axis.set_title("Active Share history", loc="left", fontsize=10.5)
    axis.set_ylabel("Active Share")
    axis.yaxis.set_major_formatter(PercentFormatter(1))
    axis.legend(loc="best", frameon=False, ncol=2)
    style_axis(axis)
    axis.grid(axis="x", alpha=0.18)
    style_date_axis(axis)


def _draw_active_weight_extremes(
    axis: plt.Axes,
    deviation: pd.DataFrame,
) -> None:
    """对照单票最大超配和最大低配时序。"""
    axis.plot(
        deviation["date"],
        deviation["max_overweight"],
        color=POSITIVE_COLOR,
        linewidth=1.5,
        marker="o",
        markersize=3,
        label="Max overweight",
    )
    axis.plot(
        deviation["date"],
        deviation["max_underweight"],
        color=NEGATIVE_COLOR,
        linewidth=1.5,
        marker="o",
        markersize=3,
        label="Max underweight",
    )
    axis.fill_between(
        deviation["date"],
        deviation["max_underweight"],
        deviation["max_overweight"],
        color="#A9BBC8",
        alpha=0.12,
    )
    axis.axhline(0, color="#555555", linewidth=0.7)
    axis.set_title("Single-name active weight range", loc="left", fontsize=10.5)
    axis.set_ylabel("Active weight")
    axis.yaxis.set_major_formatter(PercentFormatter(1))
    axis.legend(loc="best", frameon=False)
    style_axis(axis)
    axis.grid(axis="x", alpha=0.18)
    style_date_axis(axis)


def _draw_target_concentration(
    axis: plt.Axes,
    target_weights: pd.DataFrame,
) -> None:
    """用等效持股数和 Top10 权重占比诊断目标组合集中度。"""
    weight_squares = target_weights.pow(2).sum(axis=1)
    effective_holdings = 1 / weight_squares
    top_ten_share = target_weights.apply(
        lambda weights: weights.nlargest(10).sum(),
        axis=1,
    )

    effective_line = axis.plot(
        target_weights.index,
        effective_holdings,
        color=STRATEGY_COLOR,
        linewidth=1.6,
        marker="o",
        markersize=3,
        label="Effective holdings",
    )[0]
    axis.set_title("Target portfolio concentration", loc="left", fontsize=10.5)
    axis.set_ylabel("Effective holdings")
    style_axis(axis)
    axis.grid(axis="x", alpha=0.18)
    style_date_axis(axis)

    share_axis = axis.twinx()
    top_ten_line = share_axis.plot(
        target_weights.index,
        top_ten_share,
        color=EXCESS_COLOR,
        linewidth=1.4,
        linestyle="--",
        marker="o",
        markersize=3,
        label="Top10 weight share",
    )[0]
    share_axis.set_ylabel("Top10 share", color=EXCESS_COLOR)
    share_axis.yaxis.set_major_formatter(PercentFormatter(1))
    share_axis.spines[["top"]].set_visible(False)
    share_axis.tick_params(axis="y", colors=EXCESS_COLOR)
    axis.legend(
        [effective_line, top_ten_line],
        [effective_line.get_label(), top_ten_line.get_label()],
        loc="best",
        frameon=False,
    )


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
