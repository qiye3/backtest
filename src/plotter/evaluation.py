"""绘制各预测周期的分组收益与 IC 时间序列。"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib.ticker import FuncFormatter

from src.plotter.style import (
    group_colors,
    group_labels,
    save_figure,
    set_figure_title,
    style_axis,
    style_date_axis,
)

GROUPS_PER_TABLE_BLOCK = 12


def plot_evaluation(
    factor_name: str,
    group_return_result: Mapping[str, Any],
    settings: Mapping[str, Any],
    output_stem: Path,
    evaluation_settings: Mapping[str, Any] | None = None,
) -> list[Path]:
    """每个未来收益周期绘制一组收益柱图和一组 IC 曲线。"""
    definitions = group_return_result["definitions"]
    summary = group_return_result["summary"]
    ic_series = group_return_result["ic"]
    horizons = summary[
        ["horizon_value", "horizon_unit"]
    ].drop_duplicates()
    plot_settings = settings["evaluation"]
    palette = group_colors(
        plot_settings["group_colors"],
        len(definitions),
    )
    table_block_count = max(
        1,
        (len(definitions) + GROUPS_PER_TABLE_BLOCK - 1)
        // GROUPS_PER_TABLE_BLOCK,
    )
    plot_row_height = settings["row_height"]
    table_row_height = 0.62 * table_block_count
    figure = plt.figure(
        figsize=(
            settings["width"],
            plot_row_height * len(horizons) + table_row_height + 0.5,
        ),
        layout="constrained",
    )
    height_ratios = [plot_row_height] * len(horizons) + [table_row_height]
    grid = figure.add_gridspec(
        len(horizons) + 1,
        2,
        height_ratios=height_ratios,
        width_ratios=[1, 1],
    )
    axes = np.empty((len(horizons), 2), dtype=object)
    for row_position in range(len(horizons)):
        axes[row_position, 0] = figure.add_subplot(grid[row_position, 0])
        axes[row_position, 1] = figure.add_subplot(grid[row_position, 1])
    table_axis = figure.add_subplot(grid[-1, :])
    set_figure_title(
        figure,
        f"{factor_name} | Forward-return evaluation",
        settings,
        annotation=(
            _evaluation_config_label(evaluation_settings)
            if evaluation_settings is not None
            else None
        ),
    )

    for row_position, horizon in enumerate(horizons.itertuples(index=False)):
        horizon_mask = (
            (summary["horizon_value"] == horizon.horizon_value)
            & (summary["horizon_unit"] == horizon.horizon_unit)
        )
        horizon_label = _horizon_label(
            horizon.horizon_value,
            horizon.horizon_unit,
        )
        group_column = 0 if plot_settings["group_panel"] == "left" else 1
        bar_axis = axes[row_position, group_column]
        line_axis = axes[row_position, 1 - group_column]
        group_observations = (
            summary[horizon_mask]
            .set_index("group_id")
            .reindex(definitions["group_id"])
        )
        bars = bar_axis.bar(
            np.arange(len(definitions)),
            group_observations["group_return"],
            color=palette,
            width=0.8,
        )
        labels, compact_labels = group_labels(definitions)
        rotate_labels = not compact_labels
        bar_axis.set_xticks(
            np.arange(len(definitions)),
            labels,
            rotation=35 if rotate_labels else 0,
            horizontalalignment="right" if rotate_labels else "center",
            fontsize=8,
        )
        bar_axis.yaxis.set_major_formatter(
            FuncFormatter(lambda value, _: f"{value * 10_000:g}bp")
        )
        bar_axis.axhline(0, color="#555555", linewidth=0.7)
        bar_axis.set_title(
            f"{horizon_label} | groups: "
            f"{group_observations['group_return_agg'].iloc[0]}, dates: "
            f"{group_observations['time_return_agg'].iloc[0]}",
            fontsize=10,
        )
        bar_axis.set_ylabel("Aggregated forward return (bp)")
        for group_position in np.flatnonzero(
            group_observations["group_return"].isna().to_numpy()
        ):
            bar_axis.text(
                group_position,
                0,
                "N/A",
                horizontalalignment="center",
                verticalalignment="bottom",
                fontsize=8,
            )
        finite_returns = group_observations["group_return"].dropna().abs()
        label_offset = max(
            float(finite_returns.max()) if len(finite_returns) else 0.0,
            0.002,
        ) * 0.045
        for bar, value in zip(bars, group_observations["group_return"]):
            if pd.notna(value):
                bar_axis.text(
                    bar.get_x() + bar.get_width() / 2,
                    value + label_offset,
                    f"{value * 10_000:.2f}bp",
                    horizontalalignment="center",
                    verticalalignment="bottom",
                    fontsize=7,
                )
        bar_axis.margins(y=0.18)

        ic_horizon_mask = (
            (ic_series["horizon_value"] == horizon.horizon_value)
            & (ic_series["horizon_unit"] == horizon.horizon_unit)
        )
        horizon_ic = ic_series[ic_horizon_mask]
        if plot_settings["rank_ic_view"] == "monthly":
            _plot_monthly_rank_ic(line_axis, horizon_ic, horizon_label)
        else:
            _plot_sampling_ic(
                line_axis,
                horizon_ic,
                horizon_label,
                plot_settings,
            )
        style_axis(bar_axis)
        style_axis(line_axis)
        style_date_axis(line_axis)
    _plot_group_size_table(
        table_axis,
        definitions,
        _shared_mean_group_sizes(group_return_result["detail"], definitions),
    )
    return save_figure(figure, output_stem, settings)


def _plot_group_size_table(
    axis: plt.Axes,
    definitions: pd.DataFrame,
    mean_group_sizes: pd.Series,
) -> None:
    """按实际分组定义分行展示评价期内的平均股票数。"""
    axis.axis("off")
    table_rows = []
    for start_position in range(0, len(definitions), GROUPS_PER_TABLE_BLOCK):
        block = definitions.iloc[
            start_position : start_position + GROUPS_PER_TABLE_BLOCK
        ]
        group_headers = block["label"].astype(str).tolist()
        mean_sizes = mean_group_sizes.reindex(block["group_id"])
        size_labels = [
            f"{mean_size:.1f}" if pd.notna(mean_size) else "N/A"
            for mean_size in mean_sizes
        ]
        table_rows.append(["Group", *group_headers])
        table_rows.append(["Mean stocks", *size_labels])

    # 固定预留默认十二组宽度，更多自定义分组再换到下一块。
    column_count = GROUPS_PER_TABLE_BLOCK + 1
    padded_rows = [
        row + [""] * (column_count - len(row))
        for row in table_rows
    ]
    table = axis.table(
        cellText=padded_rows,
        cellLoc="center",
        bbox=[0, 0, 1, 1],
    )
    table.auto_set_font_size(False)
    table.set_fontsize(7.5)
    for (_, column_position), cell in table.get_celld().items():
        cell.set_facecolor("white")
        cell.set_edgecolor("#333333")
        cell.set_linewidth(0.6)
        if column_position == 0:
            cell.set_text_props(weight="bold")


def _shared_mean_group_sizes(
    detail: pd.DataFrame,
    definitions: pd.DataFrame,
) -> pd.Series:
    """忽略重复预测周期，统计每个采样日各组的平均股票数。"""
    unique_group_sizes = detail[
        ["date", "group_id", "n_group_stocks"]
    ].drop_duplicates(["date", "group_id"])
    return (
        unique_group_sizes.groupby("group_id", sort=False)["n_group_stocks"]
        .mean()
        .reindex(definitions["group_id"])
    )


def _plot_sampling_ic(
    axis: plt.Axes,
    horizon_ic: pd.DataFrame,
    horizon_label: str,
    plot_settings: Mapping[str, Any],
) -> None:
    """保留逐评价日 Pearson IC 与 Spearman RankIC 曲线视图。"""
    axis.plot(
        horizon_ic["date"],
        horizon_ic["ic"],
        label="IC (Pearson)",
        color=plot_settings["ic_color"],
        linewidth=1.2,
        marker="o",
        markersize=2.0,
    )
    axis.plot(
        horizon_ic["date"],
        horizon_ic["rank_ic"],
        label="RankIC (Spearman)",
        color=plot_settings["rank_ic_color"],
        linewidth=1.4,
    )
    axis.axhline(0, color="#555555", linewidth=0.7)
    axis.set_ylim(-1.05, 1.05)
    axis.set_title(f"{horizon_label} | sampling-date IC", fontsize=10)
    axis.set_ylabel("Correlation")
    axis.legend(loc="upper right", frameon=False, ncol=2, fontsize=8)


def _plot_monthly_rank_ic(
    axis: plt.Axes,
    horizon_ic: pd.DataFrame,
    horizon_label: str,
) -> None:
    """绘制月均 RankIC 柱和右轴累计 RankIC。"""
    monthly_rank_ic = _monthly_rank_ic(horizon_ic)
    month_dates = monthly_rank_ic.index.to_timestamp()
    bar_colors = np.where(
        monthly_rank_ic.to_numpy() >= 0,
        "#6F93BA",
        "#E86B68",
    )
    bars = axis.bar(
        month_dates,
        monthly_rank_ic,
        width=20,
        color=bar_colors,
        label="Monthly RankIC",
    )
    axis.axhline(0, color="#555555", linewidth=0.7)
    axis.set_title(f"{horizon_label} | monthly mean RankIC", fontsize=10)
    axis.set_ylabel("Monthly RankIC")

    cumulative_axis = axis.twinx()
    cumulative_line = cumulative_axis.plot(
        month_dates,
        monthly_rank_ic.cumsum(),
        color="#222222",
        linewidth=1.8,
        label="Cumulative RankIC",
    )[0]
    cumulative_axis.set_ylabel("Cumulative RankIC")
    cumulative_axis.axhline(
        0,
        color="#777777",
        linewidth=0.8,
        linestyle="--",
    )
    cumulative_axis.grid(False)
    cumulative_axis.spines["top"].set_visible(False)
    axis.legend(
        [bars, cumulative_line],
        ["Monthly RankIC", "Cumulative RankIC"],
        loc="upper left",
        frameon=False,
        fontsize=8,
    )

    rank_ic_standard_deviation = monthly_rank_ic.std(ddof=1)
    rank_ic_ir = (
        monthly_rank_ic.mean() / rank_ic_standard_deviation
        if rank_ic_standard_deviation > 0
        else np.nan
    )
    axis.text(
        0.98,
        0.04,
        (
            f"Monthly mean={monthly_rank_ic.mean():.4f}  "
            f"RankIC IR={rank_ic_ir:.2f}  N={len(monthly_rank_ic)}"
        ),
        transform=axis.transAxes,
        horizontalalignment="right",
        verticalalignment="bottom",
        fontsize=8,
        bbox={"facecolor": "white", "edgecolor": "none", "alpha": 0.8},
    )


def _monthly_rank_ic(horizon_ic: pd.DataFrame) -> pd.Series:
    """将评价采样日 RankIC 按自然月求算术平均。"""
    return (
        horizon_ic.assign(
            month=pd.to_datetime(horizon_ic["date"]).dt.to_period("M")
        )
        .groupby("month", sort=True)["rank_ic"]
        .mean()
        .dropna()
    )


def _horizon_label(horizon_value: int, horizon_unit: str) -> str:
    """区分交易日和自然周评价周期。"""
    unit_labels = {
        "trading_days": ("trading day", "trading days"),
        "weeks": ("week", "weeks"),
    }
    singular_label, plural_label = unit_labels[horizon_unit]
    unit_label = singular_label if horizon_value == 1 else plural_label
    return f"{int(horizon_value)} {unit_label}"


def _evaluation_config_label(settings: Mapping[str, Any]) -> str:
    """格式化评价图需要展示的采样日期与价格口径。"""
    sampling = settings["sampling"]
    target = settings["target"]
    target_label = target["type"]
    if target["type"] == "benchmark_excess_return":
        target_label += f" ({target['benchmark_source']})"
    fields = [
        f"weekday: {sampling['weekday']}",
        f"every_n_weeks: {sampling['every_n_weeks']}",
        f"anchor_date: {sampling['anchor_date']}",
    ]
    return_source = settings.get("return_source", "market_price")
    if return_source == "market_price":
        fields.append(f"reference_price: {settings['reference_price']}")
    else:
        fields.append("return_source: external_return")
    fields.append(f"target: {target_label}")
    return " | ".join(fields)
