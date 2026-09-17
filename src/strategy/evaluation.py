"""计算策略目标权重相对指数目标权重的偏离。"""

from __future__ import annotations

import pandas as pd


def calculate_weight_deviation(
    target_weights: pd.DataFrame,
    benchmark_weights: pd.DataFrame,
) -> pd.DataFrame:
    """返回 Active Share、最大超配和最大低配的调仓日序列。"""
    aligned_benchmark = benchmark_weights.reindex(
        index=target_weights.index,
        columns=target_weights.columns,
        fill_value=0.0,
    ).fillna(0.0)
    active_weights = target_weights - aligned_benchmark
    return pd.DataFrame(
        {
            "date": target_weights.index,
            "active_share": 0.5 * active_weights.abs().sum(axis=1),
            "max_overweight": active_weights.max(axis=1),
            "max_underweight": active_weights.min(axis=1),
        }
    ).reset_index(drop=True)


def summarize_weight_deviation(deviation: pd.DataFrame) -> dict[str, float]:
    """把偏离度时序汇总为策略根目录宽表使用的三个指标。"""
    return {
        "mean_active_share": float(deviation["active_share"].mean()),
        "max_overweight": float(deviation["max_overweight"].max()),
        "max_underweight": float(deviation["max_underweight"].min()),
    }
