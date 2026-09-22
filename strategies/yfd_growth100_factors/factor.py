"""按国证成长100公开编制思路构造易方达复现策略的综合成长信号。"""

from __future__ import annotations

import numpy as np
import pandas as pd
from pandas.api.indexers import VariableOffsetWindowIndexer

from src.data.market_data import MarketData
from src.factors.base import Factor

LOOKBACK_MONTHS = 6
# S_VAL_MV 的单位是万元，50 亿元对应 500,000 万元。
MINIMUM_MARKET_VALUE = 500_000


class CniGrowth100Factor(Factor):
    """计算资格过滤后的 G1 至 G4 综合排名信号。"""

    def calc(self, market_data: MarketData) -> pd.DataFrame:
        membership = market_data.membership.astype(bool)
        amount = market_data.get_panel("stock_quote", "S_DQ_AMOUNT")
        market_value = market_data.get_panel("stock_valuation", "S_VAL_MV")
        listing_dates = market_data.get_panel("stock_basic", "LISTDATE")
        net_profit = market_data.get_panel(
            "financial_income",
            "NET_PROFIT_EXCL_MIN_INT_INC",
        )
        report_periods = market_data.get_panel(
            "financial_indicators",
            "REPORT_PERIOD",
        )
        quarterly_roe = market_data.get_panel(
            "financial_indicators",
            "S_QFA_ROE",
        )
        gross_margin = market_data.get_panel(
            "financial_indicators",
            "S_QFA_GROSSPROFITMARGIN",
        )
        profit_growth = market_data.get_panel(
            "financial_indicators",
            "S_QFA_YOYNETPROFIT",
        )

        listed_long_enough = _listed_long_enough(listing_dates)
        amount_mean = _six_calendar_month_mean(amount)
        market_value_mean = _six_calendar_month_mean(market_value)
        liquid_universe = amount_mean.where(
            membership & listed_long_enough
        ).rank(axis=1, pct=True).gt(0.2)
        first_stage = (
            membership
            & listed_long_enough
            & liquid_universe
            & market_value_mean.ge(MINIMUM_MARKET_VALUE)
            & net_profit.gt(0)
        )

        previous_roe = _map_quarterly_statistic(
            _quarterly_values(quarterly_roe, report_periods).shift(1),
            report_periods,
        )
        roe_change = (quarterly_roe - previous_roe).div(previous_roe.abs())
        previous_margin = _map_quarterly_statistic(
            _quarterly_values(gross_margin, report_periods).shift(1),
            report_periods,
        )
        margin_change = gross_margin - previous_margin
        roe_filter = roe_change.where(first_stage).rank(
            axis=1,
            pct=True,
        ).gt(0.2)
        margin_filter = margin_change.where(first_stage).rank(
            axis=1,
            pct=True,
        ).gt(0.2)
        eligible = first_stage & roe_filter & margin_filter

        quarterly_growth = _quarterly_values(
            profit_growth,
            report_periods,
        )
        prior_growth = quarterly_growth.shift(1)
        growth_history = prior_growth.rolling(8, min_periods=8)
        historical_growth_mean = _map_quarterly_statistic(
            growth_history.mean(),
            report_periods,
        )
        historical_growth_std = _map_quarterly_statistic(
            growth_history.std(ddof=1),
            report_periods,
        )
        # 当前季度直接使用当日 PIT 值，不能把季度末的修订值回填到首次公告日。
        g1 = (profit_growth - historical_growth_mean).div(
            historical_growth_std
        )
        g2 = market_data.get_panel(
            "consensus_suntime",
            "con_npgrate_13w",
            forecast_year_offset=0,
        )
        g3 = market_data.get_panel(
            "consensus_suntime",
            "con_npcgrate_2y",
            forecast_year_offset=0,
        )
        current_roe = market_data.get_panel(
            "consensus_suntime",
            "con_roe",
            forecast_year_offset=0,
        )
        next_roe = market_data.get_panel(
            "consensus_suntime",
            "con_roe",
            forecast_year_offset=1,
        )
        g4 = (next_roe - current_roe).div(current_roe.abs()) * 100

        component_ranks = [
            component.where(eligible).rank(axis=1, ascending=False)
            for component in [g1, g2, g3, g4]
        ]
        complete_components = np.logical_and.reduce(
            [component.notna().to_numpy() for component in component_ranks]
        )
        rank_sum = sum(component_ranks)
        return (-rank_sum).where(complete_components)


