"""绘制各预测周期的分组收益与 IC 时间序列。"""

from __future__ import annotations

from collections.abc import Mapping
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


def plot_evaluation(
    factor_name: str,
    group_return_result: Mapping[str, Any],
    settings: Mapping[str, Any],
    output_stem: Path,
) -> list[Path]:
    """每个未来收益周期绘制一组收益柱图和一组 IC 曲线。"""
    definitions = group_return_result["definitions"]
    summary = group_return_result["summary"]
    ic_series = group_return_result["ic"]
    horizons = summary["horizon_days"].drop_duplicates().tolist()
    plot_settings = settings["evaluation"]
    palette = group_colors(
        plot_settings["group_colors"],
        len(definitions),
    )
    figure, axes = plt.subplots(
        len(horizons),
        2,
        figsize=(
            settings["width"],
            settings["row_height"] * len(horizons) + 0.5,
        ),
        squeeze=False,
        layout="constrained",
        gridspec_kw={"width_ratios": [1, 1]},
    )
    set_figure_title(
        figure,
        f"{factor_name} | Forward-return evaluation",
        settings,
    )

    for row_position, horizon_days in enumerate(horizons):
        group_column = 0 if plot_settings["group_panel"] == "left" else 1
        bar_axis = axes[row_position, group_column]
        line_axis = axes[row_position, 1 - group_column]
        group_observations = (
            summary[summary["horizon_days"] == horizon_days]
            .set_index("group_id")
            .reindex(definitions["group_id"])
        )
        bars = bar_axis.bar(
            np.arange(len(definitions)),
            group_observations["group_return"],
            color=palette,
            width=0.8,
        )
        labels, standard_deciles = group_labels(definitions)
        rotate_labels = not standard_deciles and len(definitions) > 6
        bar_axis.set_xticks(
            np.arange(len(definitions)),
            labels,
            rotation=35 if rotate_labels else 0,
            horizontalalignment="right" if rotate_labels else "center",
            fontsize=8,
        )
        bar_axis.yaxis.set_major_formatter(PercentFormatter(1))
        bar_axis.axhline(0, color="#555555", linewidth=0.7)
        bar_axis.set_title(
            f"{horizon_days} trading days | groups: "
            f"{group_observations['group_return_agg'].iloc[0]}, dates: "
            f"{group_observations['time_return_agg'].iloc[0]}",
            fontsize=10,
        )
        bar_axis.set_ylabel("Aggregated forward return")
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
                    f"{value:.2%}",
                    horizontalalignment="center",
                    verticalalignment="bottom",
                    fontsize=7,
                )

        horizon_ic = ic_series[ic_series["horizon_days"] == horizon_days]
        line_axis.plot(
            horizon_ic["date"],
            horizon_ic["ic"],
            label="IC (Pearson)",
            color=plot_settings["ic_color"],
            linewidth=1.2,
            marker="o",
            markersize=2.0,
        )
        line_axis.plot(
            horizon_ic["date"],
            horizon_ic["rank_ic"],
            label="RankIC (Spearman)",
            color=plot_settings["rank_ic_color"],
            linewidth=1.4,
        )
        line_axis.axhline(0, color="#555555", linewidth=0.7)
        line_axis.set_ylim(-1.05, 1.05)
        line_axis.set_title(
            f"{horizon_days} trading days | full valid stock universe",
            fontsize=10,
        )
        line_axis.set_ylabel("Correlation")
        line_axis.legend(
            loc="upper right",
            frameon=False,
            ncol=2,
            fontsize=8,
        )
        style_axis(bar_axis)
        style_axis(line_axis)
        style_date_axis(line_axis)
    return save_figure(figure, output_stem, settings)
