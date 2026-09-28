"""保存和加载 CLI 各阶段共享的标准因子面板。"""

from __future__ import annotations

import re
from collections.abc import Mapping
from pathlib import Path

import numpy as np
import pandas as pd
from pandas.api.types import is_numeric_dtype

FACTOR_FILE_NAME = "factor.parquet"
FactorPanelSource = str | Path | Mapping[str, str | Path]


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
        factor_path.parent.name: load_factor_parquet(factor_path)
        for factor_path in factor_paths
    }


def load_factor_panel(
    factor_name: str,
    source: FactorPanelSource,
) -> pd.DataFrame:
    """从结果根目录或显式文件映射恢复一个标准因子面板。"""
    factor_path = _resolve_factor_path(factor_name, source)
    return load_factor_parquet(factor_path)


def find_factor_names(source: FactorPanelSource) -> tuple[str, ...]:
    """按名称排序列出结果根目录或显式文件映射中的因子。"""
    if isinstance(source, Mapping):
        factor_names = tuple(sorted(source))
        if not factor_names:
            raise FileNotFoundError("显式因子 Parquet 映射为空")
        return factor_names

    output_root = Path(source)
    factor_names = tuple(
        path.parent.name
        for path in sorted(output_root.glob(f"*/{FACTOR_FILE_NAME}"))
    )
    if not factor_names:
        raise FileNotFoundError(f"没有已保存的因子面板: {output_root}")
    return factor_names


def load_factor_parquet(path: str | Path) -> pd.DataFrame:
    """读取并校验框架原生的日期乘股票因子宽表。"""
    resolved_path = Path(path)
    factor_panel = pd.read_parquet(resolved_path)
    if factor_panel.empty:
        raise ValueError(f"因子 Parquet 不能为空: {resolved_path}")
    if not isinstance(factor_panel.index, pd.DatetimeIndex):
        raise ValueError(
            f"因子 Parquet 的索引必须是 DatetimeIndex: {resolved_path}"
        )
    if factor_panel.index.tz is not None:
        raise ValueError(f"因子 Parquet 的日期不能包含时区: {resolved_path}")
    if (
        factor_panel.index.has_duplicates
        or not factor_panel.index.is_monotonic_increasing
    ):
        raise ValueError(
            f"因子 Parquet 的日期必须唯一且按时间升序排列: {resolved_path}"
        )
    if factor_panel.columns.has_duplicates:
        raise ValueError(f"因子 Parquet 的股票代码不能重复: {resolved_path}")

    nonnumeric_columns = [
        str(column_name)
        for column_name, column_dtype in factor_panel.dtypes.items()
        if not is_numeric_dtype(column_dtype)
    ]
    if nonnumeric_columns:
        raise ValueError(
            "因子 Parquet 只能包含数值列: "
            f"{resolved_path} {nonnumeric_columns[:5]}"
        )
    factor_values = factor_panel.to_numpy(dtype="float64", na_value=np.nan)
    if np.isinf(factor_values).any():
        raise ValueError(
            f"因子 Parquet 只能包含有限值或 NaN: {resolved_path}"
        )

    asset_codes = pd.Index(
        factor_panel.columns.astype(str),
        name="asset_code",
    )
    if asset_codes.has_duplicates:
        raise ValueError(
            f"因子 Parquet 的股票代码转为字符串后不能重复: {resolved_path}"
        )
    factor_panel.index = pd.DatetimeIndex(factor_panel.index, name="date")
    factor_panel.columns = asset_codes
    return factor_panel


def _resolve_factor_path(
    factor_name: str,
    source: FactorPanelSource,
) -> Path:
    """从一种已校验的因子来源解析指定面板文件。"""
    if not isinstance(source, Mapping):
        return Path(source) / factor_name / FACTOR_FILE_NAME
    if factor_name not in source:
        raise FileNotFoundError(
            f"显式 Parquet 输入中没有因子: {factor_name}"
        )
    return Path(source[factor_name])


def _factor_directory(output_root: Path, factor_name: str) -> Path:
    """检查用于目录名的 Factor 名称并返回固定结果目录。"""
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*", factor_name):
        raise ValueError(f"Factor 名称不能用作结果目录: {factor_name}")
    return output_root / factor_name
