"""提供由 YAML 配置的第一批新数据因子。"""

from __future__ import annotations

from threading import RLock
from typing import Any, Mapping
from weakref import WeakKeyDictionary

import pandas as pd

from factors.first_batch_factors.code.base_factors import calculate_base_factor
from factors.fundamental_utils import (
    FundamentalFactorParameters,
    mask_factor_to_membership,
    neutralize_by_market_cap,
    parse_fundamental_factor_parameters,
    replace_infinite_values,
    reverse_factor_values,
    smooth_factor_values,
    winsorize_cross_section,
)
from src.data.market_data import MarketData
from src.factors.base import Factor

FIRST_BATCH_FACTORS = {
    "notice_profit_growth_mid",
    "notice_consensus_surprise",
    "notice_revision",
    "notice_deducted_growth_mid",
    "notice_nonrecurring_gap",
    "notice_range_width",
    "notice_style_event",
    "historical_notice_accuracy",
    "buyback_plan_intensity",
    "buyback_execution_intensity",
    "buyback_completion_ratio",
    "buyback_execution_speed",
    "buyback_failure_event",
    "buyback_repeat_count_3y",
    "buyback_objective_group",
    "buyback_value_confirmation",
    "ebitda_ev",
    "ebitda_ev_v2",
    "industry_relative_ebitda_ev",
    "ev_ebitda_percentile_1y",
    "ev_ebitda_percentile_5y",
    "ev_definition_spread",
    "ev_growth_adjusted",
    "ev_quality_composite",
}

_BASE_FACTOR_CACHE: WeakKeyDictionary[MarketData, dict[str, pd.DataFrame]] = (
    WeakKeyDictionary()
)
_BASE_FACTOR_CACHE_LOCK = RLock()


class FirstBatchFactor(Factor):
    """计算一个业绩预告、回购或企业价值因子。"""

    def __init__(self, config: Mapping[str, Any]) -> None:
        """保存配置并校验因子名称与基础公式一一对应。"""
        super().__init__(config)
        self.params = parse_first_batch_factor_parameters(self.config["params"])
        validate_factor_identity(self.name, self.params)

    def calc(self, market_data: MarketData) -> pd.DataFrame:
        """计算固定经济公式，再执行项目统一的截面后处理。"""
        factor_values = get_cached_base_factor(
            self.params.base_factor,
            market_data,
        ).copy()
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
        return replace_infinite_values(factor_values).astype("float32")


def parse_first_batch_factor_parameters(
    config_params: Mapping[str, Any],
) -> FundamentalFactorParameters:
    """读取公共后处理参数，并限制第一批因子只使用原始公式。"""
    params = parse_fundamental_factor_parameters(config_params)
    if params.operator != "raw":
        raise ValueError("第一批新数据因子目前只支持 raw 算子")
    return params


def validate_factor_identity(
    factor_name: str,
    params: FundamentalFactorParameters,
) -> None:
    """防止 YAML 名称与实际经济公式错配。"""
    if params.base_factor not in FIRST_BATCH_FACTORS:
        raise ValueError(f"未知第一批新数据因子: {params.base_factor}")
    if factor_name != params.base_factor:
        raise ValueError(
            f"第一批因子 name 应为 {params.base_factor}，实际为 {factor_name}"
        )


def get_cached_base_factor(
    base_factor_name: str,
    market_data: MarketData,
) -> pd.DataFrame:
    """在同一次框架运行中只构造一次每个基础因子。"""
    with _BASE_FACTOR_CACHE_LOCK:
        market_cache = _BASE_FACTOR_CACHE.setdefault(market_data, {})
        if base_factor_name not in market_cache:
            market_cache[base_factor_name] = calculate_base_factor(
                base_factor_name,
                market_data,
            )
        return market_cache[base_factor_name]
