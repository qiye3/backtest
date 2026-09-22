"""第二批公告明细因子共用的时点与面板转换工具。"""

from __future__ import annotations

from collections.abc import Callable

import numpy as np
import pandas as pd

from src.data.market_data import MarketData


def numeric_column(records: pd.DataFrame, column_name: str) -> pd.Series:
    """把明细表中的一个业务字段转换为浮点数。"""
    return pd.to_numeric(records[column_name], errors="coerce")


def normalize_ratio(ratio_values: pd.Series) -> pd.Series:
    """把明显采用百分数表达的比例统一为小数。"""
    normalized_values = pd.to_numeric(ratio_values, errors="coerce").astype("float64")
    percentage_mask = normalized_values.abs() > 1.5
    normalized_values.loc[percentage_mask] /= 100.0
    return normalized_values


def move_to_next_trading_day(
    source_dates: pd.Series,
    calendar: pd.DatetimeIndex,
) -> pd.Series:
    """把公开日期移动到其后的首个交易日。"""
    normalized_dates = pd.to_datetime(source_dates, errors="coerce").dt.normalize()
    output_dates = pd.Series(pd.NaT, index=source_dates.index, dtype="datetime64[ns]")
    valid_dates = normalized_dates.notna()
    event_positions = calendar.searchsorted(
        normalized_dates.loc[valid_dates],
        side="right",
    )
    within_calendar = event_positions < len(calendar)
    valid_indices = normalized_dates.loc[valid_dates].index[within_calendar]
    output_dates.loc[valid_indices] = calendar.take(event_positions[within_calendar])
    return output_dates


def move_to_trading_day_on_or_after(
    source_dates: pd.Series,
    calendar: pd.DatetimeIndex,
) -> pd.Series:
    """把已知日期映射到当天或之后的首个交易日。"""
    normalized_dates = pd.to_datetime(source_dates, errors="coerce").dt.normalize()
    output_dates = pd.Series(pd.NaT, index=source_dates.index, dtype="datetime64[ns]")
    valid_dates = normalized_dates.notna()
    event_positions = calendar.searchsorted(
        normalized_dates.loc[valid_dates],
        side="left",
    )
    within_calendar = event_positions < len(calendar)
    valid_indices = normalized_dates.loc[valid_dates].index[within_calendar]
    output_dates.loc[valid_indices] = calendar.take(event_positions[within_calendar])
    return output_dates


def records_to_panel(
    records: pd.DataFrame,
    record_values: pd.Series,
    market_data: MarketData,
    aggregation: str | Callable,
    forward_fill: bool,
    date_column: str = "effective_date",
) -> pd.DataFrame:
    """把公告明细聚合为标准日期乘股票面板。"""
    event_records = records[[date_column, "asset_code"]].assign(
        factor_value=record_values,
    )
    event_records = event_records.dropna(
        subset=[date_column, "asset_code", "factor_value"]
    )
    grouped_values = event_records.groupby(
        [date_column, "asset_code"],
        sort=True,
    )["factor_value"].agg(aggregation)
    event_panel = grouped_values.unstack("asset_code")
    event_panel = event_panel.reindex(
        index=market_data.calendar,
        columns=market_data.membership.columns,
    )
    if forward_fill:
        return event_panel.ffill()
    return event_panel


def panel_values_at_records(
    panel: pd.DataFrame,
    records: pd.DataFrame,
    date_column: str = "effective_date",
) -> pd.Series:
    """按记录的日期和股票读取对应面板值。"""
    output_values = pd.Series(pd.NA, index=records.index, dtype="object")
    for record_index, record in records[[date_column, "asset_code"]].iterrows():
        evaluation_date = record[date_column]
        asset_code = record["asset_code"]
        if pd.isna(evaluation_date) or asset_code not in panel.columns:
            continue
        if evaluation_date not in panel.index:
            continue
        output_values.loc[record_index] = panel.at[evaluation_date, asset_code]
    return output_values


def panel_values_before_dates(
    panel: pd.DataFrame,
    source_dates: pd.Series,
    asset_codes: pd.Series,
) -> pd.Series:
    """读取每条公告严格之前最近交易日的面板值。"""
    normalized_dates = pd.to_datetime(source_dates, errors="coerce").dt.normalize()
    output_values = pd.Series(np.nan, index=source_dates.index, dtype="float64")
    calendar = panel.index
    for record_index in source_dates.index:
        source_date = normalized_dates.loc[record_index]
        asset_code = asset_codes.loc[record_index]
        if pd.isna(source_date) or asset_code not in panel.columns:
            continue
        prior_position = calendar.searchsorted(source_date, side="left") - 1
        if prior_position < 0:
            continue
        output_values.loc[record_index] = panel.iloc[prior_position][asset_code]
    return output_values


def financial_report_available_dates(
    records: pd.DataFrame,
    market_data: MarketData,
) -> pd.Series:
    """用同公司同报告期财报首次公告日为无公告日明细建立可得日。"""
    report_period_panel = market_data.get_panel(
        "financial_income",
        "REPORT_PERIOD",
    )
    availability_by_asset_period: dict[tuple[str, pd.Timestamp], pd.Timestamp] = {}
    for asset_code in report_period_panel.columns:
        asset_periods = pd.to_datetime(
            report_period_panel[asset_code],
            errors="coerce",
        )
        new_report = asset_periods.notna() & asset_periods.ne(asset_periods.shift(1))
        for announcement_date, report_period in asset_periods.loc[new_report].items():
            availability_by_asset_period[(asset_code, report_period.normalize())] = (
                announcement_date
            )

    source_dates = pd.Series(pd.NaT, index=records.index, dtype="datetime64[ns]")
    report_periods = pd.to_datetime(records["report_period"], errors="coerce")
    for record_index in records.index:
        report_period = report_periods.loc[record_index]
        if pd.isna(report_period):
            continue
        lookup_key = (records.at[record_index, "asset_code"], report_period.normalize())
        source_dates.loc[record_index] = availability_by_asset_period.get(
            lookup_key,
            pd.NaT,
        )
    return source_dates


def text_contains_any(text_values: pd.Series, keywords: tuple[str, ...]) -> pd.Series:
    """判断业务文本是否包含任一中英文关键词。"""
    normalized_text = text_values.astype("string").str.lower()
    matches = pd.Series(False, index=text_values.index)
    for keyword in keywords:
        matches |= normalized_text.str.contains(keyword.lower(), na=False)
    return matches
