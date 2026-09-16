"""保存和加载 CLI 各阶段共享的标准因子面板。"""

from __future__ import annotations

import re
from collections.abc import Mapping
from pathlib import Path

import pandas as pd

FACTOR_FILE_NAME = "factor.parquet"


def save_factor_panels(
    factor_panels: Mapping[str, pd.DataFrame],
    output_root: str | Path,
) -> dict[str, Path]:
    """按因子目录覆盖保存一批标准日频面板。"""
    output_root = Path(output_root)
    output_paths = {}
    for factor_name, factor_panel in factor_panels.items():
        factor_directory = _factor_directory(output_root, factor_name)
        factor_directory.mkdir(parents=True, exist_ok=True)
        output_path = factor_directory / FACTOR_FILE_NAME
        factor_panel.to_parquet(output_path)
        output_paths[factor_name] = output_path
    return output_paths


def load_factor_panels(
    output_root: str | Path,
) -> dict[str, pd.DataFrame]:
    """从结果根目录批量恢复全部标准因子面板。"""
    output_root = Path(output_root)
    factor_paths = sorted(output_root.glob(f"*/{FACTOR_FILE_NAME}"))
    if not factor_paths:
        raise FileNotFoundError(f"没有已保存的因子面板: {output_root}")
    return {
        factor_path.parent.name: pd.read_parquet(factor_path)
        for factor_path in factor_paths
    }


def load_factor_panel(
    factor_name: str,
    output_root: str | Path,
) -> pd.DataFrame:
    """从结果根目录恢复一个标准因子面板。"""
    result_path = Path(output_root) / factor_name / FACTOR_FILE_NAME
    return pd.read_parquet(result_path)


def find_factor_names(output_root: str | Path) -> tuple[str, ...]:
    """按目录名排序列出已经保存标准面板的因子。"""
    output_root = Path(output_root)
    factor_names = tuple(
        path.parent.name
        for path in sorted(output_root.glob(f"*/{FACTOR_FILE_NAME}"))
    )
    if not factor_names:
        raise FileNotFoundError(f"没有已保存的因子面板: {output_root}")
    return factor_names


def _factor_directory(output_root: Path, factor_name: str) -> Path:
    """检查用于目录名的 Factor 名称并返回固定结果目录。"""
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*", factor_name):
        raise ValueError(f"Factor 名称不能用作结果目录: {factor_name}")
    return output_root / factor_name
