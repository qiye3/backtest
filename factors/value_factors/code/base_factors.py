"""从估值、行情、一致预期和财务指标构造价值基础因子。"""

from __future__ import annotations

import numpy as np
import pandas as pd

from factors.fundamental_utils import safe_divide
from factors.value_factors.code.utils import ValueBasePanel
from src.data.market_data import MarketData
from src.factors.utils import neutralize_factor_values

MARKET_VALUE_UNIT_TO_CURRENCY = 10_000.0

RECIPROCAL_VALUATION_FIELDS = {
    "ep": "S_VAL_PE_TTM",
    "ep_static": "S_VAL_PE",
    "bp": "S_VAL_PB_NEW",
    "sp": "S_VAL_PS_TTM",
    "pcf": "S_VAL_PCF_OCFTTM",
    "dividend_yield": "S_PRICE_DIV_DPS",
}


def calculate_base_factor(
    base_factor_name: str,
    market_data: MarketData,
) -> ValueBasePanel:
    """根据固定名称分派传统估值、改进估值和复合公式。"""
    if base_factor_name in RECIPROCAL_VALUATION_FIELDS:
        valuation_multiple = _valuation_field(
            market_data,
            RECIPROCAL_VALUATION_FIELDS[base_factor_name],
        )
        return ValueBasePanel(_reciprocal(valuation_multiple))
    if base_factor_name == "pe_multiple":
        pe_multiple = _valuation_field(market_data, "S_VAL_PE_TTM")
        return ValueBasePanel(pe_multiple.where(pe_multiple > 0))
    if base_factor_name == "peg":
        peg = market_data.get_panel("consensus_suntime", "con_peg").astype("float64")
        return ValueBasePanel(peg.where(peg > 0))

    calculators = {
        "ebit_ev": _calculate_ebit_ev,
        "ev_ebitda": _calculate_ev_ebitda,
        "fcf_yield": _calculate_fcf_yield,
        "net_cash_to_mv": _calculate_net_cash_to_mv,
        "ev_ocf": _calculate_ev_ocf,
        "valuation_composite": _calculate_valuation_composite,
        "low_volatility": _calculate_low_volatility,
        "pb_roe_group": _calculate_pb_roe_group,
        "pb_roe_regression": _calculate_pb_roe_regression,
        "irrational_valuation_premium": _calculate_irrational_valuation_premium,
        "consensus_valuation": _calculate_consensus_valuation,
        "expected_pe_change": _calculate_expected_pe_change,
        "value_quality_composite": _calculate_value_quality_composite,
        "dividend_low_vol_composite": _calculate_dividend_low_vol_composite,
        "dividend_quality_composite": _calculate_dividend_quality_composite,
        "value_trap_filter": _calculate_value_trap_filter,
        "low_valuation_option": _calculate_low_valuation_option,
    }
    calculator = calculators.get(base_factor_name)
    if calculator is None:
        raise ValueError(f"未知价值基础因子: {base_factor_name}")
    return calculator(market_data)


def _valuation_field(market_data: MarketData, field_name: str) -> pd.DataFrame:
    """读取一个日频 Wind 估值字段。"""
    return market_data.get_panel("stock_valuation", field_name).astype("float64")


def _indicator_field(market_data: MarketData, field_name: str) -> pd.DataFrame:
    """读取一个按公告日生效的财务指标字段。"""
    return market_data.get_panel("financial_indicators", field_name).astype("float64")


def _reciprocal(valuation_multiple: pd.DataFrame) -> pd.DataFrame:
    """对有限且非零的估值倍数取倒数。"""
    unit_panel = pd.DataFrame(
        1.0,
        index=valuation_multiple.index,
        columns=valuation_multiple.columns,
    )
    return safe_divide(unit_panel, valuation_multiple)


def _enterprise_value(market_data: MarketData) -> pd.DataFrame:
    """把万元总市值转换为元后加上最新已公告净债务。"""
    market_value = _valuation_field(market_data, "S_VAL_MV")
    net_debt = _indicator_field(market_data, "S_FA_NETDEBT")
    return market_value * MARKET_VALUE_UNIT_TO_CURRENCY + net_debt


def _calculate_ebit_ev(market_data: MarketData) -> ValueBasePanel:
    """计算息税前利润相对企业价值的收益率。"""
    ebit = _indicator_field(market_data, "S_FA_EBIT")
    return ValueBasePanel(safe_divide(ebit, _enterprise_value(market_data)))


def _calculate_ev_ebitda(market_data: MarketData) -> ValueBasePanel:
    """按构造表取 EV/EBITDA 的倒数，使值越高代表越便宜。"""
    ebitda = _indicator_field(market_data, "S_FA_EBITDA")
    return ValueBasePanel(safe_divide(ebitda, _enterprise_value(market_data)))


