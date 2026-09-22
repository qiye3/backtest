"""把路演指数信号转换成调仓日目标权重。"""

from __future__ import annotations

import warnings

import numpy as np
import pandas as pd

from src.data.market_data import MarketData
from src.strategy.base import PortfolioRule


class ScoreTiltedFreeFloatPortfolio(PortfolioRule):
    """按排名倾斜自由流通市值，并施加个股和行业上限。"""

    def build_target_weights(
        self,
        signal_panel: pd.DataFrame,
        market_data: MarketData,
        rebalance_dates: pd.DatetimeIndex,
    ) -> pd.DataFrame:
        targets, self.selection_diagnostics = _build_ranked_portfolio(
            self.config,
            signal_panel,
            market_data,
            rebalance_dates,
            weight_mode="free_float_tilt",
        )
        return targets


class MarketValuePortfolio(PortfolioRule):
    """按总市值加权并施加个股上限。"""

    def build_target_weights(
        self,
        signal_panel: pd.DataFrame,
        market_data: MarketData,
        rebalance_dates: pd.DatetimeIndex,
    ) -> pd.DataFrame:
        targets, self.selection_diagnostics = _build_ranked_portfolio(
            self.config,
            signal_panel,
            market_data,
            rebalance_dates,
            weight_mode="market_value",
        )
        return targets


class DividendVolatilityPortfolio(PortfolioRule):
    """按股息率除以一年波动率加权，并施加行业上限。"""

    def build_target_weights(
        self,
        signal_panel: pd.DataFrame,
        market_data: MarketData,
        rebalance_dates: pd.DatetimeIndex,
    ) -> pd.DataFrame:
        targets, self.selection_diagnostics = _build_ranked_portfolio(
            self.config,
            signal_panel,
            market_data,
            rebalance_dates,
            weight_mode="dividend_volatility",
        )
        return targets


class FreeCashFlowPortfolio(PortfolioRule):
    """按正自由现金流加权并施加单票上限。"""

    def build_target_weights(
        self,
        signal_panel: pd.DataFrame,
        market_data: MarketData,
        rebalance_dates: pd.DatetimeIndex,
    ) -> pd.DataFrame:
        targets, self.selection_diagnostics = _build_ranked_portfolio(
            self.config,
            signal_panel,
            market_data,
            rebalance_dates,
            weight_mode="free_cashflow",
        )
        return targets


