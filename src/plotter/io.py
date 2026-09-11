"""将 v7 固定结果目录加载为 plotter 使用的内存结果结构。"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd


def load_factor_plot_data(
    factor_directory: str | Path,
    curve_frequency: str,
) -> dict[str, Any]:
    """加载一个因子目录中的样本、评价和两类回测结果。"""
    factor_directory = Path(factor_directory)
    return {
        "factor_panel": _load_factor_sample(factor_directory),
        "group_return": _load_group_return(factor_directory),
        "simple": _load_backtest(
            factor_directory / "simple_backtest",
            curve_frequency,
        ),
        "account": _load_backtest(
            factor_directory / "account_backtest",
            curve_frequency,
        ),
    }


def _load_factor_sample(factor_directory: Path) -> pd.DataFrame | None:
    """读取 v7 保存的因子绘图样本。"""
    sample_path = factor_directory / "factor_sample.csv.gz"
    if not sample_path.exists():
        return None
    return pd.read_csv(sample_path, index_col=0)


def _load_group_return(factor_directory: Path) -> dict[str, Any] | None:
    """读取 v7 的分组定义、收益汇总和 IC 序列。"""
    result_directory = factor_directory / "group_return"
    if not result_directory.exists():
        return None
    return {
        "definitions": pd.read_csv(result_directory / "definitions.csv"),
        "summary": pd.read_csv(result_directory / "summary.csv"),
        "ic": pd.read_csv(
            result_directory / "ic.csv.gz",
            parse_dates=["date"],
        ),
    }


def _load_backtest(
    result_directory: Path,
    curve_frequency: str,
) -> dict[str, Any] | None:
    """将 v7 周期/分组目录恢复成当前 backtest 嵌套结构。"""
    if not result_directory.exists():
        return None
    metrics = pd.read_csv(result_directory / "metrics.csv")
    period_directories = sorted(
        (
            path
            for path in result_directory.glob("W*")
            if path.is_dir()
        ),
        key=lambda path: int(path.name[1:]),
    )
    periods = {}
    definitions = None
    for period_directory in period_directories:
        weeks = int(period_directory.name[1:])
        period_definitions = pd.read_csv(
            period_directory / "definitions.csv"
        )
        if definitions is None:
            definitions = period_definitions
        groups = {}
        for group_id in period_definitions["group_id"]:
            curve_path = (
                period_directory
                / group_id
                / f"curves_{curve_frequency}.csv.gz"
            )
            if not curve_path.exists():
                raise ValueError(
                    f"{curve_path} 不存在；请重新生成该频率曲线，"
                    "或改用已经保存的曲线频率"
                )
            groups[group_id] = {
                "curves": {
                    curve_frequency: pd.read_csv(
                        curve_path,
                        parse_dates=["timestamp"],
                    )
                }
            }
        periods[weeks] = {"groups": groups}
    return {
        "definitions": definitions,
        "metrics": metrics,
        "periods": periods,
    }