def _calculate_fcf_yield(market_data: MarketData) -> ValueBasePanel:
    """计算企业自由现金流相对企业价值的收益率。"""
    fcff = _indicator_field(market_data, "S_FA_FCFF")
    return ValueBasePanel(safe_divide(fcff, _enterprise_value(market_data)))


def _calculate_net_cash_to_mv(market_data: MarketData) -> ValueBasePanel:
    """用负净债务近似净现金并除以总市值。"""
    net_debt = _indicator_field(market_data, "S_FA_NETDEBT")
    market_value = _valuation_field(market_data, "S_VAL_MV")
    return ValueBasePanel(safe_divide(-net_debt, market_value * MARKET_VALUE_UNIT_TO_CURRENCY))


def _calculate_ev_ocf(market_data: MarketData) -> ValueBasePanel:
    """按构造表取 EV/经营现金流的倒数。"""
    operating_cashflow = _valuation_field(
        market_data,
        "NET_CASH_FLOWS_OPER_ACT_TTM",
    )
    return ValueBasePanel(safe_divide(operating_cashflow, _enterprise_value(market_data)))


def _cross_section_score(
    factor_values: pd.DataFrame,
    higher_is_better: bool,
) -> pd.DataFrame:
    """把异量纲值转换成每日截面百分位得分。"""
    percentile_scores = factor_values.rank(axis=1, pct=True)
    if higher_is_better:
        return percentile_scores
    return 1.0 - percentile_scores


def _mean_available_scores(
    component_scores: list[pd.DataFrame],
    minimum_components: int,
) -> pd.DataFrame:
    """按每日可用分量等权合成，并要求达到最低覆盖数。"""
    available_count = sum(
        component_score.notna().astype("int8") for component_score in component_scores
    )
    score_sum = sum(component_score.fillna(0.0) for component_score in component_scores)
    composite = score_sum / available_count.where(available_count > 0)
    return composite.where(available_count >= minimum_components)


def _calculate_valuation_composite(market_data: MarketData) -> ValueBasePanel:
    """等权合成 EP、BP、PCF 和股息率的截面得分。"""
    component_names = ("ep", "bp", "pcf", "dividend_yield")
    component_scores = [
        _cross_section_score(
            calculate_base_factor(component_name, market_data).values,
            higher_is_better=True,
        )
        for component_name in component_names
    ]
    return ValueBasePanel(_mean_available_scores(component_scores, minimum_components=3))


def _calculate_low_volatility(market_data: MarketData) -> ValueBasePanel:
    """计算复权收盘日收益率过去 240 个交易日的年化波动率。"""
    adjusted_close = market_data.get_panel(
        "stock_quote",
        "S_DQ_ADJCLOSE",
    ).astype("float64")
    daily_returns = adjusted_close.pct_change(fill_method=None)
    annualized_volatility = daily_returns.rolling(
        window=240,
        min_periods=120,
    ).std(ddof=1) * np.sqrt(252.0)
    return ValueBasePanel(annualized_volatility)


def _calculate_pb_roe_group(market_data: MarketData) -> ValueBasePanel:
    """只在 ROE 高于当日中位数的质量组内保留 BP。"""
    bp = calculate_base_factor("bp", market_data).values
    roe = _indicator_field(market_data, "S_FA_ROE")
    high_quality = roe.ge(roe.median(axis=1), axis=0)
    return ValueBasePanel(bp.where(high_quality))


def _calculate_pb_roe_regression(market_data: MarketData) -> ValueBasePanel:
    """返回 log(PB) 对 ROE 截面回归残差的相反数。"""
    pb = _valuation_field(market_data, "S_VAL_PB_NEW")
    log_pb = np.log(pb.where(pb > 0))
    roe = _indicator_field(market_data, "S_FA_ROE")
    residual = neutralize_factor_values(log_pb, [roe])
    return ValueBasePanel(-residual)


def _calculate_irrational_valuation_premium(
    market_data: MarketData,
) -> ValueBasePanel:
    """返回基本面和规模无法解释的 log(PE) 溢价的相反数。"""
    pe = _valuation_field(market_data, "S_VAL_PE_TTM")
    log_pe = np.log(pe.where(pe > 0))
    roe = _indicator_field(market_data, "S_FA_ROE")
    net_margin = _indicator_field(market_data, "S_FA_NETPROFITMARGIN")
    debt_ratio = _indicator_field(market_data, "S_FA_DEBTTOASSETS")
    market_value = _valuation_field(market_data, "S_VAL_MV")
    log_market_value = np.log(market_value.where(market_value > 0))
    residual = neutralize_factor_values(
        log_pe,
        [roe, net_margin, debt_ratio, log_market_value],
    )
    return ValueBasePanel(-residual)


