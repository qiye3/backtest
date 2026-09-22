"""从框架数据源构造质量基础因子。"""

from __future__ import annotations

from collections.abc import Callable, Mapping

import numpy as np
import pandas as pd

from factors.quality_factors.code.utils import (
    QualityBasePanel,
    safe_divide,
)
from factors.quarterly_history import (
    QuarterlyHistory,
    build_financial_field_history,
    combine_quarterly_histories,
    transform_quarterly_history,
)
from src.data.market_data import MarketData

MARKET_VALUE_UNIT_TO_CURRENCY = 10_000.0

INDICATOR_FIELDS = {
    "roe_level": "S_FA_ROE",
    "roe_q": "S_QFA_ROE",
    "roe_deducted": "S_FA_ROE_DEDUCTED",
    "roic": "S_FA_ROIC",
    "roa": "S_FA_ROA",
    "gross_margin": "S_FA_GROSSPROFITMARGIN",
    "net_margin": "S_FA_NETPROFITMARGIN",
    "operating_margin": "S_FA_OPTOGR",
    "ocf_to_revenue": "S_FA_OCFTOOR",
    "cash_realization_rate": "S_FA_OCFTOPROFIT",
    "deducted_profit_to_profit": "S_FA_DEDUCTEDPROFITTOPROFIT",
    "sales_cash_to_revenue": "S_FA_SALESCASHINTOOR",
    "debt_to_assets": "S_FA_DEBTTOASSETS",
    "equity_multiplier": "S_FA_ASSETSTOEQUITY",
    "asset_turnover": "S_FA_ASSETSTURN",
    "tangible_asset_ratio": "S_FA_TANGIBLEASSETSTOASSETS",
    "current_ratio": "S_FA_CURRENT",
    "quick_ratio": "S_FA_QUICK",
    "fcff": "S_FA_FCFF",
}

DAILY_FIELDS = {
    "roe_expected": ("consensus_suntime", "con_roe"),
    "analyst_forecast_revision": ("consensus_suntime", "con_npgrate_13w"),
    "analyst_coverage": ("consensus_wind", "prediction_number"),
}


def calculate_base_factor(
    base_factor_name: str,
    market_data: MarketData,
) -> QualityBasePanel:
    """根据固定名称分派直接字段或跨报表公式。"""
    if base_factor_name in INDICATOR_FIELDS:
        return _indicator_panel(market_data, INDICATOR_FIELDS[base_factor_name])
    if base_factor_name in DAILY_FIELDS:
        source_name, field_name = DAILY_FIELDS[base_factor_name]
        values = market_data.get_panel(source_name, field_name).astype("float64")
        return QualityBasePanel(values=values, frequency="daily")

    calculators = {
        "ocf_to_net_profit": _calculate_ocf_to_net_profit,
        "accruals_to_assets": _calculate_accruals_to_assets,
        "fcf_yield": _calculate_fcf_yield,
        "capex_to_ocf": _calculate_capex_to_ocf,
        "interest_debt_to_ocf": _calculate_interest_debt_to_ocf,
        "accounts_receivable_to_revenue": _calculate_receivables_to_revenue,
        "inventory_change_to_assets": _calculate_inventory_change_to_assets,
        "goodwill_to_equity": _calculate_goodwill_to_equity,
        "quality_composite": _calculate_quality_composite,
        "pb_roe_composite": _calculate_pb_roe_composite,
    }
    calculator = calculators.get(base_factor_name)
    if calculator is None:
        raise ValueError(f"未知质量基础因子: {base_factor_name}")
    return calculator(market_data)


def _indicator_panel(market_data: MarketData, field_name: str) -> QualityBasePanel:
    """读取财务指标值及与其共用的 PIT 报告期。"""
    history = _financial_history(
        market_data,
        "financial_indicators",
        field_name,
    )
    return _quality_panel_from_history(history)


def _financial_history(
    market_data: MarketData,
    source_name: str,
    field_name: str,
) -> QuarterlyHistory:
    """读取保留迟到报告和历史修订的单字段季度历史。"""
    return build_financial_field_history(
        market_data.get_financial_records(source_name),
        field_name,
        market_data.calendar,
        market_data.membership.columns,
    )


