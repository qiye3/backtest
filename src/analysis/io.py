"""整体评价表的持久化入口。"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path

import pandas as pd


def save_overall_results(
    results: Mapping[str, pd.DataFrame],
    output_directory: str | Path,
) -> dict[str, Path]:
    """将相关性、IC 与收益汇总分别保存为 CSV。"""
    output_directory = Path(output_directory)
    output_directory.mkdir(parents=True, exist_ok=True)
    output_paths = {}
    for result_name, result in results.items():
        output_path = output_directory / f"{result_name}.csv"
        result.to_csv(
            output_path,
            index=result_name == "factor_correlation",
        )
        output_paths[result_name] = output_path
    return output_paths