def _calculate_consensus_valuation(market_data: MarketData) -> ValueBasePanel:
    """等权合成一致预期 PE、PB 和 PS 倒数的截面得分。"""
    consensus_fields = ("con_pe", "con_pb", "con_ps")
    component_scores = []
    for field_name in consensus_fields:
        multiple = market_data.get_panel(
            "consensus_suntime",
            field_name,
        ).astype("float64")
        component_scores.append(_cross_section_score(_reciprocal(multiple), higher_is_better=True))
    return ValueBasePanel(_mean_available_scores(component_scores, minimum_components=2))


def _calculate_expected_pe_change(market_data: MarketData) -> ValueBasePanel:
    """计算 13 周一致预期 PE 的下降幅度，下降越多取值越高。"""
    consensus_pe = market_data.get_panel(
        "consensus_suntime",
        "con_pe",
    ).astype("float64")
    prior_consensus_pe = consensus_pe.shift(65)
    return ValueBasePanel(safe_divide(prior_consensus_pe - consensus_pe, prior_consensus_pe.abs()))


def _calculate_value_quality_composite(market_data: MarketData) -> ValueBasePanel:
    """等权合成 EP、BP、ROE 和经营现金流质量。"""
    components = (
        (calculate_base_factor("ep", market_data).values, True),
        (calculate_base_factor("bp", market_data).values, True),
        (_indicator_field(market_data, "S_FA_ROE"), True),
        (_indicator_field(market_data, "S_FA_OCFTOPROFIT"), True),
    )
    component_scores = [
        _cross_section_score(component, higher_is_better)
        for component, higher_is_better in components
    ]
    return ValueBasePanel(_mean_available_scores(component_scores, minimum_components=3))


def _calculate_dividend_low_vol_composite(
    market_data: MarketData,
) -> ValueBasePanel:
    """等权合成股息率、低波动和 ROE。"""
    dividend_yield = calculate_base_factor("dividend_yield", market_data).values
    volatility = _calculate_low_volatility(market_data).values
    roe = _indicator_field(market_data, "S_FA_ROE")
    component_scores = [
        _cross_section_score(dividend_yield, higher_is_better=True),
        _cross_section_score(volatility, higher_is_better=False),
        _cross_section_score(roe, higher_is_better=True),
    ]
    return ValueBasePanel(_mean_available_scores(component_scores, minimum_components=3))


def _calculate_dividend_quality_composite(
    market_data: MarketData,
) -> ValueBasePanel:
    """等权合成股息率、扣非 ROE 和经营现金流质量。"""
    dividend_yield = calculate_base_factor("dividend_yield", market_data).values
    deducted_roe = _indicator_field(market_data, "S_FA_ROE_DEDUCTED")
    cash_realization = _indicator_field(market_data, "S_FA_OCFTOPROFIT")
    component_scores = [
        _cross_section_score(component, higher_is_better=True)
        for component in (dividend_yield, deducted_roe, cash_realization)
    ]
    return ValueBasePanel(_mean_available_scores(component_scores, minimum_components=3))


def _calculate_value_trap_filter(market_data: MarketData) -> ValueBasePanel:
    """以盈利改善、现金质量和低杠杆约束传统估值得分。"""
    valuation_score = _calculate_valuation_composite(market_data).values
    roe_change = _indicator_field(market_data, "S_FA_YOYROE")
    cash_realization = _indicator_field(market_data, "S_FA_OCFTOPROFIT")
    debt_ratio = _indicator_field(market_data, "S_FA_DEBTTOASSETS")
    quality_scores = [
        _cross_section_score(roe_change, higher_is_better=True),
        _cross_section_score(cash_realization, higher_is_better=True),
        _cross_section_score(debt_ratio, higher_is_better=False),
    ]
    quality_score = _mean_available_scores(quality_scores, minimum_components=2)
    return ValueBasePanel((valuation_score + quality_score) / 2.0)


def _calculate_low_valuation_option(market_data: MarketData) -> ValueBasePanel:
    """识别低 PE 历史分位且研发强度高于当日中位数的股票。"""
    raw_pe = _valuation_field(market_data, "S_VAL_PE_TTM")
    pe = raw_pe.where(raw_pe > 0)
    pe_percentile = pe.rolling(window=1200, min_periods=600).rank(pct=True)
    research_expense = market_data.get_panel(
        "financial_income",
        "RD_EXPENSE",
    ).astype("float64")
    revenue = market_data.get_panel(
        "financial_income",
        "TOT_OPER_REV",
    ).astype("float64")
    research_intensity = safe_divide(research_expense, revenue)
    high_research_intensity = research_intensity.ge(
        research_intensity.median(axis=1),
        axis=0,
    )
    option_signal = (pe_percentile <= 0.3) & high_research_intensity
    return ValueBasePanel(option_signal.astype("float64").where(pe_percentile.notna()))
