"""计算策略目标权重相对指数目标权重的偏离。"""

from __future__ import annotations

import pandas as pd


def calculate_weight_deviation(
    target_weights: pd.DataFrame,
    benchmark_weights: pd.DataFrame,
) -> pd.DataFrame:
    """返回 Active Share、最大超配和最大低配的调仓日序列。"""
    aligned_target, aligned_benchmark = align_weight_panels(
        target_weights,
        benchmark_weights,
    )
    active_weights = aligned_target - aligned_benchmark
    return pd.DataFrame(
        {
            "date": aligned_target.index,
            "active_share": 0.5 * active_weights.abs().sum(axis=1),
            "max_overweight": active_weights.max(axis=1),
            "max_underweight": active_weights.min(axis=1),
        }
    ).reset_index(drop=True)


def calculate_concentration(
    target_weights: pd.DataFrame,
    benchmark_weights: pd.DataFrame,
) -> pd.DataFrame:
    """返回策略和基准的有效持股数、HHI、Top10 占比及 Active Share。"""
    aligned_target, aligned_benchmark = align_weight_panels(
        target_weights,
        benchmark_weights,
    )
    strategy_hhi = aligned_target.pow(2).sum(axis=1)
    benchmark_hhi = aligned_benchmark.pow(2).sum(axis=1)
    active_weights = aligned_target - aligned_benchmark
    return pd.DataFrame(
        {
            "date": aligned_target.index,
            "effective_holdings": 1.0 / strategy_hhi.replace(0.0, pd.NA),
            "benchmark_effective_holdings": 1.0
            / benchmark_hhi.replace(0.0, pd.NA),
            "stock_hhi": strategy_hhi,
            "benchmark_stock_hhi": benchmark_hhi,
            "top10_share": aligned_target.apply(
                lambda weights: weights.nlargest(10).sum(),
                axis=1,
            ),
            "active_share": 0.5 * active_weights.abs().sum(axis=1),
            "max_overweight": active_weights.max(axis=1),
            "max_underweight": active_weights.min(axis=1),
        }
    ).reset_index(drop=True)


def align_weight_panels(
    target_weights: pd.DataFrame,
    benchmark_weights: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """在调仓日和股票列并集上对齐策略、基准权重。"""
    asset_codes = target_weights.columns.union(benchmark_weights.columns)
    aligned_target = target_weights.reindex(columns=asset_codes, fill_value=0.0)
    aligned_benchmark = benchmark_weights.reindex(
        index=target_weights.index,
        columns=asset_codes,
        fill_value=0.0,
    ).fillna(0.0)
    return aligned_target.fillna(0.0), aligned_benchmark


def summarize_weight_deviation(deviation: pd.DataFrame) -> dict[str, float]:
    """把偏离度时序汇总为策略根目录宽表使用的三个指标。"""
    return {
        "mean_active_share": float(deviation["active_share"].mean()),
        "max_overweight": float(deviation["max_overweight"].max()),
        "max_underweight": float(deviation["max_underweight"].min()),
    }
