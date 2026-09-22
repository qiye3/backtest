"""计算策略相对基准的行业和风格暴露。"""

from __future__ import annotations

import numpy as np
import pandas as pd

from src.strategy.evaluation import align_weight_panels

UNKNOWN_INDUSTRY = "UNKNOWN"


def calculate_industry_exposure(
    target_weights: pd.DataFrame,
    benchmark_weights: pd.DataFrame,
    industry_panel: pd.DataFrame,
) -> pd.DataFrame:
    """按调仓日汇总策略、基准及主动行业权重。"""
    aligned_target, aligned_benchmark = align_weight_panels(
        target_weights,
        benchmark_weights,
    )
    aligned_industries = industry_panel.reindex(
        index=aligned_target.index,
        columns=aligned_target.columns,
    ).fillna(UNKNOWN_INDUSTRY)

    exposure_rows = []
    for rebalance_date in aligned_target.index:
        industry_codes = aligned_industries.loc[rebalance_date].astype(str)
        portfolio_weights = aligned_target.loc[rebalance_date].groupby(
            industry_codes
        ).sum()
        benchmark_industry_weights = aligned_benchmark.loc[
            rebalance_date
        ].groupby(industry_codes).sum()
        all_industries = portfolio_weights.index.union(
            benchmark_industry_weights.index
        )
        for industry_code in all_industries:
            portfolio_weight = float(portfolio_weights.get(industry_code, 0.0))
            benchmark_weight = float(
                benchmark_industry_weights.get(industry_code, 0.0)
            )
            exposure_rows.append(
                {
                    "date": rebalance_date,
                    "industry_code": industry_code,
                    "portfolio_weight": portfolio_weight,
                    "benchmark_weight": benchmark_weight,
                    "active_weight": portfolio_weight - benchmark_weight,
                }
            )
    return pd.DataFrame(exposure_rows)


def calculate_style_exposure(
    target_weights: pd.DataFrame,
    benchmark_weights: pd.DataFrame,
    style_exposures: pd.DataFrame,
    minimum_coverage: float = 0.95,
) -> pd.DataFrame:
    """按有效权重归一化计算策略、基准和主动风格暴露。"""
    aligned_target, aligned_benchmark = align_weight_panels(
        target_weights,
        benchmark_weights,
    )
    style_names = style_exposures.columns.get_level_values(
        "style_name"
    ).unique()
    exposure_rows = []
    for style_name in style_names:
        style_panel = style_exposures.xs(
            style_name,
            axis=1,
            level="style_name",
        ).reindex(index=aligned_target.index, columns=aligned_target.columns)
        for rebalance_date in aligned_target.index:
            style_values = style_panel.loc[rebalance_date]
            portfolio_exposure, portfolio_coverage = _weighted_exposure(
                aligned_target.loc[rebalance_date],
                style_values,
                minimum_coverage,
            )
            benchmark_exposure, benchmark_coverage = _weighted_exposure(
                aligned_benchmark.loc[rebalance_date],
                style_values,
                minimum_coverage,
            )
            active_exposure = (
                portfolio_exposure - benchmark_exposure
                if np.isfinite(portfolio_exposure)
                and np.isfinite(benchmark_exposure)
                else np.nan
            )
            exposure_rows.append(
                {
                    "date": rebalance_date,
                    "style_name": style_name,
                    "portfolio_exposure": portfolio_exposure,
                    "benchmark_exposure": benchmark_exposure,
                    "active_exposure": active_exposure,
                    "portfolio_coverage": portfolio_coverage,
                    "benchmark_coverage": benchmark_coverage,
                }
            )
    return pd.DataFrame(exposure_rows)


def _weighted_exposure(
    weights: pd.Series,
    style_values: pd.Series,
    minimum_coverage: float,
) -> tuple[float, float]:
    """返回有效样本内归一化暴露及其覆盖的原组合权重。"""
    valid_assets = style_values.notna() & weights.gt(0.0)
    valid_weights = weights.loc[valid_assets]
    coverage = float(valid_weights.sum())
    if coverage < minimum_coverage:
        return np.nan, coverage
    normalized_weights = valid_weights / coverage
    exposure = normalized_weights.dot(style_values.loc[valid_assets])
    return float(exposure), coverage
