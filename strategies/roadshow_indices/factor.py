"""把五份公开指数编制方案转换为可排序的日频选样信号。"""

from __future__ import annotations

import numpy as np
import pandas as pd
from pandas.api.indexers import VariableOffsetWindowIndexer

from factors.fundamental_utils import safe_divide
from src.data.market_data import MarketData
from src.factors.base import Factor
from src.factors.utils import neutralize_factor_values

MARKET_VALUE_UNIT_TO_CURRENCY = 10_000.0


class Csi500QualityGrowthFactor(Factor):
    """计算中证500质量成长的质量与成长综合得分。"""

    def calc(self, market_data: MarketData) -> pd.DataFrame:
        profit = market_data.get_panel(
            "financial_income", "NET_PROFIT_EXCL_MIN_INT_INC"
        ).astype("float64")
        roe = market_data.get_panel("financial_indicators", "S_FA_ROE").astype("float64")
        quarterly_roe = market_data.get_panel(
            "financial_indicators", "S_QFA_ROE"
        ).astype("float64")
        profit_growth = market_data.get_panel(
            "financial_indicators", "S_QFA_YOYNETPROFIT"
        ).astype("float64")
        report_periods = market_data.get_panel("financial_indicators", "REPORT_PERIOD")
        income_periods = market_data.get_panel("financial_income", "REPORT_PERIOD")
        quarterly_profit = _quarterly_values(profit, income_periods)
        three_year_profit_change = _map_quarterly(
            quarterly_profit - quarterly_profit.shift(12), income_periods
        )
        roe_history = _quarterly_values(quarterly_roe, report_periods).rolling(
            12, min_periods=12
        )
        roe_volatility = _map_quarterly(roe_history.std(ddof=1), report_periods)
        stable_earnings = roe_volatility.rank(axis=1, pct=True).le(0.8)
        eligible = (
            market_data.membership
            & profit.gt(0)
            & three_year_profit_change.ge(0)
            & stable_earnings
        )

        pb = market_data.get_panel("stock_valuation", "S_VAL_PB_NEW").astype("float64")
        profitability = neutralize_factor_values(roe, [np.log(pb.where(pb > 0))])
        growth_sue = _historical_zscore(profit_growth, report_periods, periods=8)
        roe_change = quarterly_roe - _map_quarterly(
            _quarterly_values(quarterly_roe, report_periods).shift(1), report_periods
        )
        growth = (_cross_section_zscore(growth_sue) + _cross_section_zscore(roe_change)) / 2

        operating_cashflow = market_data.get_panel(
            "financial_cashflow", "NET_CASH_FLOWS_OPER_ACT"
        ).astype("float64")
        operating_profit = market_data.get_panel(
            "financial_income", "OPER_PROFIT"
        ).astype("float64")
        assets = market_data.get_panel(
            "financial_balance_sheet", "TOT_ASSETS"
        ).astype("float64")
        liabilities = market_data.get_panel(
            "financial_balance_sheet", "TOT_LIAB"
        ).astype("float64")
        earnings_quality = safe_divide(operating_cashflow - operating_profit, assets)
        leverage_quality = safe_divide(operating_cashflow, liabilities)
        score = (
            0.30 * _cross_section_zscore(profitability)
            + 0.35 * _cross_section_zscore(growth)
            + 0.25 * _cross_section_zscore(earnings_quality)
            + 0.10 * _cross_section_zscore(leverage_quality)
        ) / np.sqrt(0.285)
        return score.where(eligible)


class CsiTechnologyTopFactor(Factor):
    """计算科技龙头的规模、成长和研发综合选样信号。"""

    def calc(self, market_data: MarketData) -> pd.DataFrame:
        market_value = market_data.get_panel("stock_valuation", "S_VAL_MV").astype("float64")
        pe = market_data.get_panel("stock_valuation", "S_VAL_PE_TTM").astype("float64")
        revenue = market_data.get_panel("financial_income", "TOT_OPER_REV").astype("float64")
        research_expense = market_data.get_panel(
            "financial_income", "RD_EXPENSE"
        ).astype("float64")
        revenue_growth = market_data.get_panel(
            "financial_indicators", "S_FA_YOY_OR"
        ).astype("float64")
        profit_growth = market_data.get_panel(
            "financial_indicators", "S_QFA_YOYNETPROFIT"
        ).astype("float64")
        report_periods = market_data.get_panel("financial_income", "REPORT_PERIOD")
        quarterly_research = _quarterly_values(research_expense, report_periods)
        research_growth = safe_divide(
            quarterly_research, quarterly_research.shift(12).abs()
        ) - 1
        research_growth = _map_quarterly(research_growth, report_periods)
        revenue_top_ten = revenue.rank(axis=1, pct=True).ge(0.9)
        positive_reasonable_pe = pe.gt(0) & pe.rank(axis=1, pct=True).le(0.9)
        stable = revenue_top_ten | (positive_reasonable_pe & research_growth.ge(0))

        scale_rank = (
            market_value.rank(axis=1, ascending=False)
            + revenue.rank(axis=1, ascending=False)
        ) / 2
        first_hundred = scale_rank.where(stable).rank(axis=1).le(100)
        growth_rank = (
            revenue_growth.rank(axis=1, ascending=False)
            + profit_growth.rank(axis=1, ascending=False)
        ) / 2
        research_intensity = safe_divide(research_expense, revenue)
        final_rank = (
            growth_rank.rank(axis=1) + research_intensity.rank(axis=1, ascending=False)
        ) / 2
        return (-final_rank).where(first_hundred & market_data.membership)


