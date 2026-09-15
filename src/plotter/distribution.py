"""绘制因子原始值的直方图和可选核密度曲线。"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from scipy.stats import gaussian_kde

from src.plotter.style import save_figure, set_figure_title, style_axis


def plot_distribution(
    factor_name: str,
    factor_panel: pd.DataFrame,
    settings: Mapping[str, Any],
    output_stem: Path,
    sampling_settings: Mapping[str, Any] | None = None,
) -> list[Path]:
    """绘制有限因子值分布；裁剪和抽样只影响展示。"""
    plot_settings = settings["distribution"]
    values = factor_panel.to_numpy(dtype=float).ravel()
    values = values[np.isfinite(values)]
    total_count = len(values)
    if total_count == 0:
        raise ValueError(f"{factor_name} 没有可用于分布图的有限因子值")

    clip_quantiles = plot_settings["clip_quantiles"]
    if clip_quantiles is not None:
        lower, upper = np.quantile(values, clip_quantiles)
        values = values[(values >= lower) & (values <= upper)]
    if len(values) > plot_settings["max_points"]:
        values = np.random.default_rng(0).choice(
            values,
            plot_settings["max_points"],
            replace=False,
        )
    value_series = pd.Series(values)
    distribution_statistics = {
        "Mean": float(value_series.mean()),
        "Median": float(value_series.median()),
        "Min": float(value_series.min()),
        "Max": float(value_series.max()),
        "Skewness": float(value_series.skew()),
        "Kurtosis (excess)": float(value_series.kurt()),
    }
    standard_deviation = float(value_series.std(ddof=0))

    figure, axis = plt.subplots(
        figsize=(settings["width"], settings["row_height"] * 1.5),
        layout="constrained",
    )
    _, bin_edges, _ = axis.hist(
        values,
        bins=plot_settings["bins"],
        density=plot_settings["density"],
        color="#80A9C5",
        alpha=0.6,
        edgecolor="white",
        linewidth=0.4,
        label="Histogram",
    )
    mean_value = distribution_statistics["Mean"]
    for line_value, line_label, line_style in [
        (mean_value - standard_deviation, "Mean - 1 std", "--"),
        (mean_value, "Mean", "-"),
        (mean_value + standard_deviation, "Mean + 1 std", "--"),
    ]:
        axis.axvline(
            line_value,
            color="#8C2D24",
            linewidth=1.3,
            linestyle=line_style,
            label=line_label,
        )
    if (
        plot_settings["kde"]
        and len(values) >= 3
        and np.std(values) > 0
    ):
        grid = np.linspace(bin_edges[0], bin_edges[-1], 400)
        density_values = gaussian_kde(values)(grid)
        if not plot_settings["density"]:
            density_values *= len(values) * (bin_edges[1] - bin_edges[0])
        axis.plot(
            grid,
            density_values,
            color="#163B55",
            linewidth=1.8,
            label=(
                "Density"
                if plot_settings["density"]
                else "Scaled density"
            ),
        )
    elif plot_settings["kde"]:
        axis.text(
            0.98,
            0.55,
            "Density unavailable: constant or sparse values",
            transform=axis.transAxes,
            horizontalalignment="right",
            verticalalignment="top",
            fontsize=9,
        )

    set_figure_title(
        figure,
        f"{factor_name} | Factor distribution",
        settings,
        annotation=(
            _distribution_sampling_label(sampling_settings)
            if sampling_settings is not None
            else None
        ),
    )
    axis.set_xlabel("Factor value")
    axis.set_ylabel("Density" if plot_settings["density"] else "Count")
    clipping_note = " | display clipping enabled" if clip_quantiles else ""
    axis.set_title(
        f"{total_count:,} finite observations; {len(values):,} displayed"
        f"{clipping_note}",
        fontsize=10,
    )
    axis.text(
        0.98,
        0.95,
        "\n".join(
            f"{name}: {value:.6g}"
            for name, value in distribution_statistics.items()
        ),
        transform=axis.transAxes,
        horizontalalignment="right",
        verticalalignment="top",
        fontsize=9,
        bbox={
            "boxstyle": "round,pad=0.4",
            "facecolor": "white",
            "edgecolor": "#B0BEC5",
            "alpha": 0.9,
        },
    )
    style_axis(axis)
    axis.legend(loc="upper left", frameon=False)
    return save_figure(figure, output_stem, settings)


def _distribution_sampling_label(settings: Mapping[str, Any]) -> str:
    """格式化因子分布样本使用的周度截面抽样策略。"""
    sampling = settings["sampling"]
    return " | ".join(
        [
            f"weekday: {sampling['weekday']}",
            f"every_n_weeks: {sampling['every_n_weeks']}",
            f"anchor_date: {sampling['anchor_date']}",
            f"holiday_policy: {sampling['holiday_policy']}",
        ]
    )
