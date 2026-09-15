"""编排单因子与批量因子的静态图输出。"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

import matplotlib.pyplot as plt
import pandas as pd

from src.plotter.backtest import plot_backtest
from src.plotter.distribution import plot_distribution
from src.plotter.evaluation import plot_evaluation
from src.plotter.io import load_factor_plot_data


def plot_factor(
    factor_name: str,
    factor_panel: pd.DataFrame | None,
    settings: Mapping[str, Any],
    output_directory: str | Path,
    group_return_result: Mapping[str, Any] | None = None,
    simple_backtest_result: Mapping[str, Any] | None = None,
    account_backtest_result: Mapping[str, Any] | None = None,
    evaluation_settings: Mapping[str, Any] | None = None,
    backtest_settings: Mapping[str, Mapping[str, Any]] | None = None,
) -> dict[str, list[Path]]:
    """从一个因子的内存面板和计算结果生成全部已启用图表。"""
    if not settings["enabled"]:
        return {}
    output_directory = Path(output_directory)
    output_directory.mkdir(parents=True, exist_ok=True)
    backtest_settings = backtest_settings or {}
    sampled_factor_panel = (
        _sample_factor_panel(
            factor_panel,
            group_return_result,
            simple_backtest_result,
            account_backtest_result,
        )
        if factor_panel is not None
        else None
    )
    inputs = {
        "distribution": sampled_factor_panel,
        "evaluation": group_return_result,
        "simple": simple_backtest_result,
        "account": account_backtest_result,
    }
    output_names = {
        "distribution": "00_factor_distribution",
        "evaluation": "01_evaluation",
        "simple": "02_simple_backtest",
        "account": "03_account_backtest",
    }
    plot_actions = {
        "distribution": lambda result, stem: plot_distribution(
            factor_name,
            result,
            settings,
            stem,
            evaluation_settings,
        ),
        "evaluation": lambda result, stem: plot_evaluation(
            factor_name,
            result,
            settings,
            stem,
            evaluation_settings,
        ),
        "simple": lambda result, stem: plot_backtest(
            factor_name,
            result,
            "simple",
            settings,
            stem,
            backtest_settings.get("simple"),
        ),
        "account": lambda result, stem: plot_backtest(
            factor_name,
            result,
            "account",
            settings,
            stem,
            backtest_settings.get("account"),
        ),
    }

    generated = {}
    with plt.rc_context(
        {
            "font.family": settings["font_family"],
            "axes.labelsize": 10,
            "xtick.labelsize": 8,
            "ytick.labelsize": 9,
        }
    ):
        for plot_name, result in inputs.items():
            if not settings[plot_name]["enabled"]:
                continue
            if result is None:
                if settings["missing_results"] == "error":
                    raise ValueError(
                        f"{factor_name} 缺少 {plot_name} 绘图结果"
                    )
                continue
            output_stem = output_directory / output_names[plot_name]
            generated[plot_name] = plot_actions[plot_name](
                result,
                output_stem,
            )

    return generated


def plot_factors(
    factor_panels: Mapping[str, pd.DataFrame],
    settings: Mapping[str, Any],
    output_root: str | Path,
    group_return_results: Mapping[str, Mapping[str, Any]] | None = None,
    simple_backtest_results: Mapping[str, Mapping[str, Any]] | None = None,
    account_backtest_results: Mapping[str, Mapping[str, Any]] | None = None,
    evaluation_settings: Mapping[str, Any] | None = None,
    backtest_settings: Mapping[str, Mapping[str, Any]] | None = None,
) -> dict[str, dict[str, list[Path]]]:
    """批量绘制因子结果，每个因子写入独立 figures 目录。"""
    group_return_results = group_return_results or {}
    simple_backtest_results = simple_backtest_results or {}
    account_backtest_results = account_backtest_results or {}
    output_root = Path(output_root)
    return {
        factor_name: plot_factor(
            factor_name=factor_name,
            factor_panel=factor_panel,
            settings=settings,
            output_directory=output_root / factor_name / "figures",
            group_return_result=group_return_results.get(factor_name),
            simple_backtest_result=simple_backtest_results.get(factor_name),
            account_backtest_result=account_backtest_results.get(factor_name),
            evaluation_settings=evaluation_settings,
            backtest_settings=backtest_settings,
        )
        for factor_name, factor_panel in factor_panels.items()
    }


def plot_factor_from_directory(
    factor_directory: str | Path,
    settings: Mapping[str, Any],
) -> dict[str, list[Path]]:
    """读取并绘制一个 v7 固定格式的因子结果目录。"""
    factor_directory = Path(factor_directory)
    plot_data = load_factor_plot_data(
        factor_directory,
        settings["curve_frequency"],
    )
    return plot_factor(
        factor_name=factor_directory.name,
        factor_panel=plot_data["factor_panel"],
        settings=settings,
        output_directory=factor_directory / "figures",
        group_return_result=plot_data["group_return"],
        simple_backtest_result=plot_data["simple"],
        account_backtest_result=plot_data["account"],
    )


def plot_result_directory(
    result_root: str | Path,
    settings: Mapping[str, Any],
) -> dict[str, dict[str, list[Path]]]:
    """批量绘制结果根目录下的全部因子子目录。"""
    result_root = Path(result_root)
    return {
        factor_directory.name: plot_factor_from_directory(
            factor_directory,
            settings,
        )
        for factor_directory in sorted(result_root.iterdir())
        if factor_directory.is_dir()
    }


def _sample_factor_panel(
    factor_panel: pd.DataFrame,
    group_return_result: Mapping[str, Any] | None,
    simple_backtest_result: Mapping[str, Any] | None,
    account_backtest_result: Mapping[str, Any] | None,
) -> pd.DataFrame:
    """用实际评价与回测使用的因子日期构造分布图样本。"""
    date_indexes = []
    if group_return_result is not None and "detail" in group_return_result:
        date_indexes.append(
            pd.DatetimeIndex(group_return_result["detail"]["factor_date"])
        )
    for backtest_result in [
        simple_backtest_result,
        account_backtest_result,
    ]:
        if backtest_result is None:
            continue
        for period_result in backtest_result["periods"].values():
            if "actions" in period_result:
                date_indexes.append(
                    pd.DatetimeIndex(period_result["actions"]["factor_date"])
                )
    if not date_indexes:
        return factor_panel
    sample_dates = date_indexes[0]
    for date_index in date_indexes[1:]:
        sample_dates = sample_dates.union(date_index)
    return factor_panel.reindex(sample_dates.unique().sort_values())