class CsiDividendLowVolatility100Factor(Factor):
    """先筛选高股息300只，再按一年低波动选择100只。"""

    def calc(self, market_data: MarketData) -> pd.DataFrame:
        amount = market_data.get_panel("stock_quote", "S_DQ_AMOUNT").astype("float64")
        adjusted_close = market_data.get_panel(
            "stock_quote", "S_DQ_ADJCLOSE"
        ).astype("float64")
        price_to_dividend = market_data.get_panel(
            "stock_valuation", "S_PRICE_DIV_DPS"
        ).astype("float64")
        liquid = _calendar_mean(amount, months=12).where(
            market_data.membership
        ).rank(axis=1, pct=True).gt(0.2)
        dividend_yield = safe_divide(pd.DataFrame(1.0, index=price_to_dividend.index,
                                                  columns=price_to_dividend.columns),
                                     price_to_dividend).where(price_to_dividend > 0)
        high_dividend = dividend_yield.where(liquid).rank(
            axis=1, ascending=False
        ).le(300)
        volatility = adjusted_close.pct_change(fill_method=None).rolling(
            240, min_periods=120
        ).std(ddof=1)
        return (-volatility.rank(axis=1)).where(high_dividend)


class CniValue100Factor(Factor):
    """计算资格过滤后的国证价值100综合价值得分。"""

    def calc(self, market_data: MarketData) -> pd.DataFrame:
        membership = market_data.membership
        amount = market_data.get_panel("stock_quote", "S_DQ_AMOUNT").astype("float64")
        market_value = market_data.get_panel("stock_valuation", "S_VAL_MV").astype("float64")
        profit = market_data.get_panel(
            "financial_income", "NET_PROFIT_EXCL_MIN_INT_INC"
        ).astype("float64")
        report_periods = market_data.get_panel("financial_indicators", "REPORT_PERIOD")
        roe = market_data.get_panel("financial_indicators", "S_FA_ROE").astype("float64")
        roe_history = _quarterly_values(roe, report_periods).rolling(12, min_periods=12)
        roe_mean = _map_quarterly(roe_history.mean(), report_periods)
        roe_std = _map_quarterly(roe_history.std(ddof=1), report_periods)
        fcf_yield = _free_cashflow_yield(market_data)
        eligible = (
            membership
            & _calendar_mean(amount, 6).where(membership).rank(axis=1, pct=True).gt(0.2)
            & _calendar_mean(market_value, 6).where(membership).rank(axis=1, pct=True).gt(0.2)
            & profit.gt(0)
            & roe_mean.rank(axis=1, pct=True).gt(0.2)
            & roe_std.rank(axis=1, pct=True).le(0.8)
            & fcf_yield.rank(axis=1, pct=True).gt(0.5)
        )
        pe = market_data.get_panel("stock_valuation", "S_VAL_PE_TTM").astype("float64")
        price_to_dividend = market_data.get_panel(
            "stock_valuation", "S_PRICE_DIV_DPS"
        ).astype("float64")
        components = [
            safe_divide(_ones_like(pe), pe).where(pe > 0),
            safe_divide(_ones_like(price_to_dividend), price_to_dividend).where(
                price_to_dividend > 0
            ),
            fcf_yield,
        ]
        return (sum(_cross_section_zscore(value) for value in components) / 3).where(eligible)