def _six_calendar_month_mean(daily_values: pd.DataFrame) -> pd.DataFrame:
    """按包含首尾边界的六个自然月区间计算日均值。"""
    window = VariableOffsetWindowIndexer(
        index=daily_values.index,
        offset=pd.DateOffset(months=LOOKBACK_MONTHS),
    )
    return daily_values.rolling(
        window=window,
        min_periods=1,
        closed="both",
    ).mean()


def _listed_long_enough(listing_dates: pd.DataFrame) -> pd.DataFrame:
    """按科创板、北交所一年和其他市场半年实施上市时长过滤。"""
    stock_codes = listing_dates.columns.astype(str)
    one_year_required = np.array(
        [
            code.endswith(".BJ")
            or code.startswith("688")
            or code.startswith("689")
            for code in stock_codes
        ]
    )
    required_days = np.where(one_year_required, 365, 183)
    listing_values = listing_dates.to_numpy(dtype="datetime64[ns]")
    evaluation_dates = listing_dates.index.to_numpy(dtype="datetime64[ns]")
    listing_age_days = (
        evaluation_dates[:, None] - listing_values
    ).astype("timedelta64[D]").astype(float)
    return pd.DataFrame(
        listing_age_days > required_days[None, :],
        index=listing_dates.index,
        columns=listing_dates.columns,
    )


def _quarterly_values(
    daily_values: pd.DataFrame,
    report_periods: pd.DataFrame,
) -> pd.DataFrame:
    """从日频 PIT 状态提取每个报告季度最后一次已知值。"""
    state_changed = report_periods.notna() & (
        report_periods.ne(report_periods.shift())
        | daily_values.ne(daily_values.shift())
    )
    date_positions, stock_positions = np.nonzero(state_changed.to_numpy())
    event_records = pd.DataFrame(
        {
            "quarter": pd.DatetimeIndex(
                report_periods.to_numpy(dtype="datetime64[ns]")[
                    date_positions,
                    stock_positions,
                ]
            ).to_period("Q"),
            "stock_code": daily_values.columns.take(stock_positions),
            "value": daily_values.to_numpy(dtype=float)[
                date_positions,
                stock_positions,
            ],
        }
    ).drop_duplicates(["quarter", "stock_code"], keep="last")
    quarter_index = pd.period_range(
        event_records["quarter"].min(),
        event_records["quarter"].max(),
        freq="Q",
        name="quarter",
    )
    return event_records.pivot(
        index="quarter",
        columns="stock_code",
        values="value",
    ).reindex(index=quarter_index, columns=daily_values.columns)


def _map_quarterly_statistic(
    quarterly_values: pd.DataFrame,
    report_periods: pd.DataFrame,
) -> pd.DataFrame:
    """按照每日当前报告期把季度统计量映射回股票日频面板。"""
    report_months = report_periods.to_numpy(dtype="datetime64[M]")
    valid_periods = ~np.isnat(report_months)
    quarter_positions = (
        np.floor_divide(report_months.astype("int64"), 3)
        - quarterly_values.index[0].ordinal
    )
    safe_positions = np.where(valid_periods, quarter_positions, 0)
    stock_positions = np.arange(report_periods.shape[1])
    daily_values = quarterly_values.to_numpy(dtype=float)[
        safe_positions,
        stock_positions,
    ]
    daily_values[~valid_periods] = np.nan
    return pd.DataFrame(
        daily_values,
        index=report_periods.index,
        columns=report_periods.columns,
    )
