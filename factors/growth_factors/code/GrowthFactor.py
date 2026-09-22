"""提供由 YAML 配置的景气成长基础因子和核心时间序列变体。"""

from __future__ import annotations

from dataclasses import dataclass
from threading import RLock
from typing import Any, Mapping
from weakref import WeakKeyDictionary

import pandas as pd

from factors.fundamental_utils import (
    mask_factor_to_membership,
    neutralize_by_market_cap,
    replace_infinite_values,
    reverse_factor_values,
    smooth_factor_values,
    winsorize_cross_section,
)
from factors.growth_factors.code.base_factors import calculate_base_factor
from factors.growth_factors.code.utils import (
    BaseFactorPanel,
    apply_daily_operator,
    apply_quarterly_operator,
)
from src.data.market_data import MarketData
from src.factors.base import Factor

DAILY_BASE_FACTORS = {
    "consensus_eps",
    "consensus_13w_revision",
    "rating_upgrade_ratio_90d",
    "analyst_coverage",
}
QUARTERLY_BASE_FACTORS = {
    "quarterly_roe",
    "quarterly_revenue",
    "quarterly_net_profit",
    "revenue_sur",
    "earnings_sue",
    "consensus_np_sue",
}
DAILY_OPERATORS = {
    "raw",
    "qtile_M12",
    "qtile_M24",
    "zscore_K12",
    "zscore_K24",
    "chg_K1",
    "qtilechg_K24_K1",
    "zchg_K24_K1",
}
QUARTERLY_OPERATORS = {"raw", "qoq", "yoy", "qtile8"}

_BASE_FACTOR_CACHE: WeakKeyDictionary[
    MarketData,
    dict[str, BaseFactorPanel],
] = WeakKeyDictionary()
_BASE_FACTOR_CACHE_LOCK = RLock()


@dataclass(frozen=True)
class GrowthFactorParameters:
    """保存并校验单个景气因子的公式与公共后处理参数。"""

    base_factor: str
    operator: str
    rolling_mean_window: int
    min_periods: int
    neutralize: bool
    winsorize_min_quantile: float
    winsorize_max_quantile: float
    reverse: bool


class GrowthFactor(Factor):
    """按配置计算一个景气基础因子或其核心时间序列变体。"""

    def __init__(self, config: Mapping[str, Any]) -> None:
        """保存 Factor 配置并提前验证名称、算子和后处理参数。"""
        super().__init__(config)
        self.params = parse_growth_factor_parameters(self.config["params"])
        validate_factor_identity(self.name, self.params)

    def calc(self, market_data: MarketData) -> pd.DataFrame:
        """计算基础公式，并按本因子配置分别调用各项处理函数。"""
        base_factor_panel = get_cached_base_factor(
            self.params.base_factor,
            market_data,
        )
        if base_factor_panel.frequency == "daily":
            factor_values = apply_daily_operator(
                base_factor_panel.values,
                self.params.operator,
            )
        else:
            factor_values = apply_quarterly_operator(
                base_factor_panel.values,
                base_factor_panel.report_periods,
                self.params.operator,
            )

        if self.params.rolling_mean_window > 1 or self.params.min_periods > 1:
            factor_values = smooth_factor_values(
                factor_values,
                rolling_mean_window=self.params.rolling_mean_window,
                min_periods=self.params.min_periods,
            )
        factor_values = mask_factor_to_membership(factor_values, market_data)
        if self.params.neutralize:
            factor_values = neutralize_by_market_cap(factor_values, market_data)
        lower_tail_winsorization = self.params.winsorize_min_quantile > 0.0
        upper_tail_winsorization = self.params.winsorize_max_quantile < 1.0
        if lower_tail_winsorization or upper_tail_winsorization:
            factor_values = winsorize_cross_section(
                factor_values,
                min_quantile=self.params.winsorize_min_quantile,
                max_quantile=self.params.winsorize_max_quantile,
            )
        if self.params.reverse:
            factor_values = reverse_factor_values(factor_values)
        factor_values = replace_infinite_values(factor_values)
        return factor_values.astype("float32")


def get_cached_base_factor(
    base_factor_name: str,
    market_data: MarketData,
) -> BaseFactorPanel:
    """在同一次框架运行中只构造一次每个基础因子。"""
    with _BASE_FACTOR_CACHE_LOCK:
        market_cache = _BASE_FACTOR_CACHE.setdefault(market_data, {})
        if base_factor_name not in market_cache:
            market_cache[base_factor_name] = calculate_base_factor(
                base_factor_name,
                market_data,
            )
        return market_cache[base_factor_name]


def parse_growth_factor_parameters(
    config_params: Mapping[str, Any],
) -> GrowthFactorParameters:
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

    min_quantile = float(winsorize_config["min_quantile"])
    max_quantile = float(winsorize_config["max_quantile"])
    if not 0.0 <= min_quantile < max_quantile <= 1.0:
        raise ValueError("winsorize 分位点必须满足 0 <= min < max <= 1")
    return GrowthFactorParameters(
        base_factor=str(config_params["base_factor"]),
        operator=str(config_params["operator"]),
        rolling_mean_window=rolling_mean_window,
        min_periods=min_periods,
        neutralize=neutralize,
        winsorize_min_quantile=min_quantile,
        winsorize_max_quantile=max_quantile,
        reverse=reverse,
    )


def validate_factor_identity(
    factor_name: str,
    params: GrowthFactorParameters,
) -> None:
    """确认基础因子频率、算子集合和结果名称完全匹配。"""
    if params.base_factor in DAILY_BASE_FACTORS:
        allowed_operators = DAILY_OPERATORS
    elif params.base_factor in QUARTERLY_BASE_FACTORS:
        allowed_operators = QUARTERLY_OPERATORS
    else:
        raise ValueError(f"未知景气基础因子: {params.base_factor}")
    if params.operator not in allowed_operators:
        raise ValueError(f"基础因子 {params.base_factor} 不支持算子 {params.operator}")

    if params.operator == "raw":
        expected_name = params.base_factor
    else:
        expected_name = f"{params.base_factor}__{params.operator}"
    if factor_name != expected_name:
        raise ValueError(f"景气因子 name 应为 {expected_name}，实际为 {factor_name}")