def _quality_panel_from_history(history: QuarterlyHistory) -> QualityBasePanel:
    """把共享季度历史转换成质量因子使用的基础面板。"""
    return QualityBasePanel(
        history.values,
        "quarterly",
        history.report_periods,
        history.events,
    )


def _combine_financial_histories(
    market_data: MarketData,
    component_specs: Mapping[str, tuple[str, str]],
    calculator: Callable[[Mapping[str, float]], float],
) -> QualityBasePanel:
    """按公告时点对齐多个财务来源的同报告期字段。"""
    histories = {
        component_name: _financial_history(market_data, source_name, field_name)
        for component_name, (source_name, field_name) in component_specs.items()
    }
    combined_history = combine_quarterly_histories(
        histories,
        calculator,
        market_data.calendar,
        market_data.membership.columns,
    )
    return _quality_panel_from_history(combined_history)


def _divide_components(
    component_values: Mapping[str, float],
    numerator_name: str,
    denominator_name: str,
) -> float:
    """计算有限且非零的季度事件比率。"""
    numerator = component_values[numerator_name]
    denominator = component_values[denominator_name]
    if not np.isfinite(numerator) or not np.isfinite(denominator):
        return np.nan
    if abs(denominator) <= 1e-12:
        return np.nan
    return numerator / denominator


def _calculate_ocf_to_net_profit(market_data: MarketData) -> QualityBasePanel:
    """计算经营现金流相对归母净利润的利润含金量。"""
    return _combine_financial_histories(
        market_data,
        {
            "ocf": ("financial_cashflow", "NET_CASH_FLOWS_OPER_ACT"),
            "profit": ("financial_income", "NET_PROFIT_EXCL_MIN_INT_INC"),
        },
        lambda values: _divide_components(values, "ocf", "profit"),
    )


def _calculate_accruals_to_assets(market_data: MarketData) -> QualityBasePanel:
    """计算归母净利润减经营现金流后占总资产的比例。"""
    def calculate_accruals(values: Mapping[str, float]) -> float:
        profit = values["profit"]
        ocf = values["ocf"]
        assets = values["assets"]
        if not np.isfinite(profit) or not np.isfinite(ocf):
            return np.nan
        return _divide_components(
            {"accruals": profit - ocf, "assets": assets},
            "accruals",
            "assets",
        )

    return _combine_financial_histories(
        market_data,
        {
            "profit": ("financial_income", "NET_PROFIT_EXCL_MIN_INT_INC"),
            "ocf": ("financial_cashflow", "NET_CASH_FLOWS_OPER_ACT"),
            "assets": ("financial_balance_sheet", "TOT_ASSETS"),
        },
        calculate_accruals,
    )


def _calculate_fcf_yield(market_data: MarketData) -> QualityBasePanel:
    """计算企业自由现金流相对总市值加净债务的收益率。"""
    fcff = market_data.get_panel("financial_indicators", "S_FA_FCFF").astype("float64")
    net_debt = market_data.get_panel(
        "financial_indicators",
        "S_FA_NETDEBT",
    ).astype("float64")
    market_value = market_data.get_panel("stock_valuation", "S_VAL_MV").astype("float64")
    # Wind 总市值单位为万元，财务指标中的 FCFF 与净债务使用元。
    market_value_in_currency = market_value * MARKET_VALUE_UNIT_TO_CURRENCY
    return QualityBasePanel(
        safe_divide(fcff, market_value_in_currency + net_debt),
        "daily",
    )


def _calculate_capex_to_ocf(market_data: MarketData) -> QualityBasePanel:
    """计算购建长期资产现金支出占经营现金流的比例。"""
    return _combine_financial_histories(
        market_data,
        {
            "capex": ("financial_cashflow", "CASH_PAY_ACQ_CONST_FIOLTA"),
            "ocf": ("financial_cashflow", "NET_CASH_FLOWS_OPER_ACT"),
        },
        lambda values: _divide_components(values, "capex", "ocf"),
    )


