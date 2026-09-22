"""构造业绩预告的增长、预期差、质量和可信度因子。"""

from __future__ import annotations

import numpy as np
import pandas as pd

from factors.fundamental_utils import safe_divide
from src.data.market_data import MarketData

PROFIT_NOTICE_FACTORS = {
    "notice_profit_growth_mid",
    "notice_consensus_surprise",
    "notice_revision",
    "notice_deducted_growth_mid",
    "notice_nonrecurring_gap",
    "notice_range_width",
    "notice_style_event",
    "historical_notice_accuracy",
}

STYLE_SCORES = {
    "扭亏": 1.0,
    "预增": 0.8,
    "略增": 0.5,
    "续盈": 0.2,
    "预减": -0.5,
    "略减": -0.5,
    "续亏": -0.8,
    "首亏": -1.0,
}


def calculate_profit_notice_factor(
    factor_name: str,
    market_data: MarketData,
) -> pd.DataFrame:
    """根据固定名称计算一个业绩预告因子。"""
    profit_growth_mid = _midpoint(
        _notice_field(market_data, "s_profitnotice_changemin"),
        _notice_field(market_data, "s_profitnotice_changemax"),
    )
    deducted_growth_mid = _midpoint(
        _notice_field(market_data, "s_profitnotice_changemin_ded"),
        _notice_field(market_data, "s_profitnotice_changemax_ded"),
    )
    notice_profit_mid = _midpoint(
        _notice_field(market_data, "s_profitnotice_netprofitmin"),
        _notice_field(market_data, "s_profitnotice_netprofitmax"),
    )

    if factor_name == "notice_profit_growth_mid":
        return profit_growth_mid
    if factor_name == "notice_deducted_growth_mid":
        return deducted_growth_mid
    if factor_name == "notice_nonrecurring_gap":
        return profit_growth_mid - deducted_growth_mid
    if factor_name == "notice_consensus_surprise":
        consensus_profit = market_data.get_panel(
            "consensus_suntime",
            "con_np",
        ).astype("float64")
        return safe_divide(
            notice_profit_mid - consensus_profit,
            consensus_profit.abs(),
        )
    if factor_name == "notice_revision":
        report_periods = market_data.get_panel(
            "profit_notice",
            "REPORT_PERIOD",
        )
        return _calculate_notice_revision(notice_profit_mid, report_periods)
    if factor_name == "notice_range_width":
        lower_profit = _notice_field(market_data, "s_profitnotice_netprofitmin")
        upper_profit = _notice_field(market_data, "s_profitnotice_netprofitmax")
        return safe_divide(
            upper_profit - lower_profit,
            notice_profit_mid.abs(),
        )
    if factor_name == "notice_style_event":
        style_values = market_data.get_panel(
            "profit_notice",
            "s_profitnotice_style",
        )
        return _map_notice_style(style_values)
    if factor_name == "historical_notice_accuracy":
        return _calculate_historical_accuracy(notice_profit_mid, market_data)
    raise ValueError(f"未知业绩预告因子: {factor_name}")


def _notice_field(market_data: MarketData, field_name: str) -> pd.DataFrame:
    """读取一个按公告次日生效的业绩预告数值字段。"""
    return market_data.get_panel("profit_notice", field_name).astype("float64")


def _midpoint(lower_values: pd.DataFrame, upper_values: pd.DataFrame) -> pd.DataFrame:
    """计算预告区间中值；任一边界缺失时不擅自补齐。"""
    return (lower_values + upper_values) / 2.0


def _calculate_notice_revision(
    notice_profit_mid: pd.DataFrame,
    report_periods: pd.DataFrame,
) -> pd.DataFrame:
    """只在同一报告期数值发生变化时计算修正，并延续该修正状态。"""
    prior_profit_mid = notice_profit_mid.shift(1)
    same_report_period = report_periods.eq(report_periods.shift(1))
    value_changed = notice_profit_mid.ne(prior_profit_mid)
    revision_events = safe_divide(
        notice_profit_mid - prior_profit_mid,
        prior_profit_mid.abs(),
    ).where(same_report_period & value_changed)

    revision_state = pd.DataFrame(
        np.nan,
        index=notice_profit_mid.index,
        columns=notice_profit_mid.columns,
    )
    for asset_code in notice_profit_mid.columns:
        revision_state[asset_code] = revision_events[asset_code].groupby(
            report_periods[asset_code],
            dropna=False,
        ).ffill()
    return revision_state


def _map_notice_style(style_values: pd.DataFrame) -> pd.DataFrame:
    """把有明确盈亏方向的预告类型映射为可回测的有序事件分数。"""
    style_text = style_values.astype("string")
    style_scores = pd.DataFrame(
        np.nan,
        index=style_values.index,
        columns=style_values.columns,
    )
    for style_keyword, style_score in STYLE_SCORES.items():
        keyword_matches = style_text.apply(
            lambda column: column.str.contains(style_keyword, na=False)
        )
        style_scores = style_scores.mask(keyword_matches, style_score)
    return style_scores


def _calculate_historical_accuracy(
    notice_profit_mid: pd.DataFrame,
    market_data: MarketData,
) -> pd.DataFrame:
    """在正式财报公布后累计历史预告准确度，不使用当前未完成报告期。"""
    notice_periods = market_data.get_panel("profit_notice", "REPORT_PERIOD")
    actual_profit = market_data.get_panel(
        "financial_income",
        "NET_PROFIT_EXCL_MIN_INT_INC",
    ).astype("float64")
    actual_periods = market_data.get_panel("financial_income", "REPORT_PERIOD")
    matching_period = notice_periods.eq(actual_periods)
    new_actual_report = actual_periods.ne(actual_periods.shift(1))
    scaled_error = safe_divide(
        (notice_profit_mid - actual_profit).abs(),
        actual_profit.abs(),
    )
    accuracy_events = (-scaled_error).where(matching_period & new_actual_report)
    return accuracy_events.expanding(min_periods=1).mean()
