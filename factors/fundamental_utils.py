"""基本面因子共享的配置校验和截面后处理。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

import numpy as np
import pandas as pd

from src.data.market_data import MarketData
from src.factors.utils import neutralize_factor_values


@dataclass(frozen=True)
class FundamentalFactorParameters:
    """保存基本面公式和统一后处理参数。"""

    base_factor: str
    operator: str
    rolling_mean_window: int
    min_periods: int
    neutralize: bool
    winsorize_min_quantile: float
    winsorize_max_quantile: float
    reverse: bool


def safe_divide(numerator: pd.DataFrame, denominator: pd.DataFrame) -> pd.DataFrame:
    """仅在分母有限且不接近零时计算基本面比率。"""
    finite_denominator = np.isfinite(denominator)
    nonzero_denominator = denominator.abs() > 1e-12
    valid_denominator = denominator.where(finite_denominator & nonzero_denominator)
    return (numerator / valid_denominator).replace([np.inf, -np.inf], np.nan)


def parse_fundamental_factor_parameters(
    config_params: Mapping[str, Any],
) -> FundamentalFactorParameters:
    """读取公共默认值并校验 YAML 参数类型和范围。"""
    rolling_mean_window = config_params.get("rolling_mean_window", 1)
    min_periods = config_params.get("min_periods", 1)
    neutralize = config_params.get("neutralize", False)
    reverse = config_params.get("reverse", False)
    winsorize_config = config_params.get(
        "winsorize",
        {"min_quantile": 0.0, "max_quantile": 1.0},
    )

    if not isinstance(rolling_mean_window, int) or isinstance(
        rolling_mean_window,
        bool,
    ):
        raise TypeError("rolling_mean_window 必须是正整数")
    if rolling_mean_window <= 0:
        raise ValueError("rolling_mean_window 必须是正整数")
    if not isinstance(min_periods, int) or isinstance(min_periods, bool):
        raise TypeError("min_periods 必须是正整数")
    if min_periods <= 0 or min_periods > rolling_mean_window:
        raise ValueError("min_periods 必须在 1 到 rolling_mean_window 之间")
    if not isinstance(neutralize, bool):
        raise TypeError("neutralize 必须是布尔值")
    if not isinstance(reverse, bool):
        raise TypeError("reverse 必须是布尔值")
    if not isinstance(winsorize_config, Mapping):
        raise TypeError("winsorize 必须是包含分位点的映射")

    min_quantile = float(winsorize_config.get("min_quantile", 0.0))
    max_quantile = float(winsorize_config.get("max_quantile", 1.0))
    if not 0.0 <= min_quantile < max_quantile <= 1.0:
        raise ValueError("winsorize 分位点必须满足 0 <= min < max <= 1")
    return FundamentalFactorParameters(
        base_factor=str(config_params["base_factor"]),
        operator=str(config_params.get("operator", "raw")),
        rolling_mean_window=rolling_mean_window,
        min_periods=min_periods,
        neutralize=neutralize,
        winsorize_min_quantile=min_quantile,
        winsorize_max_quantile=max_quantile,
        reverse=reverse,
    )


def smooth_factor_values(
    factor_values: pd.DataFrame,
    rolling_mean_window: int,
    min_periods: int,
) -> pd.DataFrame:
    """按时间轴计算逐股票滚动均值。"""
    return factor_values.rolling(
        window=rolling_mean_window,
        min_periods=min_periods,
    ).mean()


def mask_factor_to_membership(
    factor_values: pd.DataFrame,
    market_data: MarketData,
) -> pd.DataFrame:
    """清空当日不属于研究股票池的因子值。"""
    membership = market_data.membership.reindex_like(factor_values).fillna(False)
    return factor_values.where(membership)


def neutralize_by_market_cap(
    factor_values: pd.DataFrame,
    market_data: MarketData,
) -> pd.DataFrame:
    """逐日截面回归剔除对数总市值暴露。"""
    membership = market_data.membership.reindex_like(factor_values).fillna(False)
    total_market_value = market_data.get_panel(
        "stock_valuation",
        "S_VAL_MV",
    ).reindex_like(factor_values)
    log_market_value = np.log(total_market_value.where(total_market_value > 0))
    return neutralize_factor_values(
        factor_values,
        [log_market_value.where(membership)],
    )


def winsorize_cross_section(
    factor_values: pd.DataFrame,
    min_quantile: float,
    max_quantile: float,
) -> pd.DataFrame:
    """按每日有效股票截面的线性插值分位点裁剪极端值。"""
    lower_bounds = factor_values.quantile(
        min_quantile,
        axis=1,
        interpolation="linear",
    )
    upper_bounds = factor_values.quantile(
        max_quantile,
        axis=1,
        interpolation="linear",
    )
    return factor_values.clip(
        lower=lower_bounds,
        upper=upper_bounds,
        axis=0,
    )


def reverse_factor_values(factor_values: pd.DataFrame) -> pd.DataFrame:
    """反转因子方向。"""
    return -factor_values


def replace_infinite_values(factor_values: pd.DataFrame) -> pd.DataFrame:
    """把正负无穷统一转换为缺失值。"""
    return factor_values.replace([np.inf, -np.inf], np.nan)
