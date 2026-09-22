"""构造分红收益、持续性、现金覆盖和削减风险因子。"""

from __future__ import annotations

import numpy as np
import pandas as pd

from factors.fundamental_utils import safe_divide
from factors.second_batch_factors.code.event_utils import (
    move_to_next_trading_day,
    move_to_trading_day_on_or_after,
    numeric_column,
    panel_values_at_records,
    panel_values_before_dates,
    records_to_panel,
    text_contains_any,
)
from src.data.market_data import MarketData

DIVIDEND_FACTORS = {
    "announced_dividend_yield",
    "dividend_growth_yoy",
    "dividend_payout_ratio",
    "dividend_cash_coverage",
    "dividend_cut_event",
    "realized_dividend_yield_ttm",
    "dividend_stability_5y",
    "dividend_sustainability_composite",
}

SPECIAL_DIVIDEND_KEYWORDS = ("特别", "特殊", "special")
CANCELLATION_KEYWORDS = ("取消", "终止", "不实施", "撤销", "cancel", "terminate")


def calculate_dividend_factor(
    factor_name: str,
    market_data: MarketData,
) -> pd.DataFrame:
    """根据固定名称计算一个分红因子。"""
    records = _prepare_dividend_records(market_data)
    report_events = _ordinary_report_events(records)

    if factor_name == "announced_dividend_yield":
        prior_close = panel_values_before_dates(
            market_data.get_panel("stock_quote", "S_DQ_CLOSE").astype("float64"),
            report_events["source_date"],
            report_events["asset_code"],
        )
        announced_yield = report_events["cash_dps"] / prior_close
        return records_to_panel(
            report_events,
            announced_yield,
            market_data,
            aggregation="last",
            forward_fill=True,
        )
    if factor_name == "dividend_growth_yoy":
        growth_events = _year_over_year_report_change(report_events, "cash_dps")
        return _event_values_to_state(growth_events, market_data)
    if factor_name == "dividend_payout_ratio":
        net_profit = _matching_financial_values(
            report_events,
            market_data,
            source_name="financial_income",
            field_name="NET_PROFIT_EXCL_MIN_INT_INC",
        )
        positive_profit = net_profit.where(net_profit > 0)
        payout_ratio = report_events["total_cash_dividend"] / positive_profit
        return records_to_panel(
            report_events,
            payout_ratio,
            market_data,
            aggregation="last",
            forward_fill=True,
        )
    if factor_name == "dividend_cash_coverage":
        operating_cashflow = _matching_financial_values(
            report_events,
            market_data,
            source_name="financial_cashflow",
            field_name="NET_CASH_FLOWS_OPER_ACT",
        )
        cash_coverage = operating_cashflow / report_events[
            "total_cash_dividend"
        ].replace(0.0, np.nan)
        return records_to_panel(
            report_events,
            cash_coverage,
            market_data,
            aggregation="last",
            forward_fill=True,
        )
    if factor_name == "dividend_cut_event":
        return _calculate_cut_events(records, report_events, market_data)
    if factor_name == "realized_dividend_yield_ttm":
        return _calculate_realized_yield(records, market_data)
    if factor_name == "dividend_stability_5y":
        stability_events = _calculate_stability_events(report_events)
        return _event_values_to_state(stability_events, market_data)
    if factor_name == "dividend_sustainability_composite":
        return _calculate_sustainability_composite(market_data)
    raise ValueError(f"未知分红因子: {factor_name}")


def _prepare_dividend_records(market_data: MarketData) -> pd.DataFrame:
    """清理分红明细，并把方案公告移动到下一交易日。"""
    records = market_data.get_records("dividend_wind").copy()
    records["source_date"] = pd.to_datetime(
        records["source_date"],
        errors="coerce",
    ).dt.normalize()
    records["report_period"] = pd.to_datetime(
        records["report_period"],
        errors="coerce",
    ).dt.normalize()
    records["effective_date"] = move_to_next_trading_day(
        records["source_date"],
        market_data.calendar,
    )
    records["cash_dps"] = numeric_column(records, "CASH_DVD_PER_SH_PRE_TAX")
    records["total_cash_dividend"] = numeric_column(records, "TOT_CASH_DVD")
    records["is_special"] = _special_dividend_mask(records)
    records["is_cancelled"] = text_contains_any(
        records["S_DIV_PROGRESS"],
        CANCELLATION_KEYWORDS,
    )
    return records.dropna(
        subset=["asset_code", "source_date", "report_period", "effective_date"]
    )


