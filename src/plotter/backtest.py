"""绘制 simple 累计收益和 account 独立账户净值。"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib.ticker import PercentFormatter

from src.plotter.style import (
    group_colors,
    group_labels,
    save_figure,
    set_figure_title,
    style_axis,
    style_date_axis,
)

_METRIC_LABELS = {
    "annual_return": "Annual return",
    "annual_volatility": "Annual volatility",
    "sharpe": "Sharpe",
    "max_drawdown": "Max drawdown",
    "annual_turnover": "Annual turnover",
    "annual_cost_rate": "Annual cost rate",
    "total_cost_rate": "Total cost rate",
    "net_total_return": "Net total return",
    "gross_total_return": "Gross total return",
    "benchmark_total_return": "Benchmark return",
    "excess_total_return": "Excess return",
    "tracking_error": "Tracking error",
    "information_ratio": "Information ratio",
}
_PERCENT_METRICS = {
    "annual_return",
    "annual_volatility",
    "max_drawdown",
    "annual_cost_rate",
    "total_cost_rate",
    "net_total_return",
    "gross_total_return",
    "benchmark_total_return",
    "excess_total_return",
    "tracking_error",
}


def plot_backtest(
    factor_name: str,
    backtest_result: Mapping[str, Any],
    mode: str,
    settings: Mapping[str, Any],
    output_stem: Path,
) -> list[Path]:
    """按调仓周期绘制回测曲线，并为 simple 模式附加指标表。"""
    periods = sorted(backtest_result["periods"])
    rebalance_frequency = backtest_result["rebalance_frequency"]
    plot_settings = settings[mode]
    figure, plot_axes, table_axis = _create_backtest_axes(
        period_count=len(periods),
        mode=mode,
        settings=settings,
        plot_settings=plot_settings,
    )
    title_suffix = (
        "Simple cumulative returns"
        if mode == "simple"
        else "Independent account NAV"
    )
    set_figure_title(
        figure,
        f"{factor_name} | {title_suffix}",
        settings,
    )

    legend_handles = []
    for axis, interval in zip(plot_axes, periods):
        handles = _draw_period_curves(
            axis=axis,
            period_result=backtest_result["periods"][interval],
            definitions=backtest_result["definitions"],
            rebalance_frequency=rebalance_frequency,
            rebalance_interval=interval,
            mode=mode,
            curve_frequency=settings["curve_frequency"],
            plot_settings=plot_settings,
        )
        if not legend_handles:
            legend_handles = handles
        if mode == "account":
            axis.legend(
                loc="upper left",
                ncol=min(settings["legend_columns"], len(handles)),
                frameon=False,
                fontsize=8,
            )
        style_axis(axis)
        style_date_axis(axis)

    if mode == "simple":
        plot_axes[0].legend(
            legend_handles,
            [handle.get_label() for handle in legend_handles],
            loc="upper left",
            ncol=min(11, len(legend_handles)),
            frameon=False,
            fontsize=8,
        )
        _draw_summary_table(
            table_axis=table_axis,
            metrics=backtest_result["metrics"],
            periods=periods,
            rebalance_frequency=rebalance_frequency,
            plot_settings=plot_settings,
        )
    return save_figure(figure, output_stem, settings)


def _create_backtest_axes(
    period_count: int,
    mode: str,
    settings: Mapping[str, Any],
    plot_settings: Mapping[str, Any],
) -> tuple[plt.Figure, list[plt.Axes], plt.Axes | None]:
    """按模式和布局创建曲线面板与 simple 指标表区域。"""
    if mode == "simple":
        figure = plt.figure(
            figsize=(
                settings["width"],
                settings["row_height"] * period_count + 1.8,
            ),
            layout="constrained",
        )
        grid = figure.add_gridspec(
            period_count + 1,
            1,
            height_ratios=[1] * period_count + [0.45],
        )
        plot_axes = [
            figure.add_subplot(grid[position, 0])
            for position in range(period_count)
        ]
        return figure, plot_axes, figure.add_subplot(grid[period_count, 0])

    rows, columns = (
        (period_count, 1)
        if plot_settings["layout"] == "rows"
        else (1, period_count)
    )
    figure, axes = plt.subplots(
        rows,
        columns,
        figsize=(
            settings["width"]
            if columns == 1
            else settings["width"] * 1.4,
            settings["row_height"] * rows + 0.7,
        ),
        squeeze=False,
        layout="constrained",
    )
    return figure, list(axes.flat), None


def _draw_period_curves(
    axis: plt.Axes,
    period_result: Mapping[str, Any],
    definitions: pd.DataFrame,
    rebalance_frequency: str,
    rebalance_interval: int,
    mode: str,
    curve_frequency: str,
    plot_settings: Mapping[str, Any],
) -> list[Any]:
    """使用统一分组颜色绘制一个调仓周期的费后曲线。"""
    palette = group_colors(plot_settings["group_colors"], len(definitions))
    labels, _ = group_labels(definitions)
    curve_key = "cumulative_return" if mode == "simple" else "nav"
    benchmark_key = (
        "benchmark_cumulative_return"
        if mode == "simple"
        else "benchmark_nav"
    )
    handles = []
    benchmark_curve = None
    for group_position, definition in enumerate(
        definitions.itertuples(index=False)
    ):
        curves = period_result["groups"][definition.group_id]["curves"]
        if curve_frequency not in curves:
            raise ValueError(
                f"{_rebalance_label(rebalance_frequency, rebalance_interval)}/"
                f"{definition.group_id} 不包含 "
                f"{curve_frequency} 曲线"
            )
        curve = curves[curve_frequency]
        line_width = 1.3
        if mode == "simple":
            line_width = (
                1.65
                if group_position in {0, len(definitions) - 1}
                else 1.15
            )
        (line,) = axis.plot(
            curve["timestamp"],
            curve[curve_key],
            color=palette[group_position],
            linewidth=line_width,
            linestyle="-",
            label=labels[group_position],
        )
        handles.append(line)
        if benchmark_curve is None:
            benchmark_curve = curve

    (benchmark_line,) = axis.plot(
        benchmark_curve["timestamp"],
        benchmark_curve[benchmark_key],
        color=plot_settings["benchmark_color"],
        linewidth=1.9,
        linestyle="--",
        label="Benchmark",
        zorder=5,
    )
    handles.append(benchmark_line)
    axis.axhline(0 if mode == "simple" else 1, color="#555555", linewidth=0.6)
    if mode == "simple":
        axis.yaxis.set_major_formatter(PercentFormatter(1))
    axis.set_ylabel(
        "Cumulative return (sum)"
        if mode == "simple"
        else "NAV (initial = 1)"
    )
    axis.set_title(
        f"{_rebalance_label(rebalance_frequency, rebalance_interval)} | "
        f"{curve_frequency} observations | after costs",
        fontsize=10,
    )
    return handles


def _draw_summary_table(
    table_axis: plt.Axes,
    metrics: pd.DataFrame,
    periods: Sequence[int],
    rebalance_frequency: str,
    plot_settings: Mapping[str, Any],
) -> None:
    """绘制 simple 回测指定分位组的跨周期指标摘要。"""
    table_axis.axis("off")
    table_axis.set_title(
        f"{_summary_group_label(plot_settings['summary_quantile'])} summary"
        " | displayed metrics are configurable",
        loc="left",
        fontsize=9,
        pad=6,
    )
    metric_names = plot_settings["metric_columns"]
    table = table_axis.table(
        cellText=_summary_rows(
            metrics,
            periods,
            rebalance_frequency,
            plot_settings,
        ),
        colLabels=[
            "Rebalance",
            *[_METRIC_LABELS[name] for name in metric_names],
        ],
        loc="center",
        cellLoc="center",
    )
    table.auto_set_font_size(False)
    table.set_fontsize(8)
    table.scale(1, 1.25)
    for (row, _), cell in table.get_celld().items():
        cell.set_facecolor("white")
        cell.set_edgecolor("#263238")
        cell.set_linewidth(0.55)
        if row == 0:
            cell.set_text_props(fontweight="bold")


def _summary_rows(
    metrics: pd.DataFrame,
    periods: Sequence[int],
    rebalance_frequency: str,
    plot_settings: Mapping[str, Any],
) -> list[list[str]]:
    """提取摘要分位组并格式化为表格行。"""
    quantile_lower, quantile_upper = map(
        float,
        plot_settings["summary_quantile"],
    )
    rows = []
    for interval in periods:
        selected = metrics[
            (metrics["rebalance_frequency"] == rebalance_frequency)
            & (metrics["rebalance_interval"] == interval)
            & np.isclose(metrics["quantile_lower"], quantile_lower)
            & np.isclose(metrics["quantile_upper"], quantile_upper)
        ]
        metric_values = selected.iloc[0] if len(selected) == 1 else None
        rows.append(
            [
                _rebalance_label(rebalance_frequency, interval),
                *[
                    _format_metric(name, metric_values[name])
                    if metric_values is not None
                    else "N/A"
                    for name in plot_settings["metric_columns"]
                ],
            ]
        )
    return rows


def _rebalance_label(frequency: str, interval: int) -> str:
    """把日度或周度调仓间隔转换为图标题和表格使用的英文标签。"""
    if frequency == "daily":
        unit = "trading day" if interval == 1 else "trading days"
    else:
        unit = "week" if interval == 1 else "weeks"
    return f"Every {interval} {unit}"


def _format_metric(name: str, value: Any) -> str:
    """按百分比、换手倍数或普通小数格式化指标。"""
    if pd.isna(value):
        return "N/A"
    if name in _PERCENT_METRICS:
        return f"{value:.1%}"
    if name == "annual_turnover":
        return f"{value:.2f}x"
    return f"{value:.2f}"


def _summary_group_label(summary_quantile: Sequence[float]) -> str:
    """生成人类可读的摘要分位组名称。"""
    quantile_lower, quantile_upper = map(float, summary_quantile)
    if np.isclose(quantile_lower, 0.9) and np.isclose(quantile_upper, 1):
        return "q0.1 / Q10"
    return f"quantile [{quantile_lower:.2f}, {quantile_upper:.2f}]"
