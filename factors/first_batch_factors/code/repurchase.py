"""构造回购承诺、执行和资本配置纪律因子。"""

from __future__ import annotations

from collections.abc import Callable

import numpy as np
import pandas as pd

from factors.fundamental_utils import safe_divide
from src.data.market_data import MarketData

REPURCHASE_FACTORS = {
    "buyback_plan_intensity",
    "buyback_execution_intensity",
    "buyback_completion_ratio",
    "buyback_execution_speed",
    "buyback_failure_event",
    "buyback_repeat_count_3y",
    "buyback_objective_group",
    "buyback_value_confirmation",
}

COMPLETION_KEYWORDS = ("完成", "实施完毕", "completed", "complete")
FAILURE_KEYWORDS = ("终止", "停止", "取消", "未实施", "failed", "cancel")
CANCELLATION_OBJECTIVE_KEYWORDS = ("注销", "cancel")
INCENTIVE_OBJECTIVE_KEYWORDS = ("激励", "员工持股", "incentive", "employee")


def calculate_repurchase_factor(
    factor_name: str,
    market_data: MarketData,
) -> pd.DataFrame:
    """根据固定名称计算一个回购因子。"""
    records = _prepare_repurchase_records(market_data)
    total_shares = _calculate_total_shares(market_data)

    if factor_name == "buyback_plan_intensity":
        expected_quantity = _numeric_column(records, "EXP_QTY")
        expected_quantity_state = _records_to_panel(
            records,
            expected_quantity,
            market_data,
            aggregation="sum",
            forward_fill=True,
        )
        return safe_divide(expected_quantity_state, total_shares)

    if factor_name == "buyback_execution_intensity":
        executed_quantity = _numeric_column(records, "QTY")
        executed_quantity_state = _records_to_panel(
            records,
            executed_quantity,
            market_data,
            aggregation="sum",
            forward_fill=True,
        )
        return safe_divide(executed_quantity_state, total_shares)

    completion_ratio = _completion_ratio(records)
    if factor_name == "buyback_completion_ratio":
        return _records_to_panel(
            records,
            completion_ratio,
            market_data,
            aggregation="max",
            forward_fill=True,
        )
    if factor_name == "buyback_execution_speed":
        elapsed_days = (
            records["effective_date"] - records["source_date"]
        ).dt.days.clip(lower=5)
        execution_speed = completion_ratio / elapsed_days
        return _records_to_panel(
            records,
            execution_speed,
            market_data,
            aggregation="max",
            forward_fill=True,
        )
    if factor_name == "buyback_failure_event":
        status_text = records["STATUS"].astype("string")
        textual_status = status_text.str.contains(
            r"[A-Za-z一-龥]",
            regex=True,
            na=False,
        )
        failure_values = _status_matches(records, FAILURE_KEYWORDS).astype("float64")
        failure_values = failure_values.where(textual_status)
        return _records_to_panel(
            records,
            failure_values,
            market_data,
            aggregation="max",
            forward_fill=True,
        )
    if factor_name == "buyback_repeat_count_3y":
        completion_events = _completed_records(records, completion_ratio).astype("float64")
        event_panel = _records_to_panel(
            records,
            completion_events,
            market_data,
            aggregation="sum",
            forward_fill=False,
        ).fillna(0.0)
        return event_panel.rolling(window=756, min_periods=1).sum()
    if factor_name == "buyback_objective_group":
        objective_scores = _objective_scores(records)
        return _records_to_panel(
            records,
            objective_scores,
            market_data,
            aggregation="max",
            forward_fill=True,
        )
    if factor_name == "buyback_value_confirmation":
        execution_intensity = calculate_repurchase_factor(
            "buyback_execution_intensity",
            market_data,
        )
        valuation_yield = _positive_reciprocal(
            market_data.get_panel("ev_indicator", "s_val_evtoebitda")
        )
        execution_score = execution_intensity.rank(axis=1, pct=True)
        valuation_score = valuation_yield.rank(axis=1, pct=True)
        return (execution_score + valuation_score) / 2.0
    raise ValueError(f"未知回购因子: {factor_name}")


def _prepare_repurchase_records(market_data: MarketData) -> pd.DataFrame:
    """把 Wind 回购记录转换成公告后首个交易日可用的保守时点。"""
    records = market_data.get_records("repo_wind").copy()
    operation_dates = pd.to_datetime(
        records["OPDATE"],
        errors="coerce",
    ).dt.normalize()
    source_dates = pd.to_datetime(records["source_date"]).dt.normalize()
    records["source_date"] = source_dates
    records["effective_date"] = pd.concat(
        [source_dates, operation_dates],
        axis=1,
    ).max(axis=1)

    calendar = market_data.calendar
    effective_positions = calendar.searchsorted(
        records["effective_date"],
        side="right",
    )
    within_calendar = effective_positions < len(calendar)
    records = records.loc[within_calendar].copy()
    records["effective_date"] = calendar.take(effective_positions[within_calendar])
    return records


