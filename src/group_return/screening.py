"""把因子评价结果整理为第一阶段候选筛选表。"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import numpy as np
import pandas as pd

from src.group_return.grouping import core_group_ids

SCREENING_COLUMNS = [
    "factor_name",
    "target_type",
    "horizon_value",
    "horizon_unit",
    "start",
    "end",
    "n_dates",
    "n_complete_dates",
    "valid_date_ratio",
    "mean_stock_count",
    "min_stock_count",
    "factor_coverage_rate",
    "factor_zero_rate",
    "ic_mean",
    "ic_std",
    "icir",
    "ic_n_dates",
    "rank_ic_mean",
    "rank_ic_std",
    "rank_icir",
    "rank_ic_n_dates",
    "rank_ic_positive_rate",
    "factor_direction",
    "rank_ic_consistent_rate",
    "q1_return",
    "q10_return",
    "high_minus_low_return",
    "oriented_long_short_return",
    "group_monotonicity",
    "long_short_consistent_rate",
]
BACKTEST_METRIC_COLUMNS = [
    "total_return",
    "annual_return",
    "sharpe",
    "mean_turnover",
    "turnover",
    "benchmark_total_return",
    "excess_total_return",
]
FREQUENCY_TO_HORIZON_UNIT = {
    "daily": "trading_days",
    "weekly": "weeks",
}
HORIZON_UNIT_TO_FREQUENCY = {
    horizon_unit: frequency
    for frequency, horizon_unit in FREQUENCY_TO_HORIZON_UNIT.items()
}


def build_factor_screening_summary(
    evaluation_results: Mapping[str, Mapping[str, Any]],
    settings: Mapping[str, Any],
) -> pd.DataFrame:
    """按因子和未来周期汇总覆盖度、IC、分组收益与方向稳定性。"""
    records = []
    for factor_name, result in evaluation_results.items():
        factor_quality = result["factor_quality"].iloc[0]
        group_order = core_group_ids(result["definitions"])
        for ic_summary in result["ic_summary"].itertuples(index=False):
            records.append(
                _build_horizon_record(
                    factor_name=factor_name,
                    result=result,
                    settings=settings,
                    factor_quality=factor_quality,
                    group_order=group_order,
                    ic_summary=ic_summary,
                )
            )
    return pd.DataFrame.from_records(records)


def build_frequency_summaries(
    screening_summary: pd.DataFrame | None,
    backtest_summary: pd.DataFrame | None,
    existing_summaries: Mapping[str, pd.DataFrame] | None = None,
) -> dict[str, pd.DataFrame]:
    """构建按频率分表、按周期展开且每因子一行的汇总。"""
    frequency_summaries = {
        frequency: summary.copy()
        for frequency, summary in (existing_summaries or {}).items()
    }
    if screening_summary is not None:
        frequency_summaries.update(
            _pivot_screening_summaries(screening_summary)
        )
    if backtest_summary is not None:
        frequency_summaries = _merge_backtest_summaries(
            frequency_summaries,
            backtest_summary,
        )
    return {
        frequency: summary.sort_values("factor_name").reset_index(drop=True)
        for frequency, summary in frequency_summaries.items()
    }


def _pivot_screening_summaries(
    screening_summary: pd.DataFrame,
) -> dict[str, pd.DataFrame]:
    """把评价长表转换为 daily/weekly 两张周期宽表。"""
    identity_columns = [
        "factor_name",
        "target_type",
        "factor_coverage_rate",
        "factor_zero_rate",
    ]
    horizon_columns = [
        column
        for column in SCREENING_COLUMNS
        if column
        not in {
            *identity_columns,
            "horizon_value",
            "horizon_unit",
        }
    ]
    summaries = {}
    for horizon_unit, frequency in HORIZON_UNIT_TO_FREQUENCY.items():
        frequency_rows = screening_summary.loc[
            screening_summary["horizon_unit"] == horizon_unit
        ]
        if frequency_rows.empty:
            continue
        factor_identity = frequency_rows[identity_columns].drop_duplicates(
            subset="factor_name"
        )
        summary = factor_identity.set_index("factor_name")
        for horizon_value in sorted(frequency_rows["horizon_value"].unique()):
            horizon_rows = frequency_rows.loc[
                frequency_rows["horizon_value"] == horizon_value,
                ["factor_name", *horizon_columns],
            ].set_index("factor_name")
            suffix = _period_suffix(frequency, horizon_value)
            horizon_rows = horizon_rows.add_suffix(f"_{suffix}")
            summary = summary.join(horizon_rows, how="outer")
        summaries[frequency] = summary.reset_index()
    return summaries


def _merge_backtest_summaries(
    frequency_summaries: dict[str, pd.DataFrame],
    backtest_summary: pd.DataFrame,
) -> dict[str, pd.DataFrame]:
    """将 simple G10 指标写入对应频率和调仓周期列。"""
    merged_summaries = dict(frequency_summaries)
    for frequency, frequency_rows in backtest_summary.groupby(
        "rebalance_frequency",
        sort=False,
    ):
        summary = merged_summaries.get(
            frequency,
            pd.DataFrame({"factor_name": frequency_rows["factor_name"].unique()}),
        ).set_index("factor_name")
        for interval in sorted(frequency_rows["rebalance_interval"].unique()):
            interval_rows = frequency_rows.loc[
                frequency_rows["rebalance_interval"] == interval,
                ["factor_name", *BACKTEST_METRIC_COLUMNS],
            ].set_index("factor_name")
            suffix = _period_suffix(frequency, interval)
            interval_rows = interval_rows.add_suffix(f"_{suffix}")
            summary = summary.drop(
                columns=interval_rows.columns,
                errors="ignore",
            ).join(interval_rows, how="outer")
        merged_summaries[frequency] = summary.reset_index()
    return merged_summaries


def _period_suffix(frequency: str, interval: int) -> str:
    """把调仓周期转换为宽表列名中的 d/w 后缀。"""
    unit = "d" if frequency == "daily" else "w"
    return f"{int(interval)}{unit}"


def _build_horizon_record(
    factor_name: str,
    result: Mapping[str, Any],
    settings: Mapping[str, Any],
    factor_quality: pd.Series,
    group_order: list[str],
    ic_summary: Any,
) -> dict[str, Any]:
    """构造一个因子在一个未来收益周期上的完整筛选记录。"""
    horizon_filter = (
        (result["ic"]["horizon_value"] == ic_summary.horizon_value)
        & (result["ic"]["horizon_unit"] == ic_summary.horizon_unit)
    )
    ic_observations = result["ic"].loc[horizon_filter]
    group_summary = result["summary"].loc[
        (result["summary"]["horizon_value"] == ic_summary.horizon_value)
        & (result["summary"]["horizon_unit"] == ic_summary.horizon_unit)
    ].set_index("group_id")
    group_detail = result["detail"].loc[
        (result["detail"]["horizon_value"] == ic_summary.horizon_value)
        & (result["detail"]["horizon_unit"] == ic_summary.horizon_unit)
    ]

    factor_direction, direction_sign = _factor_direction(
        ic_summary.rank_ic_mean
    )
    rank_ic_values = ic_observations["rank_ic"].dropna()
    low_group = group_order[0]
    high_group = group_order[-1]
    low_return = group_summary.at[low_group, "group_return"]
    high_return = group_summary.at[high_group, "group_return"]
    high_minus_low_return = high_return - low_return

    return {
        "factor_name": factor_name,
        "target_type": settings["target"]["type"],
        "horizon_value": ic_summary.horizon_value,
        "horizon_unit": ic_summary.horizon_unit,
        "start": ic_summary.start,
        "end": ic_summary.end,
        "n_dates": ic_summary.n_dates,
        "n_complete_dates": ic_summary.n_complete_dates,
        "valid_date_ratio": ic_summary.n_complete_dates / ic_summary.n_dates,
        "mean_stock_count": ic_observations["n_stocks"].mean(),
        "min_stock_count": ic_observations["n_stocks"].min(),
        "factor_coverage_rate": factor_quality.factor_coverage_rate,
        "factor_zero_rate": factor_quality.factor_zero_rate,
        "ic_mean": ic_summary.ic_mean,
        "ic_std": ic_summary.ic_std,
        "icir": ic_summary.icir,
        "ic_n_dates": ic_summary.ic_n_dates,
        "rank_ic_mean": ic_summary.rank_ic_mean,
        "rank_ic_std": ic_summary.rank_ic_std,
        "rank_icir": ic_summary.rank_icir,
        "rank_ic_n_dates": ic_summary.rank_ic_n_dates,
        "rank_ic_positive_rate": (rank_ic_values > 0).mean(),
        "factor_direction": factor_direction,
        "rank_ic_consistent_rate": _consistent_rate(
            rank_ic_values,
            direction_sign,
        ),
        "q1_return": low_return,
        "q10_return": high_return,
        "high_minus_low_return": high_minus_low_return,
        "oriented_long_short_return": (
            high_minus_low_return * direction_sign
        ),
        "group_monotonicity": _group_monotonicity(
            group_summary,
            group_order,
        ),
        "long_short_consistent_rate": _long_short_consistent_rate(
            group_detail,
            low_group,
            high_group,
            direction_sign,
        ),
    }


def _factor_direction(rank_ic_mean: float) -> tuple[str, float]:
    """用 RankIC 均值确定因子方向及多空收益统一方向。"""
    if pd.isna(rank_ic_mean):
        return "unavailable", np.nan
    if rank_ic_mean >= 0:
        return "positive", 1.0
    return "negative", -1.0


def _consistent_rate(values: pd.Series, direction_sign: float) -> float:
    """计算序列与因子主要方向同号的有效日期比例。"""
    if pd.isna(direction_sign):
        return np.nan
    return (values * direction_sign > 0).mean()


def _group_monotonicity(
    group_summary: pd.DataFrame,
    group_order: list[str],
) -> float:
    """计算分组顺序与组收益之间的 Spearman 相关。"""
    group_returns = group_summary.reindex(group_order)["group_return"]
    group_positions = pd.Series(
        np.arange(1, len(group_order) + 1),
        index=group_order,
    )
    return group_positions.corr(group_returns, method="spearman")


def _long_short_consistent_rate(
    group_detail: pd.DataFrame,
    low_group: str,
    high_group: str,
    direction_sign: float,
) -> float:
    """计算逐期高减低收益与因子主要方向一致的比例。"""
    if pd.isna(direction_sign):
        return np.nan
    group_returns = group_detail.pivot(
        index="date",
        columns="group_id",
        values="group_return",
    )
    long_short_returns = (
        group_returns[high_group] - group_returns[low_group]
    ).dropna()
    return (long_short_returns * direction_sign > 0).mean()