def _build_ranked_portfolio(
    config: dict,
    signal_panel: pd.DataFrame,
    market_data: MarketData,
    rebalance_dates: pd.DatetimeIndex,
    weight_mode: str,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    params = config["params"]
    top_n = int(params["top_n"])
    insufficient_policy = params.get("insufficient_candidates_policy", "error")
    allowed_policies = {
        "error",
        "warn_and_use_all",
        "warn_and_reduce_top_n",
        "skip_date",
    }
    if insufficient_policy not in allowed_policies:
        raise ValueError(f"insufficient_candidates_policy 必须是 {sorted(allowed_policies)} 之一")
    max_replacements = params.get("max_replacements")
    signals = signal_panel.reindex(
        index=rebalance_dates,
        columns=market_data.membership.columns,
    )
    raw_weight_panel = _raw_weight_panel(
        weight_mode,
        signals,
        market_data,
        rebalance_dates,
        float(params.get("tilt_strength", 1.0)),
    )
    industry_panel = _industry_panel(
        config,
        market_data,
        rebalance_dates,
        signals.columns,
    )

    previous_members = pd.Index([], dtype=object)
    target_rows = []
    target_dates = []
    diagnostic_rows = []
    for rebalance_date in rebalance_dates:
        valid_raw_weights = raw_weight_panel.loc[rebalance_date].gt(0)
        current_signals = signals.loc[rebalance_date].where(valid_raw_weights).dropna()
        candidate_count = len(current_signals)
        status = "complete"
        if candidate_count < top_n and insufficient_policy == "error":
            raise ValueError(
                f"{rebalance_date.date()} {config['name']} "
                f"可选股票仅 {candidate_count} 只，不足 {top_n} 只"
            )
        if candidate_count < top_n and insufficient_policy == "skip_date":
            diagnostic_rows.append(
                _selection_diagnostic_row(
                    rebalance_date,
                    candidate_count,
                    top_n,
                    selected_count=0,
                    status="skipped",
                )
            )
            continue
        effective_top_n = min(top_n, candidate_count)
        if candidate_count < top_n:
            status = insufficient_policy
            warnings.warn(
                f"{rebalance_date.date()} {config['name']} 可选股票仅 "
                f"{candidate_count} 只，实际选取 {effective_top_n} 只",
                stacklevel=2,
            )
        natural_members = current_signals.nlargest(effective_top_n).index
        selected_members = _limit_replacements(
            current_signals,
            natural_members,
            previous_members,
            effective_top_n,
            None if max_replacements is None else int(max_replacements),
        )
        raw_weights = raw_weight_panel.loc[rebalance_date, selected_members]
        industries = None
        if industry_panel is not None:
            industries = industry_panel.loc[rebalance_date, selected_members]
        final_weights = _cap_and_redistribute(
            raw_weights,
            params.get("max_weight"),
            industries,
            params.get("max_industry_weight"),
        )
        target_row = pd.Series(0.0, index=signals.columns)
        target_row.loc[selected_members] = final_weights
        target_rows.append(target_row)
        target_dates.append(rebalance_date)
        diagnostic_rows.append(
            _selection_diagnostic_row(
                rebalance_date,
                candidate_count,
                top_n,
                selected_count=len(selected_members),
                status=status,
            )
        )
        previous_members = selected_members
    targets = pd.DataFrame(
        target_rows,
        index=pd.DatetimeIndex(target_dates, name="date"),
    )
    return targets, pd.DataFrame(diagnostic_rows)


def _selection_diagnostic_row(
    rebalance_date: pd.Timestamp,
    candidate_count: int,
    requested_top_n: int,
    selected_count: int,
    status: str,
) -> dict[str, object]:
    """记录一个调仓日的候选池、实际选样数和降级状态。"""
    return {
        "date": rebalance_date,
        "candidate_count": candidate_count,
        "requested_top_n": requested_top_n,
        "selected_count": selected_count,
        "status": status,
    }


def _raw_weight_panel(
    weight_mode: str,
    signals: pd.DataFrame,
    market_data: MarketData,
    rebalance_dates: pd.DatetimeIndex,
    tilt_strength: float,
) -> pd.DataFrame:
    if weight_mode == "market_value":
        return market_data.get_panel("stock_valuation", "S_VAL_MV").reindex(
            index=rebalance_dates, columns=signals.columns
        )
    if weight_mode == "free_cashflow":
        return market_data.get_panel("financial_indicators", "S_FA_FCFF").reindex(
            index=rebalance_dates, columns=signals.columns
        )
    if weight_mode == "dividend_volatility":
        price_to_dividend = market_data.get_panel("stock_valuation", "S_PRICE_DIV_DPS").reindex(
            index=rebalance_dates, columns=signals.columns
        )
        adjusted_close = market_data.get_panel("stock_quote", "S_DQ_ADJCLOSE")
        volatility = (
            adjusted_close.pct_change(fill_method=None)
            .rolling(240, min_periods=120)
            .std(ddof=1)
            .reindex(index=rebalance_dates, columns=signals.columns)
        )
        dividend_yield = _safe_divide(
            _ones_like(price_to_dividend),
            price_to_dividend,
        )
        return _safe_divide(dividend_yield, volatility)

    free_shares = market_data.get_panel("stock_valuation", "FREE_SHARES_TODAY").reindex(
        index=rebalance_dates, columns=signals.columns
    )
    close_prices = market_data.get_panel("stock_quote", "S_DQ_CLOSE").reindex(
        index=rebalance_dates, columns=signals.columns
    )
    rank_tilt = 1 + tilt_strength * signals.rank(axis=1, pct=True)
    return free_shares * close_prices * rank_tilt


def _industry_panel(
    config: dict,
    market_data: MarketData,
    rebalance_dates: pd.DatetimeIndex,
    stock_codes: pd.Index,
) -> pd.DataFrame | None:
    if config["params"].get("max_industry_weight") is None:
        return None
    return market_data.get_panel("industry_history", "ind_class_code").reindex(
        index=rebalance_dates,
        columns=stock_codes,
    )


def _limit_replacements(
    current_signals: pd.Series,
    natural_members: pd.Index,
    previous_members: pd.Index,
    top_n: int,
    max_replacements: int | None,
) -> pd.Index:
    if previous_members.empty or max_replacements is None:
        return natural_members
    eligible_previous = previous_members.intersection(current_signals.index)
    new_members = natural_members.difference(eligible_previous)
    admitted_limit = top_n - len(eligible_previous) + max_replacements
    if len(new_members) <= admitted_limit:
        return natural_members
    admitted_new = current_signals.loc[new_members].nlargest(admitted_limit).index
    retained_previous = (
        current_signals.loc[eligible_previous].nlargest(top_n - len(admitted_new)).index
    )
    return (
        current_signals.loc[retained_previous.append(admitted_new)]
        .sort_values(ascending=False)
        .index
    )


def _cap_and_redistribute(
    raw_weights: pd.Series,
    max_weight: float | None,
    industries: pd.Series | None,
    max_industry_weight: float | None,
) -> pd.Series:
    weights = raw_weights / raw_weights.sum()
    for _ in range(100):
        previous_weights = weights.copy()
        if max_weight is not None:
            weights = _redistribute_cap(weights, pd.Series(float(max_weight), index=weights.index))
        if industries is not None and max_industry_weight is not None:
            weights = _redistribute_industry_cap(
                weights,
                industries,
                float(max_industry_weight),
            )
        if np.allclose(weights, previous_weights, atol=1e-12):
            break
    return weights


def _redistribute_cap(weights: pd.Series, caps: pd.Series) -> pd.Series:
    capped = weights.clip(upper=caps)
    for _ in range(len(weights)):
        remaining = 1.0 - capped.sum()
        if remaining <= 1e-12:
            break
        available = capped < caps - 1e-12
        if not available.any():
            break
        additions = weights.loc[available] / weights.loc[available].sum() * remaining
        capped.loc[available] = (capped.loc[available] + additions).clip(upper=caps.loc[available])
    return capped / capped.sum()


def _redistribute_industry_cap(
    weights: pd.Series,
    industries: pd.Series,
    max_industry_weight: float,
) -> pd.Series:
    """压低超限行业，并只向尚未触及上限的行业重新分配。"""
    adjusted = weights.copy()
    for _ in range(len(weights)):
        industry_totals = adjusted.groupby(industries).sum()
        over_limit = industry_totals[industry_totals > max_industry_weight + 1e-12]
        if over_limit.empty:
            break
        for industry_code, industry_weight in over_limit.items():
            members = industries[industries == industry_code].index
            adjusted.loc[members] *= max_industry_weight / industry_weight
        remaining_weight = 1.0 - adjusted.sum()
        industry_totals = adjusted.groupby(industries).sum()
        available_industries = industry_totals[industry_totals < max_industry_weight - 1e-12].index
        available = industries.isin(available_industries)
        additions = adjusted.loc[available] / adjusted.loc[available].sum() * remaining_weight
        adjusted.loc[available] += additions
    return adjusted / adjusted.sum()


def _ones_like(values: pd.DataFrame) -> pd.DataFrame:
    return pd.DataFrame(1.0, index=values.index, columns=values.columns)


def _safe_divide(
    numerator: pd.DataFrame,
    denominator: pd.DataFrame,
) -> pd.DataFrame:
    """仅在分母有限且不接近零时计算比率。"""
    valid_denominator = denominator.where(
        np.isfinite(denominator) & denominator.abs().gt(1e-12)
    )
    return (numerator / valid_denominator).replace([np.inf, -np.inf], np.nan)