def _calculate_total_shares(market_data: MarketData) -> pd.DataFrame:
    """用总市值和未复权收盘价还原总股本，避免依赖未确认单位的回购金额。"""
    total_market_value = market_data.get_panel(
        "stock_valuation",
        "S_VAL_MV",
    ).astype("float64")
    close_price = market_data.get_panel(
        "stock_quote",
        "S_DQ_CLOSE",
    ).astype("float64")
    return safe_divide(total_market_value * 10_000.0, close_price)


def _numeric_column(records: pd.DataFrame, column_name: str) -> pd.Series:
    """把 Wind 数值字段显式转换成浮点数。"""
    return pd.to_numeric(records[column_name], errors="coerce")


def _completion_ratio(records: pd.DataFrame) -> pd.Series:
    """优先使用 Wind 完成率，缺失时用实际股数除以计划股数。"""
    funds_ratio = _normalize_ratio(
        _numeric_column(records, "REPURCHASE_FUNDS_RATIO")
    )
    shares_ratio = _normalize_ratio(
        _numeric_column(records, "REPURCHASE_SHARES_RATIO")
    )
    reported_ratio = pd.concat([funds_ratio, shares_ratio], axis=1).max(axis=1)
    quantity_ratio = _numeric_column(records, "QTY") / _numeric_column(
        records,
        "EXP_QTY",
    ).replace(0.0, np.nan)
    return reported_ratio.combine_first(quantity_ratio).clip(lower=0.0)


def _normalize_ratio(ratio_values: pd.Series) -> pd.Series:
    """把明显采用百分数表示的完成率统一转换成 0 到 1 附近的比例。"""
    normalized_values = ratio_values.copy()
    percentage_mask = normalized_values.abs() > 1.5
    normalized_values.loc[percentage_mask] /= 100.0
    return normalized_values


def _status_matches(
    records: pd.DataFrame,
    keywords: tuple[str, ...],
) -> pd.Series:
    """按中英文状态关键词识别回购业务状态。"""
    status_text = records["STATUS"].astype("string").str.lower()
    matches = pd.Series(False, index=records.index)
    for keyword in keywords:
        matches |= status_text.str.contains(keyword.lower(), na=False)
    return matches


def _completed_records(
    records: pd.DataFrame,
    completion_ratio: pd.Series,
) -> pd.Series:
    """识别已经完成或完成率达到 99% 的独立回购记录。"""
    return _status_matches(records, COMPLETION_KEYWORDS) | completion_ratio.ge(0.99)


def _objective_scores(records: pd.DataFrame) -> pd.Series:
    """突出注销目的，并把激励用途保留为中性对照组。"""
    objective_text = records["STOCK_REPO_OBJECTIVE_CODE"].astype("string").str.lower()
    textual_objective = objective_text.str.contains(
        r"[A-Za-z一-龥]",
        regex=True,
        na=False,
    )
    cancellation = _text_matches(objective_text, CANCELLATION_OBJECTIVE_KEYWORDS)
    incentive = _text_matches(objective_text, INCENTIVE_OBJECTIVE_KEYWORDS)
    scores = pd.Series(np.nan, index=records.index, dtype="float64")
    scores.loc[textual_objective] = 0.5
    scores.loc[incentive] = 0.0
    scores.loc[cancellation] = 1.0
    return scores


def _text_matches(
    text_values: pd.Series,
    keywords: tuple[str, ...],
) -> pd.Series:
    """判断文本是否包含任一业务关键词。"""
    matches = pd.Series(False, index=text_values.index)
    for keyword in keywords:
        matches |= text_values.str.contains(keyword.lower(), na=False)
    return matches


def _positive_reciprocal(multiple_values: pd.DataFrame) -> pd.DataFrame:
    """只对正的 EV/EBITDA 取倒数。"""
    positive_multiple = multiple_values.astype("float64").where(multiple_values > 0)
    return 1.0 / positive_multiple


def _records_to_panel(
    records: pd.DataFrame,
    record_values: pd.Series,
    market_data: MarketData,
    aggregation: str | Callable,
    forward_fill: bool,
) -> pd.DataFrame:
    """把公告明细聚合到公告后首个交易日，并按需延续最新状态。"""
    event_records = records[["effective_date", "asset_code"]].assign(
        factor_value=record_values,
    )
    event_records = event_records.dropna(
        subset=["effective_date", "asset_code", "factor_value"]
    )
    grouped_values = event_records.groupby(
        ["effective_date", "asset_code"],
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