def _calculate_interest_debt_to_ocf(market_data: MarketData) -> QualityBasePanel:
    """计算净债务相对经营现金流的覆盖压力。"""
    return _combine_financial_histories(
        market_data,
        {
            "net_debt": ("financial_indicators", "S_FA_NETDEBT"),
            "ocf": ("financial_cashflow", "NET_CASH_FLOWS_OPER_ACT"),
        },
        lambda values: _divide_components(values, "net_debt", "ocf"),
    )


def _calculate_receivables_to_revenue(market_data: MarketData) -> QualityBasePanel:
    """计算应收账款占营业总收入的比例。"""
    return _combine_financial_histories(
        market_data,
        {
            "receivables": ("financial_balance_sheet", "ACCOUNTS_RECEIVABLE"),
            "revenue": ("financial_income", "TOT_OPER_REV"),
        },
        lambda values: _divide_components(values, "receivables", "revenue"),
    )


def _calculate_inventory_change_to_assets(market_data: MarketData) -> QualityBasePanel:
    """计算存货较上一自然季度的增量占当前总资产比例。"""
    inventory_history = _financial_history(
        market_data,
        "financial_balance_sheet",
        "INVENTORIES",
    )
    inventory_change_history = transform_quarterly_history(
        inventory_history,
        lambda values, quarter: values[quarter] - values.get(quarter - 1, np.nan),
        market_data.calendar,
        market_data.membership.columns,
    )
    assets_history = _financial_history(
        market_data,
        "financial_balance_sheet",
        "TOT_ASSETS",
    )
    combined_history = combine_quarterly_histories(
        {
            "inventory_change": inventory_change_history,
            "assets": assets_history,
        },
        lambda values: _divide_components(values, "inventory_change", "assets"),
        market_data.calendar,
        market_data.membership.columns,
    )
    return _quality_panel_from_history(combined_history)


def _calculate_goodwill_to_equity(market_data: MarketData) -> QualityBasePanel:
    """计算商誉占归母股东权益的比例。"""
    return _combine_financial_histories(
        market_data,
        {
            "goodwill": ("financial_balance_sheet", "GOODWILL"),
            "equity": (
                "financial_balance_sheet",
                "TOT_SHRHLDR_EQY_EXCL_MIN_INT",
            ),
        },
        lambda values: _divide_components(values, "goodwill", "equity"),
    )


def _cross_section_score(values: pd.DataFrame, higher_is_better: bool) -> pd.DataFrame:
    """把异量纲基础值转换为每日截面百分位分数。"""
    scores = values.rank(axis=1, pct=True)
    return scores if higher_is_better else 1.0 - scores


def _calculate_quality_composite(market_data: MarketData) -> QualityBasePanel:
    """等权合成 ROE、ROIC、现金含量和低杠杆四个质量维度。"""
    component_specs = (
        ("S_FA_ROE", True),
        ("S_FA_ROIC", True),
        ("S_FA_OCFTOOR", True),
        ("S_FA_DEBTTOASSETS", False),
    )
    component_scores = [
        _cross_section_score(
            market_data.get_panel("financial_indicators", field).astype("float64"),
            higher_is_better,
        )
        for field, higher_is_better in component_specs
    ]
    available_count = sum(score.notna().astype("int8") for score in component_scores)
    score_sum = sum(score.fillna(0.0) for score in component_scores)
    values = (score_sum / available_count.where(available_count > 0)).where(available_count >= 3)
    return QualityBasePanel(values, "daily")


def _calculate_pb_roe_composite(market_data: MarketData) -> QualityBasePanel:
    """等权合成高 ROE 与低 PB 的截面百分位分数。"""
    roe = market_data.get_panel("financial_indicators", "S_FA_ROE").astype("float64")
    pb = market_data.get_panel("stock_valuation", "S_VAL_PB_NEW").astype("float64")
    values = (
        _cross_section_score(roe, higher_is_better=True)
        + _cross_section_score(pb, higher_is_better=False)
    ) / 2.0
    return QualityBasePanel(values.where(roe.notna() & pb.notna()), "daily")
