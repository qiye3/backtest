"""绘制因子分布和分组评价结果。正式策略净值来自分钟账户引擎。"""
from __future__ import annotations

from collections.abc import Collection, Mapping
from pathlib import Path
from typing import Any

import matplotlib.pyplot as plt
import pandas as pd

from src.plotter.distribution import plot_distribution
from src.plotter.evaluation import plot_evaluation


def plot_factor(
    factor_name: str,
    factor_panel: pd.DataFrame | None,
    settings: Mapping[str, Any],
    output_directory: str | Path,
    group_return_result: Mapping[str, Any] | None = None,
    evaluation_settings: Mapping[str, Any] | None = None,
    plot_names: Collection[str] | None = None,
) -> dict[str, list[Path]]:
    """绘制因子分布和IC/分组评价。"""
    if not settings["enabled"]:
        return {}
    output_directory = Path(output_directory)
    output_directory.mkdir(parents=True, exist_ok=True)
    requested = set(plot_names) if plot_names is not None else {"distribution", "evaluation"}
    if factor_panel is not None and group_return_result is not None and "detail" in group_return_result:
        sampled_dates = pd.DatetimeIndex(group_return_result["detail"]["factor_date"])
        factor_panel = factor_panel.reindex(sampled_dates.unique().sort_values())
    inputs = {
        "distribution": (factor_panel, plot_distribution, "00_factor_distribution"),
        "evaluation": (group_return_result, plot_evaluation, "01_evaluation"),
    }
    generated = {}
    with plt.rc_context({
        "font.family": settings["font_family"],
        "axes.labelsize": 10, "xtick.labelsize": 8, "ytick.labelsize": 9,
    }):
        for name, (value, action, filename) in inputs.items():
            if name not in requested or not settings[name]["enabled"]:
                continue
            if value is None:
                if settings["missing_results"] == "error":
                    raise ValueError(f"{factor_name} 缺少 {name} 绘图结果")
                continue
            generated[name] = action(
                factor_name, value, settings,
                output_directory / filename, evaluation_settings,
            )
    return generated


def plot_factors(
    factor_panels: Mapping[str, pd.DataFrame],
    settings: Mapping[str, Any],
    output_root: str | Path,
    group_return_results: Mapping[str, Mapping[str, Any]] | None = None,
    evaluation_settings: Mapping[str, Any] | None = None,
) -> dict[str, dict[str, list[Path]]]:
    """批量绘制因子结果。"""
    evaluations = group_return_results or {}
    return {
        name: plot_factor(
            name, panel, settings, Path(output_root) / name / "figures",
            evaluations.get(name), evaluation_settings,
        ) for name, panel in factor_panels.items()
    }