def _special_dividend_mask(records: pd.DataFrame) -> pd.Series:
    """用方案对象和分配方式识别特别分红。"""
    dividend_description = (
        records["S_DIV_OBJECT"].astype("string").fillna("")
        + " "
        + records["DISTRIBUTION_MODEL"].astype("string").fillna("")
    )
    return text_contains_any(dividend_description, SPECIAL_DIVIDEND_KEYWORDS)


def _ordinary_report_events(records: pd.DataFrame) -> pd.DataFrame:
    """保留普通现金分红的每次公告版本，并按报告期去重。"""
    ordinary_records = records.loc[~records["is_special"]].copy()
    ordinary_records.loc[ordinary_records["is_cancelled"], "cash_dps"] = 0.0
    ordinary_records.loc[
        ordinary_records["is_cancelled"],
        "total_cash_dividend",
    ] = 0.0
    sort_columns = ["asset_code", "report_period", "effective_date", "source_date"]
    ordinary_records = ordinary_records.sort_values(sort_columns)
    return ordinary_records.drop_duplicates(
        subset=["asset_code", "report_period", "effective_date"],
        keep="last",
    )


def _year_over_year_report_change(
    report_events: pd.DataFrame,
    value_column: str,
) -> pd.DataFrame:
    """按相同月日的上年报告期计算公告版本同比变化。"""
    output_events = report_events.copy()
    output_events["factor_value"] = np.nan
    for asset_code, asset_events in output_events.groupby("asset_code", sort=False):
        values_by_period: dict[pd.Timestamp, float] = {}
        for event_index in asset_events.sort_values("effective_date").index:
            report_period = output_events.at[event_index, "report_period"]
            current_value = output_events.at[event_index, value_column]
            prior_period = report_period - pd.DateOffset(years=1)
            prior_value = values_by_period.get(prior_period)
            if prior_value is not None and abs(prior_value) > 1e-12:
                output_events.at[event_index, "factor_value"] = (
                    current_value / abs(prior_value) - 1.0
                )
            values_by_period[report_period] = current_value
    return output_events


def _matching_financial_values(
    report_events: pd.DataFrame,
    market_data: MarketData,
    source_name: str,
    field_name: str,
) -> pd.Series:
    """读取公告日已经可得且报告期完全一致的财务值。"""
    financial_values = market_data.get_panel(source_name, field_name).astype("float64")
    financial_periods = market_data.get_panel(source_name, "REPORT_PERIOD")
    matched_values = pd.to_numeric(
        panel_values_at_records(financial_values, report_events),
        errors="coerce",
    )
    matched_periods = pd.to_datetime(
        panel_values_at_records(financial_periods, report_events),
        errors="coerce",
    )
    report_periods = pd.to_datetime(report_events["report_period"], errors="coerce")
    return matched_values.where(matched_periods.eq(report_periods))


def _calculate_cut_events(
    records: pd.DataFrame,
    report_events: pd.DataFrame,
    market_data: MarketData,
) -> pd.DataFrame:
    """识别普通 DPS 同比至少下降 30% 或方案取消的公告。"""
    growth_events = _year_over_year_report_change(report_events, "cash_dps")
    cut_values = growth_events["factor_value"].le(-0.30).astype("float64")
    cut_values = cut_values.where(growth_events["factor_value"].notna(), 0.0)
    cancelled_records = records.loc[records["is_cancelled"] & ~records["is_special"]]
    cancellation_panel = records_to_panel(
        cancelled_records,
        pd.Series(1.0, index=cancelled_records.index),
        market_data,
        aggregation="max",
        forward_fill=False,
    )
    cut_panel = records_to_panel(
        growth_events,
        cut_values,
        market_data,
        aggregation="max",
        forward_fill=False,
    )
    return pd.concat([cut_panel, cancellation_panel]).groupby(level=0).max().reindex(
        market_data.calendar
    )


