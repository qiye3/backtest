"""构造业绩快报的预期差、增长质量和历史可信度因子。"""

from __future__ import annotations

import numpy as np
import pandas as pd

from factors.second_batch_factors.code.event_utils import (
    panel_values_at_records,
    panel_values_before_dates,
    records_to_panel,
)
from src.data.market_data import MarketData

PROFIT_EXPRESS_FACTORS = {
    "express_consensus_surprise",
    "express_notice_surprise",
    "express_profit_growth",
    "express_revenue_growth",
    "express_net_margin_change",
    "express_profit_revenue_gap",
    "express_final_revision",
    "historical_express_reliability",
}


def calculate_profit_express_factor(
    factor_name: str,
    market_data: MarketData,
) -> pd.DataFrame:
    """根据固定名称计算一个业绩快报因子。"""
    express_events = _extract_express_events(market_data)

    if factor_name == "express_consensus_surprise":
        consensus_profit = panel_values_before_dates(
            market_data.get_panel("consensus_suntime", "con_np").astype("float64"),
            express_events["source_date"],
            express_events["asset_code"],
        )
        surprise = (
            express_events["net_profit"] - consensus_profit
        ) / consensus_profit.abs().replace(0.0, np.nan)
        return _event_state(express_events, surprise, market_data)
    if factor_name == "express_notice_surprise":
        notice_profit = _matching_notice_profit(express_events, market_data)
        surprise = (
            express_events["net_profit"] - notice_profit
        ) / notice_profit.abs().replace(0.0, np.nan)
        return _event_state(express_events, surprise, market_data)

    comparison_events = _add_prior_year_values(express_events)
    profit_growth = _growth_rate(
        comparison_events["net_profit"],
        comparison_events["prior_net_profit"],
    )
    revenue_growth = _growth_rate(
        comparison_events["revenue"],
        comparison_events["prior_revenue"],
    )
    if factor_name == "express_profit_growth":
        return _event_state(comparison_events, profit_growth, market_data)
    if factor_name == "express_revenue_growth":
        return _event_state(comparison_events, revenue_growth, market_data)
    if factor_name == "express_net_margin_change":
        current_margin = comparison_events["net_profit"] / comparison_events[
            "revenue"
        ].replace(0.0, np.nan)
        prior_margin = comparison_events["prior_net_profit"] / comparison_events[
            "prior_revenue"
        ].replace(0.0, np.nan)
        return _event_state(
            comparison_events,
            current_margin - prior_margin,
            market_data,
        )
    if factor_name == "express_profit_revenue_gap":
        valid_growth = comparison_events["prior_net_profit"].gt(0)
        valid_growth &= comparison_events["prior_revenue"].gt(0)
        growth_gap = (profit_growth - revenue_growth).where(valid_growth)
        return _event_state(comparison_events, growth_gap, market_data)
    if factor_name == "express_final_revision":
        return _calculate_final_revision(express_events, market_data)
    if factor_name == "historical_express_reliability":
        final_revision = _calculate_final_revision(express_events, market_data)
        reliability_events = -final_revision.abs()
        return reliability_events.expanding(min_periods=1).mean()
    raise ValueError(f"未知业绩快报因子: {factor_name}")


def _extract_express_events(market_data: MarketData) -> pd.DataFrame:
    """从快报 PIT 状态中还原每次新公告或更正事件。"""
    report_periods = market_data.get_panel("profit_express", "REPORT_PERIOD")
    net_profit = market_data.get_panel(
        "profit_express",
        "net_profit_excl_min_int_inc",
    ).astype("float64")
    revenue = market_data.get_panel("profit_express", "oper_rev").astype("float64")
    announcement_dates = market_data.get_panel("profit_express", "ann_dt")

    event_rows: list[dict[str, object]] = []
    for asset_code in report_periods.columns:
        asset_periods = pd.to_datetime(report_periods[asset_code], errors="coerce")
        new_event = asset_periods.notna()
        new_event &= (
            asset_periods.ne(asset_periods.shift(1))
            | net_profit[asset_code].ne(net_profit[asset_code].shift(1))
            | revenue[asset_code].ne(revenue[asset_code].shift(1))
        )
        for effective_date in report_periods.index[new_event]:
            event_rows.append(
                {
                    "asset_code": asset_code,
                    "source_date": pd.to_datetime(
                        announcement_dates.at[effective_date, asset_code],
                        errors="coerce",
                    ),
                    "effective_date": effective_date,
                    "report_period": asset_periods.at[effective_date],
                    "net_profit": net_profit.at[effective_date, asset_code],
                    "revenue": revenue.at[effective_date, asset_code],
                }
            )
    return pd.DataFrame(event_rows)


