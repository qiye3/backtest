"""构造客户、供应商、产品结构和海外收入因子。"""

from __future__ import annotations

import numpy as np
import pandas as pd

from factors.second_batch_factors.code.event_utils import (
    financial_report_available_dates,
    move_to_next_trading_day,
    normalize_ratio,
    numeric_column,
    panel_values_at_records,
    records_to_panel,
)
from src.data.market_data import MarketData

BUSINESS_STRUCTURE_FACTORS = {
    "top5_customer_share",
    "customer_concentration_change",
    "customer_churn",
    "top5_supplier_share",
    "supplier_concentration_change",
    "customer_supplier_dependence",
    "high_margin_segment_share_change",
    "overseas_revenue_share_change",
}


def calculate_business_structure_factor(
    factor_name: str,
    market_data: MarketData,
) -> pd.DataFrame:
    """根据固定名称计算一个客户供应商或主营结构因子。"""
    customer_records = _prepare_structure_records("customer", market_data)
    supplier_records = _prepare_structure_records("supplier", market_data)
    customer_events = _concentration_events(customer_records)
    supplier_events = _concentration_events(supplier_records)

    if factor_name == "top5_customer_share":
        return _event_state(customer_events, "factor_value", market_data)
    if factor_name == "customer_concentration_change":
        customer_changes = _year_over_year_change(customer_events)
        return _event_state(customer_changes, "factor_value", market_data)
    if factor_name == "customer_churn":
        churn_events = _customer_churn_events(customer_records)
        return _event_state(churn_events, "factor_value", market_data)
    if factor_name == "top5_supplier_share":
        return _event_state(supplier_events, "factor_value", market_data)
    if factor_name == "supplier_concentration_change":
        supplier_changes = _year_over_year_change(supplier_events)
        return _event_state(supplier_changes, "factor_value", market_data)
    if factor_name == "customer_supplier_dependence":
        customer_share = _event_state(customer_events, "factor_value", market_data)
        supplier_share = _event_state(supplier_events, "factor_value", market_data)
        customer_rank = customer_share.rank(axis=1, pct=True)
        supplier_rank = supplier_share.rank(axis=1, pct=True)
        return (customer_rank + supplier_rank) / 2.0
    if factor_name == "high_margin_segment_share_change":
        product_records = _prepare_structure_records("mb_product_rank", market_data)
        product_mix_events = _high_margin_share_events(product_records)
        product_mix_changes = _year_over_year_change(product_mix_events)
        return _event_state(product_mix_changes, "factor_value", market_data)
    if factor_name == "overseas_revenue_share_change":
        consist_records = _prepare_structure_records("mb_consist", market_data)
        overseas_events = _overseas_share_events(consist_records, market_data)
        overseas_changes = _year_over_year_change(overseas_events)
        return _event_state(overseas_changes, "factor_value", market_data)
    raise ValueError(f"未知客户供应商与主营构成因子: {factor_name}")


def _prepare_structure_records(
    source_name: str,
    market_data: MarketData,
) -> pd.DataFrame:
    """用财报首次公告日为缺公告日的经营结构记录建立可得日。"""
    records = market_data.get_records(source_name).copy()
    records["report_period"] = pd.to_datetime(
        records["report_period"],
        errors="coerce",
    ).dt.normalize()
    records["source_date"] = financial_report_available_dates(records, market_data)
    records["effective_date"] = move_to_next_trading_day(
        records["source_date"],
        market_data.calendar,
    )
    return records.dropna(
        subset=["asset_code", "report_period", "source_date", "effective_date"]
    )


def _concentration_events(records: pd.DataFrame) -> pd.DataFrame:
    """按公司和报告期汇总前五项披露占比。"""
    concentration_records = records.assign(
        normalized_pct=normalize_ratio(records["pct"]),
    )
    grouped = concentration_records.groupby(
        ["asset_code", "report_period", "source_date", "effective_date"],
        as_index=False,
        sort=True,
    )["normalized_pct"].sum(min_count=1)
    return grouped.rename(columns={"normalized_pct": "factor_value"})


def _year_over_year_change(report_events: pd.DataFrame) -> pd.DataFrame:
    """按相同月日的上年报告期计算结构指标变化。"""
    change_events = report_events.copy()
    change_events["current_value"] = change_events["factor_value"]
    change_events["factor_value"] = np.nan
    for asset_code, asset_events in change_events.groupby("asset_code", sort=False):
        values_by_period: dict[pd.Timestamp, float] = {}
        for event_index in asset_events.sort_values("effective_date").index:
            report_period = change_events.at[event_index, "report_period"]
            prior_period = report_period - pd.DateOffset(years=1)
            prior_value = values_by_period.get(prior_period)
            current_value = change_events.at[event_index, "current_value"]
            if prior_value is not None:
                change_events.at[event_index, "factor_value"] = current_value - prior_value
            values_by_period[report_period] = current_value
    return change_events


