"""把成长100综合信号转换为易方达复现策略的目标权重。"""

from __future__ import annotations

import pandas as pd

from src.data.market_data import MarketData
from src.strategy.base import PortfolioRule


class CniGrowth100Portfolio(PortfolioRule):
    """执行 Top100、换样限制、排名倾斜和单票上限。"""

    def build_target_weights(
        self,
        signal_panel: pd.DataFrame,
        market_data: MarketData,
        rebalance_dates: pd.DatetimeIndex,
    ) -> pd.DataFrame:
        params = self.config["params"]
        top_n = int(params["top_n"])
        max_replacements = int(params["max_replacements"])
        tilt_strength = float(params["tilt_strength"])
        max_weight = float(params["max_weight"])
        signals = signal_panel.reindex(
            index=rebalance_dates,
            columns=market_data.membership.columns,
        )
        free_shares = market_data.get_panel(
            "stock_valuation",
            "FREE_SHARES_TODAY",
        ).reindex(index=rebalance_dates, columns=signals.columns)
        close_prices = market_data.get_panel(
            "stock_quote",
            "S_DQ_CLOSE",
        ).reindex(index=rebalance_dates, columns=signals.columns)
        free_float_market_value = free_shares * close_prices

        target_rows = []
        previous_members = pd.Index([], dtype=object)
        for rebalance_date in rebalance_dates:
            valid_market_values = free_float_market_value.loc[rebalance_date].gt(0)
            current_signals = signals.loc[rebalance_date].where(
                valid_market_values
            ).dropna()
            if len(current_signals) < top_n:
                raise ValueError(
                    f"{rebalance_date.date()} 成长100可选股票不足 {top_n} 只"
                )
            natural_members = current_signals.nlargest(top_n).index
            selected_members = _limit_replacements(
                current_signals=current_signals,
                natural_members=natural_members,
                previous_members=previous_members,
                top_n=top_n,
                max_replacements=max_replacements,
            )
            raw_weights = _growth_tilted_market_value(
                selected_signals=current_signals.loc[selected_members],
                selected_market_values=free_float_market_value.loc[
                    rebalance_date,
                    selected_members,
                ],
                tilt_strength=tilt_strength,
            )
            capped_weights = _cap_and_redistribute(raw_weights, max_weight)
            target_row = pd.Series(0.0, index=signals.columns)
            target_row.loc[selected_members] = capped_weights
            target_rows.append(target_row)
            previous_members = selected_members

        return pd.DataFrame(target_rows, index=rebalance_dates)


def _limit_replacements(
    current_signals: pd.Series,
    natural_members: pd.Index,
    previous_members: pd.Index,
    top_n: int,
    max_replacements: int,
) -> pd.Index:
    """限制排名变化造成的换入数量，硬性失效股票不继续保留。"""
    if previous_members.empty:
        return natural_members
    eligible_previous = previous_members.intersection(current_signals.index)
    new_members = natural_members.difference(eligible_previous)
    forced_replacements = top_n - len(eligible_previous)
    admitted_new_limit = forced_replacements + max_replacements
    if len(new_members) <= admitted_new_limit:
        return natural_members

    admitted_new = current_signals.loc[new_members].nlargest(
        admitted_new_limit
    ).index
    retained_count = top_n - len(admitted_new)
    retained_previous = current_signals.loc[eligible_previous].nlargest(
        retained_count
    ).index
    selected = retained_previous.append(admitted_new)
    return current_signals.loc[selected].sort_values(ascending=False).index


def _growth_tilted_market_value(
    selected_signals: pd.Series,
    selected_market_values: pd.Series,
    tilt_strength: float,
) -> pd.Series:
    """按自由流通市值乘以透明的综合排名倾斜代理构造原始权重。"""
    rank_percentiles = selected_signals.rank(pct=True)
    tilt = 1 + tilt_strength * rank_percentiles
    return selected_market_values * tilt


def _cap_and_redistribute(
    raw_weights: pd.Series,
    max_weight: float,
) -> pd.Series:
    """迭代固定超限股票，并把剩余权重按原始比例重新分配。"""
    remaining_raw = raw_weights.astype(float).copy()
    final_weights = pd.Series(0.0, index=raw_weights.index)
    remaining_weight = 1.0
    while not remaining_raw.empty:
        normalized = remaining_raw / remaining_raw.sum() * remaining_weight
        capped_members = normalized[normalized > max_weight].index
        if capped_members.empty:
            final_weights.loc[normalized.index] = normalized
            break
        final_weights.loc[capped_members] = max_weight
        remaining_raw = remaining_raw.drop(capped_members)
        remaining_weight = 1 - final_weights.sum()
    return final_weights