class CniFreeCashFlowFactor(Factor):
    """按自由现金流稳定性过滤并以自由现金流率排序。"""

    def calc(self, market_data: MarketData) -> pd.DataFrame:
        amount = market_data.get_panel("stock_quote", "S_DQ_AMOUNT").astype("float64")
        report_periods = market_data.get_panel("financial_indicators", "REPORT_PERIOD")
        roe = market_data.get_panel("financial_indicators", "S_FA_ROE").astype("float64")
        roe_std = _map_quarterly(
            _quarterly_values(roe, report_periods).rolling(12, min_periods=12).std(ddof=1),
            report_periods,
        )
        fcff = market_data.get_panel("financial_indicators", "S_FA_FCFF").astype("float64")
        net_debt = market_data.get_panel(
            "financial_indicators", "S_FA_NETDEBT"
        ).astype("float64")
        market_value = market_data.get_panel("stock_valuation", "S_VAL_MV").astype("float64")
        enterprise_value = market_value * MARKET_VALUE_UNIT_TO_CURRENCY + net_debt
        cash_quality = market_data.get_panel(
            "financial_indicators", "S_FA_OCFTOPROFIT"
        ).astype("float64")
        operating_cashflow = market_data.get_panel(
            "financial_cashflow", "NET_CASH_FLOWS_OPER_ACT"
        ).astype("float64")
        cashflow_periods = market_data.get_panel("financial_cashflow", "REPORT_PERIOD")
        quarterly_cashflow = _quarterly_values(operating_cashflow, cashflow_periods)
        three_year_positive = _map_quarterly(
            (quarterly_cashflow > 0).rolling(12, min_periods=12).sum().eq(12),
            cashflow_periods,
        ).astype(bool)
        membership = market_data.membership
        eligible = (
            membership
            & _calendar_mean(amount, 6).where(membership).rank(axis=1, pct=True).gt(0.2)
            & roe_std.rank(axis=1, pct=True).le(0.9)
            & fcff.gt(0)
            & enterprise_value.gt(0)
            & three_year_positive
            & cash_quality.rank(axis=1, pct=True).gt(0.3)
        )
        return safe_divide(fcff, enterprise_value).where(eligible)


def _free_cashflow_yield(market_data: MarketData) -> pd.DataFrame:
    fcff = market_data.get_panel("financial_indicators", "S_FA_FCFF").astype("float64")
    net_debt = market_data.get_panel("financial_indicators", "S_FA_NETDEBT").astype("float64")
    market_value = market_data.get_panel("stock_valuation", "S_VAL_MV").astype("float64")
    return safe_divide(fcff, market_value * MARKET_VALUE_UNIT_TO_CURRENCY + net_debt)


def _calendar_mean(values: pd.DataFrame, months: int) -> pd.DataFrame:
    window = VariableOffsetWindowIndexer(index=values.index, offset=pd.DateOffset(months=months))
    return values.rolling(window=window, min_periods=1, closed="both").mean()


def _ones_like(values: pd.DataFrame) -> pd.DataFrame:
    return pd.DataFrame(1.0, index=values.index, columns=values.columns)


def _cross_section_zscore(values: pd.DataFrame) -> pd.DataFrame:
    mean = values.mean(axis=1)
    standard_deviation = values.std(axis=1, ddof=1).replace(0, np.nan)
    return values.sub(mean, axis=0).div(standard_deviation, axis=0)


def _historical_zscore(
    daily_values: pd.DataFrame,
    report_periods: pd.DataFrame,
    periods: int,
) -> pd.DataFrame:
    quarterly = _quarterly_values(daily_values, report_periods)
    history = quarterly.shift(1).rolling(periods, min_periods=periods)
    mean = _map_quarterly(history.mean(), report_periods)
    standard_deviation = _map_quarterly(history.std(ddof=1), report_periods)
    return safe_divide(daily_values - mean, standard_deviation)


def _quarterly_values(
    daily_values: pd.DataFrame,
    report_periods: pd.DataFrame,
) -> pd.DataFrame:
    state_changed = report_periods.notna() & (
        report_periods.ne(report_periods.shift()) | daily_values.ne(daily_values.shift())
    )
    date_positions, stock_positions = np.nonzero(state_changed.to_numpy())
    records = pd.DataFrame(
        {
            "quarter": pd.DatetimeIndex(
                report_periods.to_numpy(dtype="datetime64[ns]")[date_positions, stock_positions]
            ).to_period("Q"),
            "stock_code": daily_values.columns.take(stock_positions),
            "value": daily_values.to_numpy(dtype=float)[date_positions, stock_positions],
        }
    ).drop_duplicates(["quarter", "stock_code"], keep="last")
    quarter_index = pd.period_range(records["quarter"].min(), records["quarter"].max(), freq="Q")
    return records.pivot(index="quarter", columns="stock_code", values="value").reindex(
        index=quarter_index,
        columns=daily_values.columns,
    )


def _map_quarterly(
    quarterly_values: pd.DataFrame,
    report_periods: pd.DataFrame,
) -> pd.DataFrame:
    report_months = report_periods.to_numpy(dtype="datetime64[M]")
    valid_periods = ~np.isnat(report_months)
    positions = (
        np.floor_divide(report_months.astype("int64"), 3)
        - quarterly_values.index[0].ordinal
    )
    safe_positions = np.where(valid_periods, positions, 0)
    stock_positions = np.arange(report_periods.shape[1])
    mapped = quarterly_values.to_numpy(dtype=float)[safe_positions, stock_positions]
    mapped[~valid_periods] = np.nan
    return pd.DataFrame(mapped, index=report_periods.index, columns=report_periods.columns)
