"""汇总一批因子的横截面相关性、IC 和分组收益。"""

from __future__ import annotations

from collections.abc import Mapping
from concurrent.futures import ThreadPoolExecutor
from itertools import repeat
from typing import Any

import numpy as np
import pandas as pd

from src.data.market_data import MarketData
from src.group_return.evaluator import rowwise_correlation


def evaluate_overall(
    factor_panels: Mapping[str, pd.DataFrame],
    evaluation_results: Mapping[str, Mapping[str, Any]],
    market_data: MarketData,
    evaluation_settings: Mapping[str, Any],
    max_workers: int | None = None,
) -> dict[str, pd.DataFrame]:
    """汇总跨因子相关性、平均 RankIC 和高减低分组收益。"""
    factor_names = list(factor_panels)
    evaluation_dates, factor_dates = _evaluation_date_mapping(
        evaluation_results[factor_names[0]]
    )
    membership = _evaluation_membership(
        market_data,
        evaluation_dates,
        evaluation_settings["universe_indices"],
    )
    factor_arrays = {
        factor_name: factor_panel.reindex(
            index=factor_dates,
            columns=membership.columns,
        ).to_numpy(dtype=float)
        for factor_name, factor_panel in factor_panels.items()
    }
    correlation = _mean_cross_sectional_correlations(
        factor_names=factor_names,
        factor_arrays=factor_arrays,
        membership=membership.to_numpy(dtype=bool),
        min_stocks=evaluation_settings["grouping"]["min_stocks"],
        max_workers=max_workers,
    )
    return {
        "factor_correlation": correlation,
        "factor_ic": _factor_ic_summary(evaluation_results),
        "factor_return": _factor_return_summary(evaluation_results),
    }


def _evaluation_date_mapping(
    evaluation_result: Mapping[str, Any],
) -> tuple[pd.DatetimeIndex, pd.DatetimeIndex]:
    """取得评价日到实际因子来源日的一一映射。"""
    date_mapping = evaluation_result["ic"][
        ["date", "factor_date"]
    ].drop_duplicates()
    return (
        pd.DatetimeIndex(date_mapping["date"], name="date"),
        pd.DatetimeIndex(date_mapping["factor_date"], name="factor_date"),
    )


def _evaluation_membership(
    market_data: MarketData,
    evaluation_dates: pd.DatetimeIndex,
    universe_indices: list[str],
) -> pd.DataFrame:
    """重建与 group return 完全一致的评价日股票池。"""
    membership = pd.DataFrame(
        False,
        index=evaluation_dates,
        columns=market_data.membership.columns,
    )
    for index_code in universe_indices:
        index_membership = market_data.get_panel(
            "index_membership",
            "membership",
            index_code=index_code,
        )
        membership |= index_membership.reindex(
            index=evaluation_dates,
            columns=membership.columns,
        ).astype(bool)
    return membership


def _mean_cross_sectional_correlations(
    factor_names: list[str],
    factor_arrays: Mapping[str, np.ndarray],
    membership: np.ndarray,
    min_stocks: int,
    max_workers: int | None,
) -> pd.DataFrame:
    """因子对并行计算逐日 Spearman 相关，再对有效日期取均值。"""
    pair_positions = [
        (left_position, right_position)
        for left_position in range(len(factor_names))
        for right_position in range(left_position, len(factor_names))
    ]
    if max_workers == 1:
        pair_results = [
            _factor_pair_correlation(
                pair_position,
                factor_names,
                factor_arrays,
                membership,
                min_stocks,
            )
            for pair_position in pair_positions
        ]
    else:
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            pair_results = list(
                executor.map(
                    _factor_pair_correlation,
                    pair_positions,
                    repeat(factor_names),
                    repeat(factor_arrays),
                    repeat(membership),
                    repeat(min_stocks),
                )
            )

    correlation_values = np.full(
        (len(factor_names), len(factor_names)),
        np.nan,
    )
    for left_position, right_position, mean_correlation in pair_results:
        correlation_values[left_position, right_position] = mean_correlation
        correlation_values[right_position, left_position] = mean_correlation
    return pd.DataFrame(
        correlation_values,
        index=pd.Index(factor_names, name="factor_name"),
        columns=pd.Index(factor_names, name="factor_name"),
    )


def _factor_pair_correlation(
    pair_position: tuple[int, int],
    factor_names: list[str],
    factor_arrays: Mapping[str, np.ndarray],
    membership: np.ndarray,
    min_stocks: int,
) -> tuple[int, int, float]:
    """计算一个因子对的平均逐日横截面 Rank 相关。"""
    left_position, right_position = pair_position
    left_values = factor_arrays[factor_names[left_position]]
    right_values = factor_arrays[factor_names[right_position]]
    valid_values = membership & np.isfinite(left_values) & np.isfinite(right_values)
    aligned_left = np.where(valid_values, left_values, np.nan)
    aligned_right = np.where(valid_values, right_values, np.nan)
    daily_correlations = rowwise_correlation(
        aligned_left,
        aligned_right,
        rank=True,
    )
    daily_correlations[valid_values.sum(axis=1) < min_stocks] = np.nan
    return left_position, right_position, float(np.nanmean(daily_correlations))


def _factor_ic_summary(
    evaluation_results: Mapping[str, Mapping[str, Any]],
) -> pd.DataFrame:
    """每个因子和未来周期保留一个平均 RankIC。"""
    records = []
    for factor_name, result in evaluation_results.items():
        for row in result["ic_summary"].itertuples(index=False):
            records.append(
                {
                    "factor_name": factor_name,
                    "horizon_value": row.horizon_value,
                    "horizon_unit": row.horizon_unit,
                    "rank_ic_mean": row.rank_ic_mean,
                }
            )
    return pd.DataFrame(records)


def _factor_return_summary(
    evaluation_results: Mapping[str, Mapping[str, Any]],
) -> pd.DataFrame:
    """每个因子和未来周期计算最高分位组减最低分位组收益。"""
    records = []
    for factor_name, result in evaluation_results.items():
        definitions = result["definitions"].sort_values("quantile_lower")
        low_group = definitions["group_id"].iloc[0]
        high_group = definitions["group_id"].iloc[-1]
        summary = result["summary"].pivot(
            index=["horizon_value", "horizon_unit"],
            columns="group_id",
            values="group_return",
        )
        high_minus_low = summary[high_group] - summary[low_group]
        for (horizon_value, horizon_unit), factor_return in high_minus_low.items():
            records.append(
                {
                    "factor_name": factor_name,
                    "horizon_value": horizon_value,
                    "horizon_unit": horizon_unit,
                    "high_minus_low_return": factor_return,
                }
            )
    return pd.DataFrame(records)
