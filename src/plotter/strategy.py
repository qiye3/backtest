"""绘制策略目标权重与基准的主动偏离诊断。"""

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


