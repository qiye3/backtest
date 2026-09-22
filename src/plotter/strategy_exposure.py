"""绘制策略集中度、主动行业和主动风格的长期总览。"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib.ticker import PercentFormatter

from src.plotter.style import save_figure, set_figure_title, style_axis

STRATEGY_COLOR = "#174A73"
BENCHMARK_COLOR = "#777777"
TOP10_COLOR = "#C66B2E"


def plot_strategy_risk_exposure(
    strategy_name: str,
    concentration: pd.DataFrame,
    industry_exposure: pd.DataFrame,
    style_exposure: pd.DataFrame,
    settings: Mapping[str, Any],
    output_stem: Path,
    rebalance_label: str,
) -> list[Path]:
    """绘制一张三联长期风险暴露总览。"""
    figure = plt.figure(
        figsize=(settings["width"], settings["row_height"] * 3.0),
        layout="constrained",
    )
    grid = figure.add_gridspec(3, 1, height_ratios=[1.05, 1.8, 1.0])
    concentration_axis = figure.add_subplot(grid[0, 0])
    industry_axis = figure.add_subplot(grid[1, 0])
    style_axis = figure.add_subplot(grid[2, 0])

    set_figure_title(
        figure,
        f"{strategy_name} | Risk exposure overview",
        settings,
        annotation=rebalance_label,
    )
    _draw_concentration(concentration_axis, concentration)
    _draw_exposure_heatmap(
        industry_axis,
        industry_exposure,
        row_field="industry_code",
        value_field="active_weight",
        title="Active industry weight",
        colorbar_label="Active weight",
        percent_colorbar=True,
        sort_by_activity=True,
    )
    _draw_exposure_heatmap(
        style_axis,
        style_exposure,
        row_field="style_name",
        value_field="active_exposure",
        title="Active style exposure",
        colorbar_label="Active z-score",
        percent_colorbar=False,
        sort_by_activity=False,
    )
    return save_figure(figure, output_stem, settings)


def _draw_concentration(axis: plt.Axes, concentration: pd.DataFrame) -> None:
    """对照策略与基准有效持股数，并补充策略 Top10 占比。"""
    dates = pd.to_datetime(concentration["date"])
    axis.plot(
        dates,
        concentration["effective_holdings"],
        color=STRATEGY_COLOR,
        linewidth=1.8,
        label="Strategy effective holdings",
    )
    axis.plot(
        dates,
        concentration["benchmark_effective_holdings"],
        color=BENCHMARK_COLOR,
        linewidth=1.4,
        linestyle="--",
        label="Benchmark effective holdings",
    )
    axis.set_title("Stock concentration", loc="left", fontsize=10.5)
    axis.set_ylabel("Effective holdings")
    style_axis(axis)

    top10_axis = axis.twinx()
    top10_axis.plot(
        dates,
        concentration["top10_share"],
        color=TOP10_COLOR,
        linewidth=1.35,
        label="Strategy Top10 share",
    )
    top10_axis.set_ylabel("Top10 share")
    top10_axis.yaxis.set_major_formatter(PercentFormatter(1))
    top10_axis.spines["top"].set_visible(False)

    handles, labels = axis.get_legend_handles_labels()
    top10_handles, top10_labels = top10_axis.get_legend_handles_labels()
    axis.legend(
        handles + top10_handles,
        labels + top10_labels,
        loc="upper left",
        frameon=False,
        ncol=3,
    )


def _draw_exposure_heatmap(
    axis: plt.Axes,
    exposure: pd.DataFrame,
    row_field: str,
    value_field: str,
    title: str,
    colorbar_label: str,
    percent_colorbar: bool,
    sort_by_activity: bool,
) -> None:
    """将长表暴露转换为以调仓日为横轴的零中心热力图。"""
    heatmap = exposure.pivot(
        index=row_field,
        columns="date",
        values=value_field,
    )
    if sort_by_activity:
        row_order = heatmap.abs().mean(axis=1).sort_values(ascending=False).index
        heatmap = heatmap.loc[row_order]
    color_limit = _robust_symmetric_limit(heatmap)
    color_map = plt.get_cmap("RdBu").with_extremes(bad="#EEEEEE")
    image = axis.imshow(
        heatmap.to_numpy(dtype=float),
        aspect="auto",
        interpolation="nearest",
        cmap=color_map,
        vmin=-color_limit,
        vmax=color_limit,
    )
    axis.set_title(title, loc="left", fontsize=10.5)
    axis.set_yticks(np.arange(len(heatmap.index)))
    axis.set_yticklabels(heatmap.index.astype(str), fontsize=8)
    _set_heatmap_date_ticks(axis, pd.DatetimeIndex(heatmap.columns))
    axis.set_xlabel("Rebalance date")
    axis.tick_params(length=0)
    for spine in axis.spines.values():
        spine.set_visible(False)

    colorbar = axis.figure.colorbar(image, ax=axis, pad=0.012, fraction=0.025)
    colorbar.set_label(colorbar_label)
    if percent_colorbar:
        colorbar.ax.yaxis.set_major_formatter(PercentFormatter(1))


def _robust_symmetric_limit(heatmap: pd.DataFrame) -> float:
    """用绝对暴露 98% 分位生成对称色阶，截断只影响显示。"""
    absolute_values = np.abs(heatmap.to_numpy(dtype=float))
    finite_values = absolute_values[np.isfinite(absolute_values)]
    if finite_values.size == 0:
        return 1.0
    color_limit = float(np.quantile(finite_values, 0.98))
    return color_limit if color_limit > 0 else 1.0


def _set_heatmap_date_ticks(axis: plt.Axes, dates: pd.DatetimeIndex) -> None:
    """完整保留热力格子，仅降低过密日期标签数量。"""
    tick_step = max(1, int(np.ceil(len(dates) / 10)))
    tick_positions = np.arange(0, len(dates), tick_step)
    axis.set_xticks(tick_positions)
    axis.set_xticklabels(
        [dates[position].strftime("%Y-%m-%d") for position in tick_positions],
        rotation=20,
        horizontalalignment="right",
        fontsize=8,
    )
