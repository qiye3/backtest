"""提供由 YAML 配置的价值基础因子和历史分位变体。"""

from __future__ import annotations

from threading import RLock
from typing import Any, Mapping
from weakref import WeakKeyDictionary

import pandas as pd

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
from factors.value_factors.code.base_factors import calculate_base_factor
from factors.value_factors.code.utils import ValueBasePanel, apply_value_operator
from src.data.market_data import MarketData
from src.factors.base import Factor

RAW_BASE_FACTORS = {
    "ep",
    "ep_static",
    "bp",
    "sp",
    "pcf",
    "dividend_yield",
    "ebit_ev",
    "ev_ebitda",
    "fcf_yield",
    "peg",
    "net_cash_to_mv",
    "ev_ocf",
    "valuation_composite",
    "low_volatility",
    "pb_roe_group",
    "pb_roe_regression",
    "irrational_valuation_premium",
    "consensus_valuation",
    "expected_pe_change",
    "value_quality_composite",
    "dividend_low_vol_composite",
    "dividend_quality_composite",
    "value_trap_filter",
    "low_valuation_option",
}

VARIANT_IDENTITIES = {
    "pe_percentile_5y": ("pe_multiple", "percentile_5y"),
    "valuation_composite_percentile_5y": (
        "valuation_composite",
        "percentile_5y",
    ),
}
for _base_factor_name in (
    "ep",
    "ep_static",
    "bp",
    "sp",
    "pcf",
    "dividend_yield",
    "ebit_ev",
    "ev_ebitda",
    "fcf_yield",
    "peg",
    "net_cash_to_mv",
    "ev_ocf",
    "consensus_valuation",
):
    VARIANT_IDENTITIES[f"{_base_factor_name}_percentile_1y"] = (
        _base_factor_name,
        "percentile_1y",
    )
    VARIANT_IDENTITIES[f"{_base_factor_name}_percentile_5y"] = (
        _base_factor_name,
        "percentile_5y",
    )

_BASE_FACTOR_CACHE: WeakKeyDictionary[MarketData, dict[str, ValueBasePanel]] = WeakKeyDictionary()
_BASE_FACTOR_CACHE_LOCK = RLock()


class ValueFactor(Factor):
    """按配置计算一个价值基础因子或历史估值分位变体。"""

    def __init__(self, config: Mapping[str, Any]) -> None:
        """保存配置并提前校验名称、公式和公共参数。"""
        super().__init__(config)
        self.params = parse_value_factor_parameters(self.config["params"])
        validate_factor_identity(self.name, self.params)

    def calc(self, market_data: MarketData) -> pd.DataFrame:
        """计算价值公式，并按本因子配置分别调用各项处理函数。"""
        base_panel = get_cached_base_factor(self.params.base_factor, market_data)
        factor_values = apply_value_operator(base_panel, self.params.operator)
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


def parse_value_factor_parameters(
    config_params: Mapping[str, Any],
) -> FundamentalFactorParameters:
    """使用基本面因子统一规则读取价值因子参数。"""
    return parse_fundamental_factor_parameters(config_params)


def validate_factor_identity(
    factor_name: str,
    params: FundamentalFactorParameters,
) -> None:
    """确认公开因子名与基础公式、历史算子的映射一致。"""
    if params.operator == "raw":
        if params.base_factor not in RAW_BASE_FACTORS:
            raise ValueError(f"未知价值基础因子: {params.base_factor}")
        expected_identity = (params.base_factor, "raw")
        expected_name = params.base_factor
    else:
        if factor_name not in VARIANT_IDENTITIES:
            raise ValueError(f"未知价值变体: {factor_name}")
        expected_identity = VARIANT_IDENTITIES[factor_name]
        expected_name = factor_name
    actual_identity = (params.base_factor, params.operator)
    if factor_name != expected_name or actual_identity != expected_identity:
        raise ValueError(
            f"价值因子 {factor_name} 应配置为 {expected_identity}，实际为 {actual_identity}"
        )


def get_cached_base_factor(
    base_factor_name: str,
    market_data: MarketData,
) -> ValueBasePanel:
    """在同一次框架运行中只构造一次每个价值基础因子。"""
    with _BASE_FACTOR_CACHE_LOCK:
        market_cache = _BASE_FACTOR_CACHE.setdefault(market_data, {})
        if base_factor_name not in market_cache:
            market_cache[base_factor_name] = calculate_base_factor(
                base_factor_name,
                market_data,
            )
        return market_cache[base_factor_name]
