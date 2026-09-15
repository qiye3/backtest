"""绘制一批因子的相关性、RankIC 与多空收益分布。"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from src.plotter.style import save_figure, style_axis


def plot_overall_evaluation(
    overall_result: Mapping[str, pd.DataFrame],
    settings: Mapping[str, Any],
    output_directory: str | Path,
) -> dict[str, list[Path]]:
    """把三类跨因子统计写入结果根目录下的 overall 目录。"""
    output_directory = Path(output_directory)
    output_directory.mkdir(parents=True, exist_ok=True)
    with plt.rc_context(
        {
            "font.family": settings["font_family"],
            "axes.labelsize": 10,
            "xtick.labelsize": 8,
            "ytick.labelsize": 9,
        }
    ):
        return {
            "factor_correlation": _plot_correlation_heatmap(
                overall_result["factor_correlation"],
                settings,
                output_directory / "factor_correlation_heatmap",
            ),
            "factor_ic": _plot_factor_distribution(
                overall_result["factor_ic"],
                value_column="rank_ic_mean",
                x_label="Mean RankIC",
                title="Cross-factor mean RankIC distribution",
                settings=settings,
                output_stem=output_directory / "factor_ic_distribution",
            ),
            "factor_return": _plot_factor_distribution(
                overall_result["factor_return"],
                value_column="high_minus_low_return",
                x_label="High-minus-low return (bp)",
                title="Cross-factor high-minus-low return distribution",
                settings=settings,
                output_stem=output_directory / "factor_return_distribution",
                basis_points=True,
            ),
        }


def _plot_correlation_heatmap(
    correlation: pd.DataFrame,
    settings: Mapping[str, Any],
    output_stem: Path,
) -> list[Path]:
    """绘制逐日横截面 Spearman 相关的时间均值。"""
    factor_count = len(correlation)
    figure_size = max(settings["width"], 4.0 + factor_count * 0.45)
    figure, axis = plt.subplots(
        figsize=(figure_size, figure_size * 0.8),
        layout="constrained",
    )
    image = axis.imshow(
        correlation.to_numpy(dtype=float),
        cmap="RdYlGn",
        vmin=-1,
        vmax=1,
        aspect="equal",
    )
    axis.set_xticks(np.arange(factor_count), correlation.columns, rotation=45, ha="right")
    axis.set_yticks(np.arange(factor_count), correlation.index)
    axis.set_title("Mean daily cross-sectional Spearman correlation", fontsize=13)
    for row_position in range(factor_count):
        for column_position in range(factor_count):
            correlation_value = correlation.iat[row_position, column_position]
            axis.text(
                column_position,
                row_position,
                f"{correlation_value:.2f}",
                horizontalalignment="center",
                verticalalignment="center",
                fontsize=7,
            )
    figure.colorbar(image, ax=axis, shrink=0.8, label="Spearman correlation")
    return save_figure(figure, output_stem, settings)


def _plot_factor_distribution(
    summary: pd.DataFrame,
    value_column: str,
    x_label: str,
    title: str,
    settings: Mapping[str, Any],
    output_stem: Path,
    basis_points: bool = False,
) -> list[Path]:
    """按未来周期分面绘制每因子一个汇总值的直方图。"""
    horizons = summary[["horizon_value", "horizon_unit"]].drop_duplicates()
    figure, axes = plt.subplots(
        len(horizons),
        1,
        figsize=(
            settings["width"],
            settings["row_height"] * len(horizons),
        ),
        squeeze=False,
        layout="constrained",
    )
    figure.suptitle(title, fontsize=13, fontweight="bold")
    for axis, horizon in zip(axes[:, 0], horizons.itertuples(index=False)):
        horizon_values = summary.loc[
            (summary["horizon_value"] == horizon.horizon_value)
            & (summary["horizon_unit"] == horizon.horizon_unit),
            value_column,
        ].dropna()
        plot_values = horizon_values * 10_000 if basis_points else horizon_values
        bin_count = min(20, max(5, int(np.ceil(np.sqrt(len(plot_values))))))
        axis.hist(
            plot_values,
            bins=bin_count,
            color="#5B7FA3",
            edgecolor="white",
            alpha=0.9,
        )
        axis.axvline(plot_values.mean(), color="#C23B32", linewidth=1.4)
        axis.set_title(_horizon_label(horizon.horizon_value, horizon.horizon_unit))
        axis.set_xlabel(x_label)
        axis.set_ylabel("Factor count")
        axis.text(
            0.98,
            0.94,
            (
                f"mean={plot_values.mean():.4g}  "
                f"median={plot_values.median():.4g}  N={len(plot_values)}"
            ),
            transform=axis.transAxes,
            horizontalalignment="right",
            verticalalignment="top",
            fontsize=8,
        )
        style_axis(axis)
        axis.grid(axis="x", alpha=0.18)
    return save_figure(figure, output_stem, settings)


def _horizon_label(horizon_value: int, horizon_unit: str) -> str:
    """格式化整体评价分面使用的未来收益周期。"""
    unit = "trading days" if horizon_unit == "trading_days" else "weeks"
    return f"{int(horizon_value)} {unit}"
