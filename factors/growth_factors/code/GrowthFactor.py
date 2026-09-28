"""提供由 YAML 配置的景气成长基础因子和核心时间序列变体。"""

from __future__ import annotations

from dataclasses import dataclass
from threading import RLock
from typing import Any, Mapping
from weakref import WeakKeyDictionary

import pandas as pd

from factors.fundamental_utils import (
    mask_factor_to_membership,
    replace_infinite_values,
)
from factors.growth_factors.code.base_factors import calculate_base_factor
from factors.growth_factors.code.utils import (
    BaseFactorPanel,
    apply_daily_operator,
    apply_quarterly_operator,
)
from src.data.market_data import MarketData
from src.factors.base import Factor, FactorSearchSource

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
    """保存单个景气因子的公式与时间序列算子。"""

    base_factor: str
    operator: str


class GrowthFactor(Factor):
    """按配置计算一个景气基础因子或其核心时间序列变体。"""

    def __init__(self, config: Mapping[str, Any]) -> None:
        """保存 Factor 配置并提前验证名称和算子。"""
        super().__init__(config)
        self.params = parse_growth_factor_parameters(self.config["params"])
        validate_factor_identity(self.name, self.params)

    def calc(self, market_data: MarketData) -> pd.DataFrame:
        """计算基础公式及其时间序列变体。"""
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
                base_factor_panel.quarterly_events,
            )

        factor_values = mask_factor_to_membership(factor_values, market_data)
        factor_values = replace_infinite_values(factor_values)
        return factor_values.astype("float32")

    def factor_search_source(
        self,
        market_data: MarketData,
    ) -> FactorSearchSource:
        """为 raw 景气因子保留季度公告事件，供 PIT 时序搜索使用。"""
        base_factor_panel = get_cached_base_factor(
            self.params.base_factor,
            market_data,
        )
        if self.params.operator != "raw":
            return FactorSearchSource(
                values=self.calc(market_data),
                frequency=base_factor_panel.frequency,
            )
        factor_values = mask_factor_to_membership(
            base_factor_panel.values,
            market_data,
        )
        factor_values = replace_infinite_values(factor_values)
        return FactorSearchSource(
            values=factor_values.astype("float32"),
            frequency=base_factor_panel.frequency,
            quarterly_events=base_factor_panel.quarterly_events,
        )


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
    """读取景气因子的基础公式与时间序列算子。"""
    return GrowthFactorParameters(
        base_factor=str(config_params["base_factor"]),
        operator=str(config_params["operator"]),
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
