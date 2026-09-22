"""按真实公告顺序维护财务报告期历史，并物化当前季度状态。"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass

import numpy as np
import pandas as pd


@dataclass(frozen=True)
class QuarterlyHistory:
    """保存当前最新季度面板及构造它所需的全部 PIT 报告事件。"""

    values: pd.DataFrame
    report_periods: pd.DataFrame
    events: pd.DataFrame


def build_financial_field_history(
    financial_records: pd.DataFrame,
    field_name: str,
    calendar: pd.DatetimeIndex,
    asset_codes: Sequence[str],
    cumulative: bool = False,
) -> QuarterlyHistory:
    """从财务事件记录构造直接字段或累计字段的单季度历史。"""
    field_events = _select_field_events(financial_records, field_name)
    if cumulative:
        field_events = _convert_cumulative_events_to_quarters(field_events)
    values, report_periods = materialize_latest_quarter(
        field_events,
        calendar,
        asset_codes,
    )
    return QuarterlyHistory(values, report_periods, field_events)


def combine_quarterly_histories(
    histories: Mapping[str, QuarterlyHistory],
    calculator: Callable[[Mapping[str, float]], float],
    calendar: pd.DatetimeIndex,
    asset_codes: Sequence[str],
) -> QuarterlyHistory:
    """在同一报告期各分项均按当时版本更新后计算复合季度指标。"""
    named_events = []
    for component_name, history in histories.items():
        component_events = history.events.copy()
        component_events["component"] = component_name
        named_events.append(component_events)
    all_events = pd.concat(named_events, ignore_index=True)
    combined_events = _calculate_combined_events(all_events, histories.keys(), calculator)
    values, report_periods = materialize_latest_quarter(
        combined_events,
        calendar,
        asset_codes,
    )
    return QuarterlyHistory(values, report_periods, combined_events)


def transform_quarterly_history(
    history: QuarterlyHistory,
    calculator: Callable[[Mapping[pd.Period, float], pd.Period], float],
    calendar: pd.DatetimeIndex,
    asset_codes: Sequence[str],
) -> QuarterlyHistory:
    """历史季度到达或修订时，重算所有受影响的季度派生值。"""
    transformed_rows: list[dict[str, object]] = []
    for asset_code, asset_events in history.events.groupby("asset_code", sort=False):
        source_values: dict[pd.Period, float] = {}
        transformed_values: dict[pd.Period, float] = {}
        asset_events = asset_events.sort_values(["date", "report_period"], kind="mergesort")
        for event_date, date_events in asset_events.groupby("date", sort=True):
            for event in date_events.itertuples(index=False):
                report_quarter = pd.Timestamp(event.report_period).to_period("Q")
                source_values[report_quarter] = _finite_float(event.value)

            for report_quarter in sorted(source_values):
                transformed_value = calculator(source_values, report_quarter)
                previous_value = transformed_values.get(report_quarter, np.nan)
                if _same_numeric_state(previous_value, transformed_value):
                    continue
                transformed_values[report_quarter] = transformed_value
                transformed_rows.append(
                    {
                        "date": event_date,
                        "asset_code": asset_code,
                        "report_period": report_quarter.end_time.normalize(),
                        "value": transformed_value,
                    }
                )

    transformed_events = pd.DataFrame.from_records(
        transformed_rows,
        columns=["date", "asset_code", "report_period", "value"],
    )
    values, report_periods = materialize_latest_quarter(
        transformed_events,
        calendar,
        asset_codes,
    )
    return QuarterlyHistory(values, report_periods, transformed_events)


def materialize_latest_quarter(
    quarterly_events: pd.DataFrame,
    calendar: pd.DatetimeIndex,
    asset_codes: Sequence[str],
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """把报告事件展开成当前最大报告期的日频值和报告期面板。"""
    current_events = _current_quarter_events(quarterly_events)
    value_events = current_events.pivot(
        index="date",
        columns="asset_code",
        values="value",
    )
    period_events = current_events.pivot(
        index="date",
        columns="asset_code",
        values="report_period",
    )
    values = _align_event_panel(value_events, calendar, asset_codes)
    report_periods = _align_event_panel(period_events, calendar, asset_codes)
    return values.astype("float64"), report_periods


def apply_quarterly_event_operator(
    quarterly_events: pd.DataFrame,
    calendar: pd.DatetimeIndex,
    asset_codes: Sequence[str],
    calculator: Callable[[Mapping[pd.Period, float], pd.Period, float], float],
) -> pd.DataFrame:
    """任一历史季度到达或修订后，重算当时最新季度的时序结果。"""
    operator_rows: list[dict[str, object]] = []
    for asset_code, asset_events in quarterly_events.groupby("asset_code", sort=False):
        values_by_quarter: dict[pd.Period, float] = {}
        asset_events = asset_events.sort_values(["date", "report_period"], kind="mergesort")
        for event_date, date_events in asset_events.groupby("date", sort=True):
            for event in date_events.itertuples(index=False):
                report_quarter = pd.Timestamp(event.report_period).to_period("Q")
                values_by_quarter[report_quarter] = _finite_float(event.value)
            current_quarter = max(values_by_quarter)
            current_value = values_by_quarter[current_quarter]
            operator_rows.append(
                {
                    "date": event_date,
                    "asset_code": asset_code,
                    "value": calculator(
                        values_by_quarter,
                        current_quarter,
                        current_value,
                    ),
                }
            )

    operator_events = pd.DataFrame.from_records(operator_rows)
    event_panel = operator_events.pivot(
        index="date",
        columns="asset_code",
        values="value",
    )
    return _align_event_panel(event_panel, calendar, asset_codes).astype("float64")


def _select_field_events(
    financial_records: pd.DataFrame,
    field_name: str,
) -> pd.DataFrame:
    """同一公告日、股票和报告期按版本顺序保留最后一条字段状态。"""
    selected_columns = [
        column_name
        for column_name in (
            "date",
            "asset_code",
            "report_period",
            "operation_time",
            "source_order",
            field_name,
        )
        if column_name in financial_records.columns
    ]
    events = financial_records.loc[:, selected_columns].copy()
    events = events.dropna(subset=["date", "asset_code", "report_period"])
    sort_columns = ["asset_code", "date", "report_period"]
    if "operation_time" in events.columns:
        sort_columns.append("operation_time")
    if "source_order" in events.columns:
        sort_columns.append("source_order")
    events = events.sort_values(sort_columns, kind="mergesort")
    business_keys = ["date", "asset_code", "report_period"]
    events = events.drop_duplicates(business_keys, keep="last")
    events = events.rename(columns={field_name: "value"})
    events["value"] = pd.to_numeric(events["value"], errors="coerce")
    return events.loc[:, [*business_keys, "value"]].reset_index(drop=True)


def _convert_cumulative_events_to_quarters(
    cumulative_events: pd.DataFrame,
) -> pd.DataFrame:
    """累计报表更新时同步重算本季度及受其影响的下一季度。"""
    quarterly_rows: list[dict[str, object]] = []
    for asset_code, asset_events in cumulative_events.groupby("asset_code", sort=False):
        cumulative_by_quarter: dict[pd.Period, float] = {}
        asset_events = asset_events.sort_values(["date", "report_period"], kind="mergesort")
        for event_date, date_events in asset_events.groupby("date", sort=True):
            affected_quarters: set[pd.Period] = set()
            for event in date_events.itertuples(index=False):
                report_quarter = pd.Timestamp(event.report_period).to_period("Q")
                cumulative_by_quarter[report_quarter] = _finite_float(event.value)
                affected_quarters.add(report_quarter)
                next_quarter = report_quarter + 1
                if next_quarter.year == report_quarter.year:
                    affected_quarters.add(next_quarter)

            for report_quarter in sorted(affected_quarters):
                if report_quarter not in cumulative_by_quarter:
                    continue
                quarterly_rows.append(
                    {
                        "date": event_date,
                        "asset_code": asset_code,
                        "report_period": report_quarter.end_time.normalize(),
                        "value": _single_quarter_value(
                            cumulative_by_quarter,
                            report_quarter,
                        ),
                    }
                )
    return pd.DataFrame.from_records(
        quarterly_rows,
        columns=["date", "asset_code", "report_period", "value"],
    )


def _single_quarter_value(
    cumulative_by_quarter: Mapping[pd.Period, float],
    report_quarter: pd.Period,
) -> float:
    """按自然年累计口径还原一个报告季度的单季度数值。"""
    current_value = cumulative_by_quarter[report_quarter]
    if not np.isfinite(current_value):
        return np.nan
    if report_quarter.quarter == 1:
        return current_value
    prior_value = cumulative_by_quarter.get(report_quarter - 1, np.nan)
    if not np.isfinite(prior_value):
        return np.nan
    return current_value - prior_value


def _calculate_combined_events(
    all_events: pd.DataFrame,
    component_names: Sequence[str],
    calculator: Callable[[Mapping[str, float]], float],
) -> pd.DataFrame:
    """任一分项公告或修订时，按当时已知的同报告期分项重算结果。"""
    output_rows: list[dict[str, object]] = []
    for asset_code, asset_events in all_events.groupby("asset_code", sort=False):
        values_by_component = {name: {} for name in component_names}
        asset_events = asset_events.sort_values(["date", "report_period"], kind="mergesort")
        for event_date, date_events in asset_events.groupby("date", sort=True):
            affected_periods: set[pd.Timestamp] = set()
            for event in date_events.itertuples(index=False):
                report_period = pd.Timestamp(event.report_period)
                values_by_component[event.component][report_period] = _finite_float(
                    event.value
                )
                affected_periods.add(report_period)

            for report_period in sorted(affected_periods):
                component_values = {
                    component_name: values_by_component[component_name].get(
                        report_period,
                        np.nan,
                    )
                    for component_name in component_names
                }
                output_rows.append(
                    {
                        "date": event_date,
                        "asset_code": asset_code,
                        "report_period": report_period,
                        "value": calculator(component_values),
                    }
                )
    return pd.DataFrame.from_records(
        output_rows,
        columns=["date", "asset_code", "report_period", "value"],
    )


def _current_quarter_events(quarterly_events: pd.DataFrame) -> pd.DataFrame:
    """每次公告后输出截至当时最大报告期的当前值。"""
    output_rows: list[dict[str, object]] = []
    for asset_code, asset_events in quarterly_events.groupby("asset_code", sort=False):
        values_by_period: dict[pd.Timestamp, float] = {}
        asset_events = asset_events.sort_values(["date", "report_period"], kind="mergesort")
        for event_date, date_events in asset_events.groupby("date", sort=True):
            for event in date_events.itertuples(index=False):
                values_by_period[pd.Timestamp(event.report_period)] = _finite_float(
                    event.value
                )
            current_period = max(values_by_period)
            output_rows.append(
                {
                    "date": event_date,
                    "asset_code": asset_code,
                    "report_period": current_period,
                    "value": values_by_period[current_period],
                }
            )
    return pd.DataFrame.from_records(output_rows)


def _align_event_panel(
    event_panel: pd.DataFrame,
    calendar: pd.DatetimeIndex,
    asset_codes: Sequence[str],
) -> pd.DataFrame:
    """只向未来延续公告状态，并将非交易日公告带入下一交易日。"""
    combined_dates = calendar.union(event_panel.index).sort_values()
    aligned = event_panel.reindex(combined_dates).ffill().reindex(calendar)
    return aligned.reindex(columns=pd.Index(asset_codes, name="asset_code"))


def _finite_float(value: object) -> float:
    """把事件字段统一为有限浮点数，其他状态记为缺失。"""
    numeric_value = float(value) if pd.notna(value) else np.nan
    if np.isfinite(numeric_value):
        return numeric_value
    return np.nan


def _same_numeric_state(first_value: float, second_value: float) -> bool:
    """比较两个季度派生值，并把两个缺失状态视为相同。"""
    if np.isnan(first_value) and np.isnan(second_value):
        return True
    return first_value == second_value
