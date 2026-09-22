"""从框架 MarketData 构造十个景气成长基础因子。"""

from __future__ import annotations

import numpy as np

from factors.growth_factors.code.utils import (
    BaseFactorPanel,
    build_consensus_profit_surprise,
    build_seasonal_surprise,
)
from factors.quarterly_history import build_financial_field_history
from src.data.market_data import MarketData

DAILY_BASE_FIELDS = {
    "consensus_eps": ("consensus_suntime", "con_eps"),
    "consensus_13w_revision": ("consensus_suntime", "con_npgrate_13w"),
    "analyst_coverage": ("consensus_wind", "prediction_number"),
}


def calculate_base_factor(
    base_factor_name: str,
    market_data: MarketData,
) -> BaseFactorPanel:
    """根据固定基础因子名称分派到对应经济公式。"""
    if base_factor_name in DAILY_BASE_FIELDS:
        source_name, field_name = DAILY_BASE_FIELDS[base_factor_name]
        factor_values = market_data.get_panel(source_name, field_name)
        return BaseFactorPanel(
            values=factor_values.astype("float64"),
            frequency="daily",
        )
    if base_factor_name == "rating_upgrade_ratio_90d":
        return calculate_rating_upgrade_ratio(market_data)
    if base_factor_name == "quarterly_roe":
        return calculate_quarterly_roe(market_data)
    if base_factor_name in {
        "quarterly_revenue",
        "quarterly_net_profit",
        "revenue_sur",
        "earnings_sue",
        "consensus_np_sue",
    }:
        return calculate_income_factor(base_factor_name, market_data)
    raise ValueError(f"未知景气基础因子: {base_factor_name}")


def calculate_rating_upgrade_ratio(market_data: MarketData) -> BaseFactorPanel:
    """计算90日评级净上调次数占全部评级动作的比例。"""
    upgrade_counts = market_data.get_panel("ratings", "S_WRATING_UPGRADE")
    downgrade_counts = market_data.get_panel("ratings", "S_WRATING_DOWNGRADE")
    maintain_counts = market_data.get_panel("ratings", "S_WRATING_MAINTAIN")
    action_counts = upgrade_counts + downgrade_counts + maintain_counts
    factor_values = (upgrade_counts - downgrade_counts) / action_counts.replace(
        0.0,
        np.nan,
    )
    return BaseFactorPanel(values=factor_values, frequency="daily")


def calculate_quarterly_roe(market_data: MarketData) -> BaseFactorPanel:
    """读取按公告日生效的单季度 ROE 与报告期状态。"""
    history = build_financial_field_history(
        market_data.get_financial_records("financial_indicators"),
        "S_QFA_ROE",
        market_data.calendar,
        market_data.membership.columns,
    )
    return BaseFactorPanel(
        values=history.values,
        frequency="quarterly",
        report_periods=history.report_periods,
        quarterly_events=history.events,
    )


def calculate_income_factor(
    base_factor_name: str,
    market_data: MarketData,
) -> BaseFactorPanel:
    """构造单季营收、利润及其两类标准化意外。"""
    if base_factor_name in {"quarterly_revenue", "revenue_sur"}:
        cumulative_field = "TOT_OPER_REV"
    else:
        cumulative_field = "NET_PROFIT_EXCL_MIN_INT_INC"
    history = build_financial_field_history(
        market_data.get_financial_records("financial_income"),
        cumulative_field,
        market_data.calendar,
        market_data.membership.columns,
        cumulative=True,
    )
    quarterly_values = history.values
    report_periods = history.report_periods

    if base_factor_name in {"revenue_sur", "earnings_sue"}:
        factor_values = build_seasonal_surprise(
            quarterly_values,
            report_periods,
        )
    elif base_factor_name == "consensus_np_sue":
        consensus_net_profit = market_data.get_panel(
            "consensus_suntime",
            "con_np",
        ).astype("float64")
        factor_values = build_consensus_profit_surprise(
            quarterly_values,
            report_periods,
            consensus_net_profit,
        )
    else:
        factor_values = quarterly_values

    quarterly_events = None
    if base_factor_name in {"quarterly_revenue", "quarterly_net_profit"}:
        quarterly_events = history.events

    return BaseFactorPanel(
        values=factor_values,
        frequency="quarterly",
        report_periods=report_periods,
        quarterly_events=quarterly_events,
    )
