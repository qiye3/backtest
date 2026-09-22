"""从框架数据源构造质量基础因子。"""

from __future__ import annotations

import pandas as pd

from factors.quality_factors.code.utils import (
    QualityBasePanel,
    aligned_financial_ratio,
    apply_quarterly_operator,
    safe_divide,
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
    values = market_data.get_panel("financial_indicators", field_name).astype("float64")
    report_periods = market_data.get_panel("financial_indicators", "REPORT_PERIOD")
    return QualityBasePanel(values, "quarterly", report_periods)


def _financial_field(
    market_data: MarketData,
    source_name: str,
    field_name: str,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """读取一个财务字段及其公告时点对应的报告期。"""
    values = market_data.get_panel(source_name, field_name).astype("float64")
    report_periods = market_data.get_panel(source_name, "REPORT_PERIOD")
    return values, report_periods


def _calculate_ocf_to_net_profit(market_data: MarketData) -> QualityBasePanel:
    """计算经营现金流相对归母净利润的利润含金量。"""
    ocf, ocf_periods = _financial_field(
        market_data,
        "financial_cashflow",
        "NET_CASH_FLOWS_OPER_ACT",
    )
    profit, profit_periods = _financial_field(
        market_data,
        "financial_income",
        "NET_PROFIT_EXCL_MIN_INT_INC",
    )
    values, periods = aligned_financial_ratio(ocf, ocf_periods, profit, profit_periods)
    return QualityBasePanel(values, "quarterly", periods)


def _calculate_accruals_to_assets(market_data: MarketData) -> QualityBasePanel:
    """计算归母净利润减经营现金流后占总资产的比例。"""
    profit, income_periods = _financial_field(
        market_data,
        "financial_income",
        "NET_PROFIT_EXCL_MIN_INT_INC",
    )
    ocf, cashflow_periods = _financial_field(
        market_data,
        "financial_cashflow",
        "NET_CASH_FLOWS_OPER_ACT",
    )
    assets, balance_periods = _financial_field(
        market_data,
        "financial_balance_sheet",
        "TOT_ASSETS",
    )
    aligned = income_periods.eq(cashflow_periods) & income_periods.eq(balance_periods)
    periods = income_periods.where(aligned)
    values = safe_divide(profit - ocf, assets).where(aligned)
    return QualityBasePanel(values, "quarterly", periods)


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
    capex, periods = _financial_field(
        market_data,
        "financial_cashflow",
        "CASH_PAY_ACQ_CONST_FIOLTA",
    )
    ocf, _ = _financial_field(
        market_data,
        "financial_cashflow",
        "NET_CASH_FLOWS_OPER_ACT",
    )
    return QualityBasePanel(safe_divide(capex, ocf), "quarterly", periods)


def _calculate_interest_debt_to_ocf(market_data: MarketData) -> QualityBasePanel:
    """计算净债务相对经营现金流的覆盖压力。"""
    net_debt = market_data.get_panel(
        "financial_indicators",
        "S_FA_NETDEBT",
    ).astype("float64")
    indicator_periods = market_data.get_panel("financial_indicators", "REPORT_PERIOD")
    ocf, cashflow_periods = _financial_field(
        market_data,
        "financial_cashflow",
        "NET_CASH_FLOWS_OPER_ACT",
    )
    values, periods = aligned_financial_ratio(
        net_debt,
        indicator_periods,
        ocf,
        cashflow_periods,
    )
    return QualityBasePanel(values, "quarterly", periods)


def _calculate_receivables_to_revenue(market_data: MarketData) -> QualityBasePanel:
    """计算应收账款占营业总收入的比例。"""
    receivables, balance_periods = _financial_field(
        market_data,
        "financial_balance_sheet",
        "ACCOUNTS_RECEIVABLE",
    )
    revenue, income_periods = _financial_field(
        market_data,
        "financial_income",
        "TOT_OPER_REV",
    )
    values, periods = aligned_financial_ratio(
        receivables,
        balance_periods,
        revenue,
        income_periods,
    )
    return QualityBasePanel(values, "quarterly", periods)


def _calculate_inventory_change_to_assets(market_data: MarketData) -> QualityBasePanel:
    """计算存货较上一自然季度的增量占当前总资产比例。"""
    inventories, periods = _financial_field(
        market_data,
        "financial_balance_sheet",
        "INVENTORIES",
    )
    assets, _ = _financial_field(
        market_data,
        "financial_balance_sheet",
        "TOT_ASSETS",
    )
    inventory_change = apply_quarterly_operator(inventories, periods, "qoq")
    return QualityBasePanel(safe_divide(inventory_change, assets), "quarterly", periods)


def _calculate_goodwill_to_equity(market_data: MarketData) -> QualityBasePanel:
    """计算商誉占归母股东权益的比例。"""
    goodwill, periods = _financial_field(
        market_data,
        "financial_balance_sheet",
        "GOODWILL",
    )
    equity, _ = _financial_field(
        market_data,
        "financial_balance_sheet",
        "TOT_SHRHLDR_EQY_EXCL_MIN_INT",
    )
    return QualityBasePanel(safe_divide(goodwill, equity), "quarterly", periods)


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
