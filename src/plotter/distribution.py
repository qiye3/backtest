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
            0.95,
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
    )
    axis.set_xlabel("Factor value")
    axis.set_ylabel("Density" if plot_settings["density"] else "Count")
    clipping_note = " | display clipping enabled" if clip_quantiles else ""
    axis.set_title(
        f"{total_count:,} finite observations; {len(values):,} displayed"
        f"{clipping_note}",
        fontsize=10,
    )
    style_axis(axis)
    axis.legend(frameon=False)
    return save_figure(figure, output_stem, settings)
