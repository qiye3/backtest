"""构造企业价值的绝对、相对和价值陷阱过滤因子。"""

from __future__ import annotations

import numpy as np
import pandas as pd

from factors.fundamental_utils import safe_divide
from src.data.market_data import MarketData

ENTERPRISE_VALUE_FACTORS = {
    "ebitda_ev",
    "ebitda_ev_v2",
    "industry_relative_ebitda_ev",
    "ev_ebitda_percentile_1y",
    "ev_ebitda_percentile_5y",
    "ev_definition_spread",
    "ev_growth_adjusted",
    "ev_quality_composite",
}


def calculate_enterprise_value_factor(
    factor_name: str,
    market_data: MarketData,
) -> pd.DataFrame:
    """根据固定名称计算一个企业价值因子。"""
    primary_multiple = _ev_field(market_data, "s_val_evtoebitda")
    primary_yield = _positive_reciprocal(primary_multiple)

    if factor_name == "ebitda_ev":
        return primary_yield
    if factor_name == "ebitda_ev_v2":
        secondary_multiple = _ev_field(market_data, "s_val_evtoebitda2")
        return _positive_reciprocal(secondary_multiple)
    if factor_name == "industry_relative_ebitda_ev":
        industries = market_data.get_panel(
            "industry_history",
            "ind_class_code",
        )
        return _industry_relative_values(primary_yield, industries)
    if factor_name == "ev_ebitda_percentile_1y":
        return _rolling_percentile(primary_multiple, window=240, min_periods=120)
    if factor_name == "ev_ebitda_percentile_5y":
        return _rolling_percentile(primary_multiple, window=1200, min_periods=600)
    if factor_name == "ev_definition_spread":
        primary_ev = _ev_field(market_data, "s_val_ev1")
        secondary_ev = _ev_field(market_data, "s_val_ev2")
        return safe_divide(primary_ev - secondary_ev, primary_ev.abs()).abs()
    if factor_name == "ev_growth_adjusted":
        expected_growth = market_data.get_panel(
            "consensus_suntime",
            "con_npcgrate_2y",
        ).astype("float64")
        return _mean_percentile_scores(primary_yield, expected_growth)
    if factor_name == "ev_quality_composite":
        roic = market_data.get_panel(
            "financial_indicators",
            "S_FA_ROIC",
        ).astype("float64")
        operating_cashflow_margin = market_data.get_panel(
            "financial_indicators",
            "S_FA_OCFTOOR",
        ).astype("float64")
        return _mean_percentile_scores(
            primary_yield,
            roic,
            operating_cashflow_margin,
        )
    raise ValueError(f"未知企业价值因子: {factor_name}")


def _ev_field(market_data: MarketData, field_name: str) -> pd.DataFrame:
    """读取一个日频企业价值字段。"""
    return market_data.get_panel("ev_indicator", field_name).astype("float64")


def _positive_reciprocal(multiple_values: pd.DataFrame) -> pd.DataFrame:
    """只对正的估值倍数取倒数，负 EBITDA 不制造伪高收益率。"""
    positive_multiple = multiple_values.where(multiple_values > 0)
    unit_values = pd.DataFrame(
        1.0,
        index=multiple_values.index,
        columns=multiple_values.columns,
    )
    return safe_divide(unit_values, positive_multiple)


def _industry_relative_values(
    factor_values: pd.DataFrame,
    industries: pd.DataFrame,
) -> pd.DataFrame:
    """逐日减去所属行业有效样本的中位数。"""
    relative_values = pd.DataFrame(
        np.nan,
        index=factor_values.index,
        columns=factor_values.columns,
    )
    for evaluation_date in factor_values.index:
        daily_values = factor_values.loc[evaluation_date]
        daily_industries = industries.loc[evaluation_date]
        industry_medians = daily_values.groupby(daily_industries).transform("median")
        relative_values.loc[evaluation_date] = daily_values - industry_medians
    return relative_values


def _rolling_percentile(
    multiple_values: pd.DataFrame,
    window: int,
    min_periods: int,
) -> pd.DataFrame:
    """计算逐股票历史估值分位；原值越低代表越便宜。"""
    positive_multiple = multiple_values.where(multiple_values > 0)
    return positive_multiple.rolling(
        window=window,
        min_periods=min_periods,
    ).rank(pct=True)


def _mean_percentile_scores(*components: pd.DataFrame) -> pd.DataFrame:
    """把同向分量转换为每日截面百分位后等权合成。"""
    component_scores = [component.rank(axis=1, pct=True) for component in components]
    available_count = sum(
        component_score.notna().astype("int8")
        for component_score in component_scores
    )
    score_sum = sum(
        component_score.fillna(0.0)
        for component_score in component_scores
    )
    minimum_components = len(component_scores)
    return (score_sum / available_count.where(available_count > 0)).where(
        available_count >= minimum_components
    )