def _customer_churn_events(customer_records: pd.DataFrame) -> pd.DataFrame:
    """用前五大客户集合的年度 Jaccard 距离衡量客户更替。"""
    grouped_names = customer_records.groupby(
        ["asset_code", "report_period", "source_date", "effective_date"],
        sort=True,
    )["customer_name_rank"].agg(
        lambda values: frozenset(values.astype("string").dropna())
    )
    churn_events = grouped_names.reset_index(name="customer_names")
    churn_events["factor_value"] = np.nan
    for asset_code, asset_events in churn_events.groupby("asset_code", sort=False):
        names_by_period: dict[pd.Timestamp, frozenset[str]] = {}
        for event_index in asset_events.sort_values("effective_date").index:
            report_period = churn_events.at[event_index, "report_period"]
            current_names = churn_events.at[event_index, "customer_names"]
            prior_names = names_by_period.get(report_period - pd.DateOffset(years=1))
            if prior_names is not None:
                union_names = current_names | prior_names
                if union_names:
                    overlap_ratio = len(current_names & prior_names) / len(union_names)
                    churn_events.at[event_index, "factor_value"] = 1.0 - overlap_ratio
            names_by_period[report_period] = current_names
    return churn_events


def _high_margin_share_events(product_records: pd.DataFrame) -> pd.DataFrame:
    """计算每期高于公司加权平均毛利率的产品收入占比。"""
    product_data = product_records.assign(
        product_revenue=numeric_column(product_records, "mb_revenue_product"),
        product_cost=numeric_column(product_records, "mb_cost_product"),
    )
    output_rows: list[dict[str, object]] = []
    group_columns = ["asset_code", "report_period", "source_date", "effective_date"]
    for group_keys, report_products in product_data.groupby(group_columns, sort=True):
        valid_products = report_products.loc[report_products["product_revenue"].gt(0)].copy()
        if valid_products.empty:
            continue
        valid_products["gross_margin"] = 1.0 - (
            valid_products["product_cost"] / valid_products["product_revenue"]
        )
        total_revenue = valid_products["product_revenue"].sum(min_count=1)
        weighted_margin = (
            valid_products["gross_margin"] * valid_products["product_revenue"]
        ).sum(min_count=1) / total_revenue
        high_margin_revenue = valid_products.loc[
            valid_products["gross_margin"] > weighted_margin,
            "product_revenue",
        ].sum(min_count=1)
        output_rows.append(
            {
                "asset_code": group_keys[0],
                "report_period": group_keys[1],
                "source_date": group_keys[2],
                "effective_date": group_keys[3],
                "factor_value": high_margin_revenue / total_revenue,
            }
        )
    return pd.DataFrame(output_rows)


def _overseas_share_events(
    consist_records: pd.DataFrame,
    market_data: MarketData,
) -> pd.DataFrame:
    """计算海外收入占同期财务报表营业收入的比例。"""
    overseas_events = consist_records.assign(
        overseas_revenue=numeric_column(consist_records, "mb_overseas_revenue"),
    ).groupby(
        ["asset_code", "report_period", "source_date", "effective_date"],
        as_index=False,
        sort=True,
    )["overseas_revenue"].max()
    total_revenue_panel = market_data.get_panel(
        "financial_income",
        "TOT_OPER_REV",
    ).astype("float64")
    income_period_panel = market_data.get_panel("financial_income", "REPORT_PERIOD")
    total_revenue = pd.to_numeric(
        panel_values_at_records(total_revenue_panel, overseas_events),
        errors="coerce",
    )
    matched_periods = pd.to_datetime(
        panel_values_at_records(income_period_panel, overseas_events),
        errors="coerce",
    )
    total_revenue = total_revenue.where(
        matched_periods.eq(overseas_events["report_period"])
    )
    overseas_events["factor_value"] = overseas_events[
        "overseas_revenue"
    ] / total_revenue.replace(0.0, np.nan)
    return overseas_events


def _event_state(
    event_records: pd.DataFrame,
    value_column: str,
    market_data: MarketData,
) -> pd.DataFrame:
    """把低频经营结构数据从可得日向前延续。"""
    return records_to_panel(
        event_records,
        event_records[value_column],
        market_data,
        aggregation="last",
        forward_fill=True,
    )
