"""绘制跨因子相关性、RankIC、收益分布与四周分组收益。"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from src.plotter.distribution import (
    distribution_sampling_label,
    plot_distribution_axis,
)
from src.plotter.evaluation import plot_group_return_bars
from src.plotter.style import (
    group_colors,
    save_figure,
    set_figure_title,
    style_axis,
)

GROUP_RETURN_HORIZON_WEEKS = 4


def plot_overall_evaluation(
    overall_result: Mapping[str, pd.DataFrame],
    settings: Mapping[str, Any],
    output_directory: str | Path,
    evaluation_results: Mapping[str, Mapping[str, Any]] | None = None,
    factor_panels: Mapping[str, pd.DataFrame] | None = None,
    evaluation_settings: Mapping[str, Any] | None = None,
) -> dict[str, list[Path]]:
    """把跨因子统计图写入结果根目录下的 overall 目录。"""
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
        output_paths = {
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
        group_grid_settings = settings["overall"]["group_return_grid"]
        if group_grid_settings["enabled"]:
            output_paths["group_return_grid"] = plot_group_return_grid(
                evaluation_results=evaluation_results,
                settings=settings,
                output_stem=output_directory / "group_return_4week_grid",
            )
        distribution_grid_settings = settings["overall"][
            "factor_distribution_grid"
        ]
        if distribution_grid_settings["enabled"]:
            output_paths[
                "factor_distribution_grid"
            ] = plot_factor_distribution_grid(
                factor_panels=factor_panels,
                evaluation_results=evaluation_results,
                settings=settings,
                sampling_settings=evaluation_settings,
                output_stem=output_directory / "factor_distribution_grid",
            )
        return output_paths


def plot_factor_distribution_grid(
    factor_panels: Mapping[str, pd.DataFrame] | None,
    evaluation_results: Mapping[str, Mapping[str, Any]] | None,
    settings: Mapping[str, Any],
    sampling_settings: Mapping[str, Any] | None,
    output_stem: Path,
) -> list[Path]:
    """将各因子在实际评价截面上的值分布汇集为一张大图。"""
    if factor_panels is None or evaluation_results is None:
        raise ValueError("因子分布汇总图需要 factor_panels 和 evaluation_results")

    factor_names = list(factor_panels)
    columns = min(
        settings["overall"]["factor_distribution_grid"]["columns"],
        len(factor_names),
    )
    rows = (len(factor_names) + columns - 1) // columns
    figure, axes = plt.subplots(
        rows,
        columns,
        figsize=(max(settings["width"], columns * 3.4), rows * 3.0 + 0.8),
        squeeze=False,
        layout="constrained",
    )
    set_figure_title(
        figure,
        "Factor Distributions",
        settings,
        annotation=(
            distribution_sampling_label(sampling_settings)
            if sampling_settings is not None
            else None
        ),
    )

    legend_handles = None
    legend_labels = None
    for position, factor_name in enumerate(factor_names):
        axis = axes.flat[position]
        sampled_panel = _sample_evaluation_factor_panel(
            factor_panels[factor_name],
            evaluation_results[factor_name],
        )
        distribution_summary = plot_distribution_axis(
            axis,
            factor_name,
            sampled_panel,
            settings["distribution"],
        )
        statistics = distribution_summary["statistics"]
        axis.set_title(factor_name, fontsize=10)
        axis.set_xlabel("Factor value")
        if position % columns == 0:
            axis.set_ylabel(
                "Density"
                if settings["distribution"]["density"]
                else "Count"
            )
        axis.text(
            0.98,
            0.95,
            (
                f"N={distribution_summary['displayed_count']:,}\n"
                f"mean={statistics['Mean']:.3g}\n"
                f"median={statistics['Median']:.3g}"
            ),
            transform=axis.transAxes,
            horizontalalignment="right",
            verticalalignment="top",
            fontsize=7,
            bbox={
                "facecolor": "white",
                "edgecolor": "none",
                "alpha": 0.75,
            },
        )
        if legend_handles is None:
            legend_handles, legend_labels = axis.get_legend_handles_labels()

    for axis in axes.flat[len(factor_names) :]:
        axis.set_visible(False)
    figure.legend(
        legend_handles,
        legend_labels,
        loc="outside lower center",
        ncol=len(legend_labels),
        frameon=False,
        fontsize=8,
    )
    return save_figure(figure, output_stem, settings)


def _sample_evaluation_factor_panel(
    factor_panel: pd.DataFrame,
    evaluation_result: Mapping[str, Any],
) -> pd.DataFrame:
    """按 evaluation 实际使用的因子来源日抽取分布样本。"""
    factor_dates = pd.DatetimeIndex(
        evaluation_result["detail"]["factor_date"]
    ).unique().rename(factor_panel.index.name)
    return factor_panel.reindex(factor_dates.sort_values())


def plot_group_return_grid(
    evaluation_results: Mapping[str, Mapping[str, Any]] | None,
    settings: Mapping[str, Any],
    output_stem: Path,
) -> list[Path]:
    """将每个因子的四周分组收益汇集为一张可横向比较的大图。"""
    if evaluation_results is None:
        raise ValueError("四周分组收益汇总图需要 evaluation_results")

    factor_summaries = _four_week_group_summaries(evaluation_results)
    columns = min(
        settings["overall"]["group_return_grid"]["columns"],
        len(factor_summaries),
    )
    rows = (len(factor_summaries) + columns - 1) // columns
    figure, axes = plt.subplots(
        rows,
        columns,
        figsize=(max(settings["width"], columns * 3.4), rows * 3.1 + 0.5),
        squeeze=False,
        layout="constrained",
    )
    figure.suptitle("4-Week Group Returns by Factor", fontsize=14)
    evaluation_settings = settings["evaluation"]
    shared_y_axis = settings["overall"]["group_return_grid"][
        "share_y_axis"
    ]
    if shared_y_axis:
        all_returns = pd.concat(
            [summary["group_return"] for _, _, summary in factor_summaries],
            ignore_index=True,
        ).dropna()
        lower_limit = min(float(all_returns.min()), 0.0)
        upper_limit = max(float(all_returns.max()), 0.0)
        padding = max((upper_limit - lower_limit) * 0.15, 0.002)
        shared_limits = (lower_limit - padding, upper_limit + padding)

    for position, (factor_name, definitions, summary) in enumerate(
        factor_summaries
    ):
        axis = axes.flat[position]
        palette = group_colors(
            evaluation_settings["group_colors"],
            len(definitions),
        )
        plot_group_return_bars(
            axis=axis,
            definitions=definitions,
            summary=summary,
            palette=palette,
            title=factor_name,
        )
        axis.tick_params(axis="x", labelrotation=45)
        for tick_label in axis.get_xticklabels():
            tick_label.set_horizontalalignment("right")
        for value_label in axis.texts:
            value_label.set_rotation(90)
            value_label.set_fontsize(6)
        if shared_y_axis:
            axis.set_ylim(shared_limits)
        if position % columns:
            axis.set_ylabel("")

    for axis in axes.flat[len(factor_summaries) :]:
        axis.set_visible(False)
    return save_figure(figure, output_stem, settings)


def _four_week_group_summaries(
    evaluation_results: Mapping[str, Mapping[str, Any]],
) -> list[tuple[str, pd.DataFrame, pd.DataFrame]]:
    """按输入顺序提取每个因子的四周分组定义和收益。"""
    factor_summaries = []
    for factor_name, result in evaluation_results.items():
        summary = result["summary"]
        selected = summary.loc[
            (summary["horizon_value"] == GROUP_RETURN_HORIZON_WEEKS)
            & (summary["horizon_unit"] == "weeks")
        ]
        if selected.empty:
            raise ValueError(f"因子 {factor_name} 缺少 4 weeks 分组收益")
        factor_summaries.append(
            (factor_name, result["definitions"], selected)
        )
    if not factor_summaries:
        raise ValueError("四周分组收益汇总图没有可绘制的因子")
    return factor_summaries


def _plot_correlation_heatmap(
    correlation: pd.DataFrame,
    settings: Mapping[str, Any],
    output_stem: Path,
) -> list[Path]:
    """绘制逐日横截面 Spearman 相关的时间均值。"""
    factor_count = len(correlation)
    figure_size = min(30.0, max(settings["width"], 4.0 + factor_count * 0.18))
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
    if factor_count <= 40:
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
    facet_columns = ["horizon_value", "horizon_unit"]
    if "target_type" in summary:
        facet_columns.append("target_type")
    horizons = summary[facet_columns].drop_duplicates()
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
        selected = (
            (summary["horizon_value"] == horizon.horizon_value)
            & (summary["horizon_unit"] == horizon.horizon_unit)
        )
        target_type = getattr(horizon, "target_type", None)
        if target_type is not None:
            selected &= summary["target_type"] == target_type
        horizon_values = summary.loc[selected, value_column].dropna()
        plot_values = horizon_values * 10_000 if basis_points else horizon_values
        axis.hist(
            plot_values,
            bins=settings["distribution"]["overall_bins"],
            color="#5B7FA3",
            edgecolor="white",
            alpha=0.9,
        )
        axis.axvline(plot_values.mean(), color="#C23B32", linewidth=1.4)
        facet_title = _horizon_label(horizon.horizon_value, horizon.horizon_unit)
        if target_type is not None:
            facet_title = f"{facet_title} · {target_type}"
        axis.set_title(facet_title)
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