def _calculate_realized_yield(
    records: pd.DataFrame,
    market_data: MarketData,
) -> pd.DataFrame:
    """按除息日汇总过去 252 个交易日已兑现普通 DPS。"""
    realized_records = records.loc[~records["is_special"] & ~records["is_cancelled"]].copy()
    ex_dates = pd.to_datetime(realized_records["EX_DT"], errors="coerce").dt.normalize()
    realization_dates = pd.concat(
        [realized_records["source_date"], ex_dates],
        axis=1,
    ).max(axis=1)
    realized_records["realization_date"] = move_to_trading_day_on_or_after(
        realization_dates,
        market_data.calendar,
    )
    realized_records = realized_records.sort_values(
        ["asset_code", "report_period", "realization_date", "source_date"]
    ).drop_duplicates(
        subset=["asset_code", "report_period", "realization_date"],
        keep="last",
    )
    realized_dps = records_to_panel(
        realized_records,
        realized_records["cash_dps"],
        market_data,
        aggregation="sum",
        forward_fill=False,
        date_column="realization_date",
    ).fillna(0.0)
    trailing_dps = realized_dps.rolling(window=252, min_periods=1).sum()
    close_price = market_data.get_panel("stock_quote", "S_DQ_CLOSE").astype("float64")
    return safe_divide(trailing_dps, close_price)


def _calculate_stability_events(report_events: pd.DataFrame) -> pd.DataFrame:
    """在年度方案公告后计算包含零分红年份的五年 DPS 稳定性。"""
    annual_events = report_events[
        report_events["report_period"].dt.month.eq(12)
        & report_events["report_period"].dt.day.eq(31)
    ].copy()
    annual_events["factor_value"] = np.nan
    for asset_code, asset_events in annual_events.groupby("asset_code", sort=False):
        dps_by_year: dict[int, float] = {}
        for event_index in asset_events.sort_values("effective_date").index:
            report_year = annual_events.at[event_index, "report_period"].year
            dps_by_year[report_year] = annual_events.at[event_index, "cash_dps"]
            observed_years = [year for year in range(report_year - 4, report_year + 1) if year in dps_by_year]
            if len(observed_years) < 3:
                continue
            five_year_dps = np.array(
                [dps_by_year.get(year, 0.0) for year in range(report_year - 4, report_year + 1)],
                dtype="float64",
            )
            mean_dps = five_year_dps.mean()
            if abs(mean_dps) <= 1e-12:
                continue
            annual_events.at[event_index, "factor_value"] = -five_year_dps.std(
                ddof=0
            ) / abs(mean_dps)
    return annual_events


def _event_values_to_state(
    event_records: pd.DataFrame,
    market_data: MarketData,
) -> pd.DataFrame:
    """把报告事件值延续到下一次有效披露。"""
    return records_to_panel(
        event_records,
        event_records["factor_value"],
        market_data,
        aggregation="last",
        forward_fill=True,
    )


def _calculate_sustainability_composite(market_data: MarketData) -> pd.DataFrame:
    """合成收益率、增长、覆盖和稳定性，并惩罚削减及极端支付率。"""
    component_names = (
        "announced_dividend_yield",
        "dividend_growth_yoy",
        "dividend_cash_coverage",
        "dividend_stability_5y",
    )
    component_scores = [
        calculate_dividend_factor(component_name, market_data).rank(axis=1, pct=True)
        for component_name in component_names
    ]
    available_count = sum(score.notna().astype("int8") for score in component_scores)
    score_sum = sum(score.fillna(0.0) for score in component_scores)
    composite = (score_sum / available_count.where(available_count > 0)).where(
        available_count == len(component_scores)
    )

    payout_ratio = calculate_dividend_factor("dividend_payout_ratio", market_data)
    extreme_payout_penalty = payout_ratio.gt(1.2).astype("float64") * 0.20
    recent_cut_penalty = (
        calculate_dividend_factor("dividend_cut_event", market_data)
        .fillna(0.0)
        .rolling(window=60, min_periods=1)
        .max()
        * 0.30
    )
    return composite - extreme_payout_penalty - recent_cut_penalty
