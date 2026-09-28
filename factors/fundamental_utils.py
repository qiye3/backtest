"""基本面因子共享的配置校验和数值清理。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

import numpy as np
import pandas as pd

from src.data.market_data import MarketData


@dataclass(frozen=True)
class FundamentalFactorParameters:
    """保存基本面因子的公式与时间序列算子。"""

    base_factor: str
    operator: str


def safe_divide(numerator: pd.DataFrame, denominator: pd.DataFrame) -> pd.DataFrame:
    """仅在分母有限且不接近零时计算基本面比率。"""
    finite_denominator = np.isfinite(denominator)
    nonzero_denominator = denominator.abs() > 1e-12
    valid_denominator = denominator.where(finite_denominator & nonzero_denominator)
    return (numerator / valid_denominator).replace([np.inf, -np.inf], np.nan)


def parse_fundamental_factor_parameters(
    config_params: Mapping[str, Any],
) -> FundamentalFactorParameters:
    """读取因子公式及其时间序列算子。"""
    return FundamentalFactorParameters(
        base_factor=str(config_params["base_factor"]),
        operator=str(config_params.get("operator", "raw")),
    )


def mask_factor_to_membership(
    factor_values: pd.DataFrame,
    market_data: MarketData,
) -> pd.DataFrame:
    """清空当日不属于研究股票池的因子值。"""
    membership = market_data.membership.reindex_like(factor_values).fillna(False)
    return factor_values.where(membership)


def replace_infinite_values(factor_values: pd.DataFrame) -> pd.DataFrame:
    """把正负无穷统一转换为缺失值。"""
    return factor_values.replace([np.inf, -np.inf], np.nan)