def _add_prior_year_values(express_events: pd.DataFrame) -> pd.DataFrame:
    """为每次快报事件附加上年同报告期的已知快报结果。"""
    comparison_events = express_events.copy()
    comparison_events["prior_net_profit"] = np.nan
    comparison_events["prior_revenue"] = np.nan
    for asset_code, asset_events in comparison_events.groupby(
        "asset_code",
        sort=False,
    ):
        values_by_period: dict[pd.Timestamp, tuple[float, float]] = {}
        for event_index in asset_events.sort_values("effective_date").index:
            report_period = comparison_events.at[event_index, "report_period"]
            prior_period = report_period - pd.DateOffset(years=1)
            prior_values = values_by_period.get(prior_period)
            if prior_values is not None:
                comparison_events.at[event_index, "prior_net_profit"] = prior_values[0]
                comparison_events.at[event_index, "prior_revenue"] = prior_values[1]
            values_by_period[report_period] = (
                comparison_events.at[event_index, "net_profit"],
                comparison_events.at[event_index, "revenue"],
            )
    return comparison_events


def _growth_rate(current_values: pd.Series, prior_values: pd.Series) -> pd.Series:
    """仅对正的上年基数计算普通同比增长。"""
    positive_prior = prior_values.where(prior_values > 0)
    return current_values / positive_prior - 1.0


def _matching_notice_profit(
    express_events: pd.DataFrame,
    market_data: MarketData,
) -> pd.Series:
    """读取快报生效时同报告期的最后一份业绩预告中值。"""
    notice_lower = market_data.get_panel(
        "profit_notice",
        "s_profitnotice_netprofitmin",
    ).astype("float64")
    notice_upper = market_data.get_panel(
        "profit_notice",
        "s_profitnotice_netprofitmax",
    ).astype("float64")
    notice_midpoint = (notice_lower + notice_upper) / 2.0
    notice_periods = market_data.get_panel("profit_notice", "REPORT_PERIOD")
    matched_profit = pd.to_numeric(
        panel_values_at_records(notice_midpoint, express_events),
        errors="coerce",
    )
    matched_periods = pd.to_datetime(
        panel_values_at_records(notice_periods, express_events),
        errors="coerce",
    )
    return matched_profit.where(matched_periods.eq(express_events["report_period"]))


def _calculate_final_revision(
    express_events: pd.DataFrame,
    market_data: MarketData,
) -> pd.DataFrame:
    """在正式财报首次披露时计算其相对快报的修正。"""
    actual_profit = market_data.get_panel(
        "financial_income",
        "NET_PROFIT_EXCL_MIN_INT_INC",
    ).astype("float64")
    actual_periods = market_data.get_panel("financial_income", "REPORT_PERIOD")
    output = pd.DataFrame(
        np.nan,
        index=market_data.calendar,
        columns=market_data.membership.columns,
    )

    express_by_asset_period: dict[tuple[str, pd.Timestamp], float] = {}
    for event in express_events.sort_values("effective_date").itertuples(index=False):
        express_by_asset_period[(event.asset_code, event.report_period)] = event.net_profit

    for asset_code in actual_periods.columns:
        asset_periods = pd.to_datetime(actual_periods[asset_code], errors="coerce")
        new_actual = asset_periods.notna() & asset_periods.ne(asset_periods.shift(1))
        for announcement_date in actual_periods.index[new_actual]:
            report_period = asset_periods.at[announcement_date]
            express_profit = express_by_asset_period.get((asset_code, report_period))
            if express_profit is None or abs(express_profit) <= 1e-12:
                continue
            output.at[announcement_date, asset_code] = (
                actual_profit.at[announcement_date, asset_code] - express_profit
            ) / abs(express_profit)
    return output


def _event_state(
    event_records: pd.DataFrame,
    factor_values: pd.Series,
    market_data: MarketData,
) -> pd.DataFrame:
    """把快报事件值延续到下一份快报。"""
    return records_to_panel(
        event_records,
        factor_values,
        market_data,
        aggregation="last",
        forward_fill=True,
    )
