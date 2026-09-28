"""提供由 YAML 配置的质量基础因子和核心变体。"""

from __future__ import annotations

from threading import RLock
from typing import Any, Mapping
from weakref import WeakKeyDictionary

import pandas as pd

from factors.fundamental_utils import (
    FundamentalFactorParameters,
    mask_factor_to_membership,
    parse_fundamental_factor_parameters,
    replace_infinite_values,
)
from factors.quality_factors.code.base_factors import calculate_base_factor
from factors.quality_factors.code.utils import QualityBasePanel, apply_quality_operator
from src.data.market_data import MarketData
from src.factors.base import Factor

RAW_BASE_FACTORS = {
    "roe_level",
    "roe_q",
    "roe_deducted",
    "roic",
    "roa",
    "gross_margin",
    "net_margin",
    "operating_margin",
    "ocf_to_net_profit",
    "ocf_to_revenue",
    "cash_realization_rate",
    "accruals_to_assets",
    "deducted_profit_to_profit",
    "fcf_yield",
    "capex_to_ocf",
    "interest_debt_to_ocf",
    "accounts_receivable_to_revenue",
    "sales_cash_to_revenue",
    "inventory_change_to_assets",
    "goodwill_to_equity",
    "debt_to_assets",
    "equity_multiplier",
    "asset_turnover",
    "tangible_asset_ratio",
    "current_ratio",
    "quick_ratio",
    "roe_expected",
    "analyst_forecast_revision",
    "analyst_coverage",
    "quality_composite",
    "pb_roe_composite",
}

VARIANT_IDENTITIES = {
    "roe_yoy": ("roe_q", "yoy"),
    "roe_qoq": ("roe_q", "qoq"),
    "roe_stability_3y": ("roe_level", "std12"),
    "roe_stability_5y": ("roe_level", "std20"),
    "roe_cv_3y": ("roe_level", "cv12"),
    "roe_deducted_stability_2y": ("roe_deducted", "std8"),
    "roic_stability_3y": ("roic", "std12"),
    "roa_stability_3y": ("roa", "std12"),
    "gross_margin_trend": ("gross_margin", "qoq"),
    "gross_margin_stability_2y": ("gross_margin", "std8"),
    "net_margin_stability": ("net_margin", "std8"),
    "operating_margin_stability_2y": ("operating_margin", "std8"),
    "ocf_to_net_profit_stability_2y": ("ocf_to_net_profit", "std8"),
    "ocf_to_revenue_stability_2y": ("ocf_to_revenue", "std8"),
    "accruals_to_assets_change": ("accruals_to_assets", "yoy"),
    "deducted_profit_to_profit_stability_2y": (
        "deducted_profit_to_profit",
        "std8",
    ),
    "fcf_turning_positive": ("fcff", "turning_positive"),
    "capex_to_ocf_3y_mean": ("capex_to_ocf", "mean12"),
    "accounts_receivable_to_revenue_yoy": (
        "accounts_receivable_to_revenue",
        "yoy",
    ),
    "debt_to_assets_yoy": ("debt_to_assets", "yoy"),
    "roe_expected_change": ("roe_expected", "chg65"),
}

_BASE_FACTOR_CACHE: WeakKeyDictionary[MarketData, dict[str, QualityBasePanel]] = WeakKeyDictionary()
_BASE_FACTOR_CACHE_LOCK = RLock()


class QualityFactor(Factor):
    """按配置计算一个质量基础因子或其核心变体。"""

    def __init__(self, config: Mapping[str, Any]) -> None:
        """保存配置并提前校验因子名称、公式和算子。"""
        super().__init__(config)
        self.params = parse_quality_factor_parameters(self.config["params"])
        validate_factor_identity(self.name, self.params)

    def calc(self, market_data: MarketData) -> pd.DataFrame:
        """计算 PIT 公式及其时间序列变体。"""
        base_panel = get_cached_base_factor(self.params.base_factor, market_data)
        factor_values = apply_quality_operator(base_panel, self.params.operator)
        factor_values = mask_factor_to_membership(factor_values, market_data)
        factor_values = replace_infinite_values(factor_values)
        return factor_values.astype("float32")


def parse_quality_factor_parameters(
    config_params: Mapping[str, Any],
) -> FundamentalFactorParameters:
    """使用基本面因子统一规则读取质量因子参数。"""
    return parse_fundamental_factor_parameters(config_params)


def validate_factor_identity(
    factor_name: str,
    params: FundamentalFactorParameters,
) -> None:
    """确认公开因子名与基础公式、算子的固定映射一致。"""
    if params.operator == "raw":
        if params.base_factor not in RAW_BASE_FACTORS:
            raise ValueError(f"未知质量基础因子: {params.base_factor}")
        expected_identity = (params.base_factor, "raw")
        expected_name = params.base_factor
    else:
        if factor_name not in VARIANT_IDENTITIES:
            raise ValueError(f"未知质量变体: {factor_name}")
        expected_identity = VARIANT_IDENTITIES[factor_name]
        expected_name = factor_name
    actual_identity = (params.base_factor, params.operator)
    if factor_name != expected_name or actual_identity != expected_identity:
        raise ValueError(
            f"质量因子 {factor_name} 应配置为 {expected_identity}，实际为 {actual_identity}"
        )


def get_cached_base_factor(
    base_factor_name: str,
    market_data: MarketData,
) -> QualityBasePanel:
    """在同一次框架运行中只构造一次每个质量基础因子。"""
    with _BASE_FACTOR_CACHE_LOCK:
        market_cache = _BASE_FACTOR_CACHE.setdefault(market_data, {})
        if base_factor_name not in market_cache:
            market_cache[base_factor_name] = calculate_base_factor(
                base_factor_name,
                market_data,
            )
        return market_cache[base_factor_name]
