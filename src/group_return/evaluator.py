"""
矩阵化评价多个固定未来周期的分组收益、IC 和 RankIC。

``evaluate`` 处理单个标准日频因子面板，``evaluate_factors`` 复用一次市场
上下文并在因子粒度线程并行。模块不模拟调仓、成交、费用或账户净值，也不负责
读取 YAML 和保存结果。
"""

from __future__ import annotations

import os
from collections.abc import Iterable, Iterator, Mapping
from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd

from src.data.market_data import MarketData
from src.group_return.grouping import build_group_definitions, group_cross_sections

WEEKDAY_NUMBER = {
    "MON": 0,
    "TUE": 1,
    "WED": 2,
    "THU": 3,
    "FRI": 4,
}


@dataclass(frozen=True)
class _EvaluationContext:
    """保存一批 Factor 共享的日期、股票池、价格和分组上下文。"""

    calendar: pd.DatetimeIndex
    stock_codes: pd.Index
    sample_dates: pd.DatetimeIndex
    sample_positions: np.ndarray
    factor_dates: pd.DatetimeIndex
    membership: pd.DataFrame
    group_definitions: pd.DataFrame
    weight_values: pd.DataFrame | None
    horizon_values: np.ndarray
    horizon_units: np.ndarray
    return_end_positions: np.ndarray
    return_end_dates: np.ndarray
    horizon_complete: np.ndarray
    reference_prices: pd.DataFrame | None
    price_filled: pd.DataFrame | None
    external_future_returns: np.ndarray | None
    benchmark_returns: np.ndarray | None


@dataclass(frozen=True)
class _FutureReturnMatrices:
    """保存单个 Factor 的未来收益和补价矩阵。"""

    completed_evaluations: np.ndarray
    required_prices: np.ndarray
    future_returns: np.ndarray
    combined_price_filled: np.ndarray


# 按固定锚定周和指定星期选择因子评价日期。
def _sample_dates(
    calendar: pd.DatetimeIndex,
    start: str,
    end: str,
    sampling: Mapping[str, Any],
) -> pd.DatetimeIndex:
    """
    构造 group_return 的评价日序列。

    输入：
    - calendar：市场数据的真实交易日历。
    - start、end：评价区间闭区间。
    - sampling：星期、周间隔、锚定日和节假日策略。

    输出：
    - 返回按时间升序排列的评价交易日。

    功能和用途：
    - 锚定周固定采样相位，改变评价区间不会改变原有日期的采样批次。
    - 节假日回退仅发生在当前自然周内。
    """
    start_date = pd.Timestamp(start)
    end_date = pd.Timestamp(end)
    anchor_monday = pd.Timestamp(sampling["anchor_date"]).normalize()
    anchor_monday -= pd.Timedelta(days=anchor_monday.weekday())
    first_monday = start_date.normalize() - pd.Timedelta(days=start_date.weekday())

    selected_dates = []
    for week_start in pd.date_range(first_monday, end_date, freq="7D"):
        week_number = (week_start - anchor_monday).days // 7
        if week_number % sampling["every_n_weeks"]:
            continue

        target_date = week_start + pd.Timedelta(
            days=WEEKDAY_NUMBER[sampling["weekday"]]
        )
        if target_date > end_date:
            continue
        if target_date in calendar:
            selected_date = target_date
        elif sampling["holiday_policy"] == "skip":
            continue
        else:
            earlier_days = calendar[
                (calendar >= week_start) & (calendar < target_date)
            ]
            if earlier_days.empty:
                continue
            selected_date = earlier_days[-1]

        if start_date <= selected_date <= end_date:
            selected_dates.append(selected_date)

    return pd.DatetimeIndex(selected_dates, name="date")


def _prepare_return_horizons(
    calendar: pd.DatetimeIndex,
    sample_dates: pd.DatetimeIndex,
    sample_positions: np.ndarray,
    settings: Mapping[str, Any],
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """按交易日位移和自然周目标日分别计算未来收益端点。"""
    future_return_days = np.asarray(
        settings.get("future_return_days", []),
        dtype=int,
    )
    future_return_weeks = np.asarray(
        settings.get("future_return_weeks", []),
        dtype=int,
    )
    day_end_positions = (
        sample_positions[None, :] + future_return_days[:, None]
    )

    week_end_positions = np.empty(
        (len(future_return_weeks), len(sample_dates)),
        dtype=int,
    )
    if len(future_return_weeks):
        sample_week_starts = sample_dates - pd.to_timedelta(
            sample_dates.weekday,
            unit="D",
        )
        target_week_starts = (
            sample_week_starts.to_numpy()[None, :]
            + future_return_weeks[:, None] * np.timedelta64(7, "D")
        )
        target_dates = target_week_starts + np.timedelta64(
            WEEKDAY_NUMBER[settings["sampling"]["weekday"]],
            "D",
        )
        exact_positions = calendar.get_indexer(target_dates.reshape(-1)).reshape(
            target_dates.shape
        )
        if settings["sampling"]["holiday_policy"] == "skip":
            week_end_positions = exact_positions
        else:
            previous_positions = calendar.searchsorted(
                target_dates.reshape(-1),
                side="left",
            ).reshape(target_dates.shape) - 1
            safe_previous_positions = np.maximum(previous_positions, 0)
            previous_dates = calendar.to_numpy()[safe_previous_positions]
            valid_previous_dates = (
                (previous_positions >= 0)
                & (previous_dates >= target_week_starts)
            )
            fallback_positions = np.where(
                valid_previous_dates,
                previous_positions,
                -1,
            )
            week_end_positions = np.where(
                exact_positions >= 0,
                exact_positions,
                fallback_positions,
            )

    horizon_values = np.concatenate(
        [future_return_days, future_return_weeks]
    )
    horizon_units = np.asarray(
        ["trading_days"] * len(future_return_days)
        + ["weeks"] * len(future_return_weeks),
        dtype=object,
    )
    return (
        horizon_values,
        horizon_units,
        np.concatenate([day_end_positions, week_end_positions]),
    )


def _compound_external_returns(
    return_panel: pd.DataFrame,
    calendar: pd.DatetimeIndex,
    stock_codes: pd.Index,
    sample_positions: np.ndarray,
    return_end_positions: np.ndarray,
) -> np.ndarray:
    """按 t-1 收盘到 t 收盘口径批量复合各评价区间的日收益。"""
    aligned_returns = return_panel.reindex(
        index=calendar,
        columns=stock_codes,
    ).to_numpy(dtype=float)
    valid_returns = np.isfinite(aligned_returns)
    cumulative_log_returns = np.cumsum(
        np.where(valid_returns, np.log1p(aligned_returns), 0.0),
        axis=0,
    )
    cumulative_missing_counts = np.cumsum(~valid_returns, axis=0)
    safe_end_positions = np.clip(return_end_positions, 0, len(calendar) - 1)
    interval_log_returns = (
        cumulative_log_returns[safe_end_positions]
        - cumulative_log_returns[sample_positions][None, :, :]
    )
    interval_missing_counts = (
        cumulative_missing_counts[safe_end_positions]
        - cumulative_missing_counts[sample_positions][None, :, :]
    )
    compounded_returns = np.expm1(interval_log_returns)
    return np.where(interval_missing_counts == 0, compounded_returns, np.nan)


def _benchmark_horizon_returns(
    market_data: MarketData,
    benchmark_source: str,
    sample_positions: np.ndarray,
    return_end_positions: np.ndarray,
    horizon_complete: np.ndarray,
) -> np.ndarray:
    """按评价起终点计算配置基准的同期收益。"""
    benchmark_prices = market_data.get_panel(
        benchmark_source,
        "S_DQ_CLOSE",
    )[market_data.benchmark_index].reindex(market_data.calendar).to_numpy(dtype=float)
    safe_end_positions = np.clip(
        return_end_positions,
        0,
        len(market_data.calendar) - 1,
    )
    start_prices = benchmark_prices[sample_positions]
    end_prices = benchmark_prices[safe_end_positions]
    benchmark_returns = end_prices / start_prices[None, :] - 1.0
    missing_benchmark = horizon_complete & ~np.isfinite(benchmark_returns)
    if missing_benchmark.any():
        horizon_position, date_position = np.argwhere(missing_benchmark)[0]
        evaluation_date = market_data.calendar[sample_positions[date_position]]
        raise ValueError(
            "评价目标缺少基准收益: "
            f"{evaluation_date.date()} horizon={horizon_position}"
        )
    return benchmark_returns


def _horizon_label(context: _EvaluationContext, position: int) -> str:
    """生成人类可读且不混淆交易日与自然周的周期标签。"""
    unit = {
        "trading_days": "个交易日",
        "weeks": "周",
    }[context.horizon_units[position]]
    return f"{context.horizon_values[position]}{unit}"


# 根据交易日位置批量取得因子或权重字段的滞后截面。
def _lagged_rows(
    panel: pd.DataFrame,
    calendar: pd.DatetimeIndex,
    evaluation_dates: pd.DatetimeIndex,
    lag_days: int,
) -> tuple[pd.DataFrame, pd.DatetimeIndex]:
    """
    取得评价日对应的滞后数据行。

    输入：
    - panel：按完整交易日历排列的日期乘股票面板。
    - calendar：确定交易日位置的统一日历。
    - evaluation_dates：需要评价的交易日。
    - lag_days：相对评价日向前移动的交易日数。

    输出：
    - 返回以评价日为索引的数据矩阵和实际使用的来源日期。

    功能和用途：
    - 因子值与字段权重使用同一套交易日滞后语义。
    """
    evaluation_positions = calendar.get_indexer(evaluation_dates)
    source_positions = evaluation_positions - lag_days
    if (source_positions < 0).any():
        raise ValueError("市场数据没有覆盖因子或权重字段所需的滞后历史")

    source_dates = calendar[source_positions]
    selected_values = panel.reindex(calendar).iloc[source_positions].copy()
    selected_values.index = evaluation_dates
    return selected_values, source_dates


# 一次性准备复权参考价格及严格向过去查找的补价信息。
def _prepare_reference_prices(
    market_data: MarketData,
    reference_price: str,
    missing_price_policy: str,
    max_stale_days: int | None,
    stock_codes: pd.Index,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """
    准备全部交易日的评价参考价格。

    输入：
    - market_data：共享市场数据对象。
    - reference_price：``close`` 或 ``open``。
    - missing_price_policy：``error`` 或 ``previous_close``。
    - max_stale_days：历史收盘补价允许的最大交易日陈旧度。
    - stock_codes：评价使用的固定股票列顺序。

    输出：
    - 返回参考价格和是否使用历史收盘的日频面板。

    功能和用途：
    - ``previous_close`` 只读取参考日前已经出现的正复权收盘。
    """
    price_field = "S_DQ_ADJCLOSE" if reference_price == "close" else "S_DQ_ADJOPEN"
    raw_price_panel = market_data.get_panel("stock_quote", price_field).reindex(
        index=market_data.calendar,
        columns=stock_codes,
    )
    adjusted_close_panel = market_data.get_panel(
        "stock_quote",
        "S_DQ_ADJCLOSE",
    ).reindex(
        index=market_data.calendar,
        columns=stock_codes,
    )

    raw_prices = raw_price_panel.to_numpy(dtype=float)
    adjusted_closes = adjusted_close_panel.to_numpy(dtype=float)
    valid_raw_prices = np.isfinite(raw_prices) & (raw_prices > 0)
    valid_closes = np.isfinite(adjusted_closes) & (adjusted_closes > 0)
    calendar_positions = np.arange(len(market_data.calendar), dtype=np.int32)

    last_close_positions = np.maximum.accumulate(
        np.where(valid_closes, calendar_positions[:, None], -1),
        axis=0,
    )
    previous_close_positions = np.empty_like(last_close_positions)
    previous_close_positions[0] = -1
    previous_close_positions[1:] = last_close_positions[:-1]

    reference_values = np.where(valid_raw_prices, raw_prices, np.nan)
    price_filled = np.zeros_like(valid_raw_prices)

    if missing_price_policy == "previous_close":
        available_previous_close = previous_close_positions >= 0
        stale_days = calendar_positions[:, None] - previous_close_positions
        fill_prices = ~valid_raw_prices & available_previous_close
        if max_stale_days is not None:
            fill_prices &= stale_days <= max_stale_days

        safe_previous_positions = np.maximum(previous_close_positions, 0)
        previous_close_values = np.take_along_axis(
            adjusted_closes,
            safe_previous_positions,
            axis=0,
        )
        reference_values[fill_prices] = previous_close_values[fill_prices]
        price_filled[fill_prices] = True

    reference_price_panel = pd.DataFrame(
        reference_values,
        index=market_data.calendar,
        columns=stock_codes,
    )
    price_filled_panel = pd.DataFrame(
        price_filled,
        index=market_data.calendar,
        columns=stock_codes,
    )
    return reference_price_panel, price_filled_panel


# 为一批 Factor 准备只计算一次的市场评价上下文。
def _prepare_context(
    market_data: MarketData,
    settings: Mapping[str, Any],
    return_panel: pd.DataFrame | None = None,
) -> _EvaluationContext:
    """
    准备 group_return 的共享计算上下文。

    输入：
    - market_data：包含行情和各指数历史成员的市场数据。
    - settings：已经解析的 ``group_return`` 配置。

    输出：
    - 返回可供多个 Factor 只读共享的 ``_EvaluationContext``。

    功能和用途：
    - 采样、股票池、字段权重、未来端点和价格补齐只准备一次。
    """
    calendar = market_data.calendar
    stock_codes = market_data.membership.columns
    sample_dates = _sample_dates(
        calendar,
        settings["start"],
        settings["end"],
        settings["sampling"],
    )
    if sample_dates.empty:
        raise ValueError("group_return 配置区间内没有评价日期")

    sample_positions = calendar.get_indexer(sample_dates)
    factor_positions = sample_positions - settings["factor_lag_days"]
    if (factor_positions < 0).any():
        raise ValueError("市场数据没有覆盖 factor_lag_days 所需历史")
    factor_dates = calendar[factor_positions]

    membership = pd.DataFrame(False, index=sample_dates, columns=stock_codes)
    for index_code in settings["universe_indices"]:
        index_membership = market_data.get_panel(
            "index_membership",
            "membership",
            index_code=index_code,
        )
        membership |= index_membership.reindex(
            index=sample_dates,
            columns=stock_codes,
        ).astype(bool)

    weighting = settings["grouping"]["weighting"]
    weight_values = None
    if weighting["method"] == "field":
        weight_panel = market_data.get_panel(
            weighting["source"],
            weighting["field"],
        ).reindex(columns=stock_codes)
        weight_values, _ = _lagged_rows(
            weight_panel,
            calendar,
            sample_dates,
            weighting["lag_days"],
        )

    horizon_values, horizon_units, return_end_positions = (
        _prepare_return_horizons(
            calendar=calendar,
            sample_dates=sample_dates,
            sample_positions=sample_positions,
            settings=settings,
        )
    )
    positions_in_calendar = (
        (return_end_positions >= 0) & (return_end_positions < len(calendar))
    )
    safe_end_positions = np.clip(return_end_positions, 0, len(calendar) - 1)
    candidate_end_dates = calendar.to_numpy()[safe_end_positions]
    horizon_complete = positions_in_calendar & (
        candidate_end_dates <= np.datetime64(pd.Timestamp(settings["end"]))
    )
    return_end_dates = candidate_end_dates.astype("datetime64[ns]")
    return_end_dates[~positions_in_calendar] = np.datetime64("NaT")

    reference_prices = None
    price_filled = None
    external_future_returns = None
    if return_panel is None:
        reference_prices, price_filled = _prepare_reference_prices(
            market_data=market_data,
            reference_price=settings["reference_price"],
            missing_price_policy=settings["missing_price_policy"],
            max_stale_days=settings["max_stale_days"],
            stock_codes=stock_codes,
        )
    else:
        external_future_returns = _compound_external_returns(
            return_panel=return_panel,
            calendar=calendar,
            stock_codes=stock_codes,
            sample_positions=sample_positions,
            return_end_positions=return_end_positions,
        )

    target_settings = settings["target"]
    benchmark_returns = None
    if target_settings["type"] == "benchmark_excess_return":
        benchmark_returns = _benchmark_horizon_returns(
            market_data=market_data,
            benchmark_source=target_settings["benchmark_source"],
            sample_positions=sample_positions,
            return_end_positions=return_end_positions,
            horizon_complete=horizon_complete,
        )
    group_definitions = build_group_definitions(
        settings["grouping"]["quantile_edges"]
    )
    return _EvaluationContext(
        calendar=calendar,
        stock_codes=stock_codes,
        sample_dates=sample_dates,
        sample_positions=sample_positions,
        factor_dates=factor_dates,
        membership=membership,
        group_definitions=group_definitions,
        weight_values=weight_values,
        horizon_values=horizon_values,
        horizon_units=horizon_units,
        return_end_positions=return_end_positions,
        return_end_dates=return_end_dates,
        horizon_complete=horizon_complete,
        reference_prices=reference_prices,
        price_filled=price_filled,
        external_future_returns=external_future_returns,
        benchmark_returns=benchmark_returns,
    )


# 沿股票轴计算每个截面的 Pearson IC 或平均名次 RankIC。
def rowwise_correlation(
    factor_values: np.ndarray,
    future_returns: np.ndarray,
    rank: bool = False,
) -> np.ndarray:
    """
    计算多个横截面的相关系数。

    输入：
    - factor_values、future_returns：形状相同的二维数组，行为独立截面。
    - rank：为真时先分别计算股票横截面的平均名次。

    输出：
    - 返回每行一个相关系数的一维数组。

    功能和用途：
    - 使用矩阵中心化和内积替代逐日期调用 ``Series.corr``。
    """
    valid_values = np.isfinite(factor_values) & np.isfinite(future_returns)
    if rank:
        factor_values = pd.DataFrame(np.where(valid_values, factor_values, np.nan)).rank(
            axis=1,
            method="average",
        ).to_numpy()
        future_returns = pd.DataFrame(
            np.where(valid_values, future_returns, np.nan)
        ).rank(
            axis=1,
            method="average",
        ).to_numpy()

    valid_counts = valid_values.sum(axis=1)
    safe_counts = np.maximum(valid_counts, 1)
    factor_means = np.nansum(np.where(valid_values, factor_values, np.nan), axis=1)
    factor_means /= safe_counts
    return_means = np.nansum(np.where(valid_values, future_returns, np.nan), axis=1)
    return_means /= safe_counts

    centered_factors = np.where(
        valid_values,
        factor_values - factor_means[:, None],
        0.0,
    )
    centered_returns = np.where(
        valid_values,
        future_returns - return_means[:, None],
        0.0,
    )
    covariance = np.einsum(
        "rs,rs->r",
        centered_factors,
        centered_returns,
        optimize=True,
    )
    factor_squares = np.einsum(
        "rs,rs->r",
        centered_factors,
        centered_factors,
        optimize=True,
    )
    return_squares = np.einsum(
        "rs,rs->r",
        centered_returns,
        centered_returns,
        optimize=True,
    )
    denominator = np.sqrt(factor_squares * return_squares)

    correlations = np.full(len(valid_counts), np.nan)
    valid_correlations = (valid_counts >= 2) & (denominator > 0)
    correlations[valid_correlations] = (
        covariance[valid_correlations] / denominator[valid_correlations]
    )
    return correlations


# 同时构造所有未来周期的固定端点收益和补价矩阵。
def _prepare_future_return_matrices(
    factor_array: np.ndarray,
    enough_stocks: np.ndarray,
    context: _EvaluationContext,
) -> _FutureReturnMatrices:
    """
    准备一个 Factor 的未来收益矩阵。

    输入：
    - factor_array：评价日乘股票的有效因子矩阵。
    - enough_stocks：每个评价日是否达到最少股票数。
    - context：共享参考价格、端点位置和周期完整性。

    输出：
    - 返回未来收益、补价标记和有效评价位置。

    功能和用途：
    - 价格只按当期有效因子股票检查，不会反向改变股票资格或分组。
    """
    valid_factor = np.isfinite(factor_array)
    completed_evaluations = context.horizon_complete & enough_stocks[None, :]
    required_prices = completed_evaluations[:, :, None] & valid_factor[None, :, :]
    safe_end_positions = np.clip(
        context.return_end_positions,
        0,
        len(context.calendar) - 1,
    )

    if context.external_future_returns is None:
        reference_prices = context.reference_prices.to_numpy(dtype=float)
        price_filled = context.price_filled.to_numpy(dtype=bool)
        start_prices = reference_prices[context.sample_positions]
        start_price_filled = price_filled[context.sample_positions]
        end_prices = reference_prices[safe_end_positions]
        end_price_filled = price_filled[safe_end_positions]
        source_returns = end_prices / start_prices[None, :, :] - 1.0
        missing_required_values = required_prices & (
            ~np.isfinite(start_prices[None, :, :]) | ~np.isfinite(end_prices)
        )
        combined_price_filled = start_price_filled[None, :, :] | end_price_filled
        missing_label = "未来收益缺少参考价格"
    else:
        source_returns = context.external_future_returns
        missing_required_values = required_prices & ~np.isfinite(source_returns)
        combined_price_filled = np.zeros_like(required_prices, dtype=bool)
        missing_label = "未来收益缺少外部日收益"

    if missing_required_values.any():
        horizon_position, date_position, stock_position = np.argwhere(
            missing_required_values
        )[0]
        raise ValueError(
            f"{missing_label}: "
            f"{context.sample_dates[date_position].date()} "
            f"{_horizon_label(context, horizon_position)} "
            f"{context.stock_codes[stock_position]}"
        )

    future_returns = source_returns
    if context.benchmark_returns is not None:
        future_returns = future_returns - context.benchmark_returns[:, :, None]
    future_returns = np.where(required_prices, future_returns, np.nan)
    return _FutureReturnMatrices(
        completed_evaluations=completed_evaluations,
        required_prices=required_prices,
        future_returns=future_returns,
        combined_price_filled=combined_price_filled,
    )


# 聚合所有未来周期和独立分位区间的收益、人数与状态。
def _calculate_group_return_matrices(
    group_membership: np.ndarray,
    group_weight_denominators: np.ndarray,
    base_weights: np.ndarray,
    enough_stocks: np.ndarray,
    future_matrices: _FutureReturnMatrices,
    context: _EvaluationContext,
    settings: Mapping[str, Any],
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """
    计算各未来周期和分位组的收益矩阵。

    输入：
    - 组成员、权重分母、基础权重和最少股票状态。
    - future_matrices：已经完成价格检查的未来收益矩阵。
    - context、settings：提供组定义和聚合策略。

    输出：
    - 返回组规模、组收益、组内补价人数和明细状态矩阵。

    功能和用途：
    - 均值路径使用 ``einsum``，中位数路径只循环少量周期和分组。
    """
    horizon_count = len(context.horizon_values)
    group_count = len(context.group_definitions)
    date_count = len(context.sample_dates)
    group_sizes = group_membership.sum(axis=2)
    complete_empty_groups = (
        future_matrices.completed_evaluations[:, None, :]
        & (group_sizes[None, :, :] == 0)
    )
    if settings["empty_group_policy"] == "error" and complete_empty_groups.any():
        horizon_position, group_position, date_position = np.argwhere(
            complete_empty_groups
        )[0]
        raise ValueError(
            "评价分组为空: "
            f"{context.sample_dates[date_position].date()} "
            f"{_horizon_label(context, horizon_position)} "
            f"{context.group_definitions.iloc[group_position]['group_id']}"
        )

    if settings["group_return_agg"] == "mean":
        return_numerators = np.einsum(
            "hds,gds,ds->hgd",
            np.nan_to_num(future_matrices.future_returns, nan=0.0),
            group_membership,
            base_weights,
            optimize=True,
        )
        group_returns = np.divide(
            return_numerators,
            group_weight_denominators[None, :, :],
            out=np.full_like(return_numerators, np.nan),
            where=group_weight_denominators[None, :, :] > 0,
        )
    else:
        group_returns = np.full(
            (horizon_count, group_count, date_count),
            np.nan,
        )
        for horizon_position in range(horizon_count):
            for group_position in range(group_count):
                valid_dates = future_matrices.completed_evaluations[
                    horizon_position
                ] & (group_sizes[group_position] > 0)
                if valid_dates.any():
                    group_return_values = np.where(
                        group_membership[group_position, valid_dates],
                        future_matrices.future_returns[horizon_position, valid_dates],
                        np.nan,
                    )
                    group_returns[horizon_position, group_position, valid_dates] = (
                        np.nanmedian(group_return_values, axis=1)
                    )
    group_returns = np.where(
        future_matrices.completed_evaluations[:, None, :],
        group_returns,
        np.nan,
    )

    detail_status = np.full(
        (horizon_count, group_count, date_count),
        "complete",
        dtype=object,
    )
    detail_status[:, :, ~enough_stocks] = "insufficient_stocks"
    incomplete_horizons = ~np.broadcast_to(
        context.horizon_complete[:, None, :],
        detail_status.shape,
    )
    detail_status[incomplete_horizons] = "horizon_incomplete"
    detail_status[complete_empty_groups] = "empty_group"

    group_price_filled_counts = np.einsum(
        "hds,gds->hgd",
        (
            future_matrices.combined_price_filled
            & future_matrices.required_prices
        ).astype(np.int64),
        group_membership,
        optimize=True,
    ).astype(int)
    return (
        group_sizes,
        group_returns,
        group_price_filled_counts,
        detail_status,
    )


# 将矩阵化评价结果按未来周期和分组做跨日期统计。
def summarize_evaluation(
    detail: pd.DataFrame,
    ic_series: pd.DataFrame,
    settings: Mapping[str, Any],
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """
    汇总分组收益与总体 IC 序列。

    输入：
    - detail：日期乘未来周期乘分组的收益明细。
    - ic_series：日期乘未来周期的全截面相关序列。
    - settings：提供评价区间和两层收益聚合方法。

    输出：
    - 返回分组收益汇总和 IC 汇总。

    功能和用途：
    - ICIR 和 RankICIR 使用序列均值除以样本标准差，不做年化。
    - 相邻未来收益可以重叠，汇总仅作为描述统计。
    """
    ic_summary_records = []
    for (horizon_value, horizon_unit), observations in ic_series.groupby(
        ["horizon_value", "horizon_unit"],
        sort=False,
    ):
        summary_record = {
            "horizon_value": horizon_value,
            "horizon_unit": horizon_unit,
            "start": settings["start"],
            "end": settings["end"],
            "ic_scope": "full_universe",
            "n_dates": len(observations),
            "n_complete_dates": int((observations["status"] == "complete").sum()),
        }
        for metric_name in ["ic", "rank_ic"]:
            metric_values = observations[metric_name].dropna()
            metric_standard_deviation = metric_values.std(ddof=1)
            summary_record[f"{metric_name}_mean"] = metric_values.mean()
            summary_record[f"{metric_name}_std"] = metric_standard_deviation
            ratio_name = "icir" if metric_name == "ic" else "rank_icir"
            summary_record[ratio_name] = (
                metric_values.mean() / metric_standard_deviation
                if metric_standard_deviation > 0
                else np.nan
            )
            summary_record[f"{metric_name}_n_dates"] = len(metric_values)
        ic_summary_records.append(summary_record)

    group_summary_records = []
    for (horizon_value, horizon_unit, group_id), observations in detail.groupby(
        ["horizon_value", "horizon_unit", "group_id"],
        sort=False,
    ):
        first_observation = observations.iloc[0]
        valid_returns = observations["group_return"].dropna()
        if settings["time_return_agg"] == "mean":
            aggregated_return = valid_returns.mean()
        else:
            aggregated_return = valid_returns.median()
        group_summary_records.append(
            {
                "horizon_value": horizon_value,
                "horizon_unit": horizon_unit,
                "group_id": group_id,
                "quantile_lower": first_observation["quantile_lower"],
                "quantile_upper": first_observation["quantile_upper"],
                "label": first_observation["label"],
                "start": settings["start"],
                "end": settings["end"],
                "group_return_agg": settings["group_return_agg"],
                "time_return_agg": settings["time_return_agg"],
                "group_return": aggregated_return,
                "n_dates": len(observations),
                "n_valid_dates": len(valid_returns),
                "mean_group_size": observations["n_group_stocks"].mean(),
            }
        )
    return pd.DataFrame(group_summary_records), pd.DataFrame(ic_summary_records)


# 计算单个 Factor 的全部未来周期评价表。
def _evaluate_factor(
    factor_panel: pd.DataFrame,
    context: _EvaluationContext,
    settings: Mapping[str, Any],
) -> dict[str, pd.DataFrame | pd.DatetimeIndex]:
    """
    使用共享上下文评价一个因子面板。

    输入：
    - factor_panel：完整交易日乘股票的标准 Factor 面板。
    - context：本批次共用的市场评价上下文。
    - settings：group_return 配置。

    输出：
    - 返回定义、原始评价、IC、汇总、成员、标签和采样日期。

    功能和用途：
    - 收益、分组均值、相关系数和输出坐标均按矩阵批量计算。
    - 未来价格只用于收益，不参与当期股票资格和分组判断。
    """
    aligned_factor_panel = factor_panel.reindex(columns=context.stock_codes)
    factor_values, _ = _lagged_rows(
        aligned_factor_panel,
        context.calendar,
        context.sample_dates,
        settings["factor_lag_days"],
    )
    (
        factor_values,
        _,
        group_membership,
        group_weight_denominators,
    ) = group_cross_sections(
        factor_values=factor_values,
        membership=context.membership,
        group_definitions=context.group_definitions,
        missing_factor_policy=settings["grouping"]["missing_factor_policy"],
        weight_values=context.weight_values,
    )

    factor_array = factor_values.to_numpy(dtype=float)
    valid_factor = np.isfinite(factor_array)
    stock_counts = valid_factor.sum(axis=1)
    enough_stocks = stock_counts >= settings["grouping"]["min_stocks"]
    if settings["insufficient_stocks_policy"] == "error" and (~enough_stocks).any():
        first_position = np.flatnonzero(~enough_stocks)[0]
        raise ValueError(
            f"有效因子股票数不足: {context.sample_dates[first_position].date()}"
        )

    if context.weight_values is None:
        base_weights = np.ones_like(factor_array)
    else:
        base_weights = context.weight_values.to_numpy(dtype=float)
    base_weights = np.where(group_membership.any(axis=0), base_weights, 0.0)

    future_matrices = _prepare_future_return_matrices(
        factor_array=factor_array,
        enough_stocks=enough_stocks,
        context=context,
    )

    horizon_count = len(context.horizon_values)
    date_count = len(context.sample_dates)
    stock_count = len(context.stock_codes)
    repeated_factors = np.broadcast_to(
        factor_array[None, :, :],
        (horizon_count, date_count, stock_count),
    ).reshape(horizon_count * date_count, stock_count)
    flattened_returns = future_matrices.future_returns.reshape(
        horizon_count * date_count,
        stock_count,
    )
    ic_values = rowwise_correlation(repeated_factors, flattened_returns).reshape(
        horizon_count,
        date_count,
    )
    rank_ic_values = rowwise_correlation(
        repeated_factors,
        flattened_returns,
        rank=True,
    ).reshape(
        horizon_count,
        date_count,
    )

    ic_status = np.full((horizon_count, date_count), "complete", dtype=object)
    ic_status[:, ~enough_stocks] = "insufficient_stocks"
    ic_status[~context.horizon_complete] = "horizon_incomplete"
    (
        group_sizes,
        group_returns,
        group_price_filled_counts,
        detail_status,
    ) = _calculate_group_return_matrices(
        group_membership=group_membership,
        group_weight_denominators=group_weight_denominators,
        base_weights=base_weights,
        enough_stocks=enough_stocks,
        future_matrices=future_matrices,
        context=context,
        settings=settings,
    )
    detail = _build_detail_table(
        context=context,
        stock_counts=stock_counts,
        group_sizes=group_sizes,
        group_returns=group_returns,
        group_price_filled_counts=group_price_filled_counts,
        detail_status=detail_status,
    )
    ic_series = _build_ic_table(
        context=context,
        stock_counts=stock_counts,
        completed_evaluations=future_matrices.completed_evaluations,
        combined_price_filled=future_matrices.combined_price_filled,
        valid_factor=valid_factor,
        ic_values=ic_values,
        rank_ic_values=rank_ic_values,
        ic_status=ic_status,
    )
    summary, ic_summary = summarize_evaluation(detail, ic_series, settings)
    return {
        "definitions": context.group_definitions.copy(),
        "detail": detail,
        "ic": ic_series,
        "summary": summary,
        "ic_summary": ic_summary,
        "factor_quality": _summarize_factor_quality(
            factor_values,
            context.membership,
        ),
        "sample_dates": context.sample_dates,
    }


def _summarize_factor_quality(
    factor_values: pd.DataFrame,
    membership: pd.DataFrame,
) -> pd.DataFrame:
    """汇总股票池内因子非空覆盖率和有效值零值率。"""
    membership_values = membership.to_numpy(dtype=bool)
    factor_array = factor_values.to_numpy(dtype=float)
    valid_factor = membership_values & np.isfinite(factor_array)
    universe_observation_count = membership_values.sum()
    valid_factor_count = valid_factor.sum()
    factor_coverage_rate = (
        valid_factor_count / universe_observation_count
        if universe_observation_count > 0
        else np.nan
    )
    factor_zero_rate = (
        (valid_factor & (factor_array == 0)).sum() / valid_factor_count
        if valid_factor_count > 0
        else np.nan
    )
    return pd.DataFrame(
        {
            "factor_coverage_rate": [factor_coverage_rate],
            "factor_zero_rate": [factor_zero_rate],
        }
    )


# 按日期、未来周期、分组顺序批量构造收益明细表。
def _build_detail_table(
    context: _EvaluationContext,
    stock_counts: np.ndarray,
    group_sizes: np.ndarray,
    group_returns: np.ndarray,
    group_price_filled_counts: np.ndarray,
    detail_status: np.ndarray,
) -> pd.DataFrame:
    """把评价矩阵展开为日期乘未来周期乘分组明细。"""
    date_count = len(context.sample_dates)
    horizon_count = len(context.horizon_values)
    group_count = len(context.group_definitions)
    detail_size = date_count * horizon_count * group_count
    definitions = context.group_definitions

    return pd.DataFrame(
        {
            "date": np.repeat(context.sample_dates.to_numpy(), horizon_count * group_count),
            "factor_date": np.repeat(
                context.factor_dates.to_numpy(),
                horizon_count * group_count,
            ),
            "return_end_date": np.repeat(
                context.return_end_dates.T.reshape(-1),
                group_count,
            ),
            "horizon_value": np.tile(
                np.repeat(context.horizon_values, group_count),
                date_count,
            ),
            "horizon_unit": np.tile(
                np.repeat(context.horizon_units, group_count),
                date_count,
            ),
            "n_stocks": np.repeat(stock_counts, horizon_count * group_count),
            "group_id": np.tile(definitions["group_id"].to_numpy(), date_count * horizon_count),
            "quantile_lower": np.tile(
                definitions["quantile_lower"].to_numpy(),
                date_count * horizon_count,
            ),
            "quantile_upper": np.tile(
                definitions["quantile_upper"].to_numpy(),
                date_count * horizon_count,
            ),
            "label": np.tile(definitions["label"].to_numpy(), date_count * horizon_count),
            "group_return": group_returns.transpose(2, 0, 1).reshape(detail_size),
            "n_group_stocks": np.broadcast_to(
                group_sizes.T[:, None, :],
                (date_count, horizon_count, group_count),
            ).reshape(detail_size),
            "n_group_price_filled": group_price_filled_counts.transpose(2, 0, 1).reshape(
                detail_size
            ),
            "status": detail_status.transpose(2, 0, 1).reshape(detail_size),
        }
    )


# 按日期和未来周期批量构造全截面 IC 序列表。
def _build_ic_table(
    context: _EvaluationContext,
    stock_counts: np.ndarray,
    completed_evaluations: np.ndarray,
    combined_price_filled: np.ndarray,
    valid_factor: np.ndarray,
    ic_values: np.ndarray,
    rank_ic_values: np.ndarray,
    ic_status: np.ndarray,
) -> pd.DataFrame:
    """把相关系数矩阵展开为日期乘未来周期序列。"""
    date_count = len(context.sample_dates)
    horizon_count = len(context.horizon_values)
    complete_stock_counts = np.where(
        completed_evaluations,
        stock_counts[None, :],
        0,
    )
    filled_counts = (
        combined_price_filled & valid_factor[None, :, :] & completed_evaluations[:, :, None]
    ).sum(axis=2)
    return pd.DataFrame(
        {
            "date": np.repeat(context.sample_dates.to_numpy(), horizon_count),
            "factor_date": np.repeat(context.factor_dates.to_numpy(), horizon_count),
            "return_end_date": context.return_end_dates.T.reshape(-1),
            "horizon_value": np.tile(context.horizon_values, date_count),
            "horizon_unit": np.tile(context.horizon_units, date_count),
            "n_stocks": np.repeat(stock_counts, horizon_count),
            "status": ic_status.T.reshape(-1),
            "ic": ic_values.T.reshape(-1),
            "rank_ic": rank_ic_values.T.reshape(-1),
            "n_returns": complete_stock_counts.T.reshape(-1),
            "n_price_filled": filled_counts.T.reshape(-1),
        }
    )


# 评价一个标准日频 Factor 面板。
def evaluate(
    factor_panel: pd.DataFrame,
    market_data: MarketData,
    settings: Mapping[str, Any],
    return_panel: pd.DataFrame | None = None,
) -> dict[str, pd.DataFrame | pd.DatetimeIndex]:
    """
    计算单因子的多未来周期分组收益和 IC。

    输入：
    - factor_panel：日期乘股票的标准 Factor 面板。
    - market_data：已经物化的市场数据对象。
    - settings：已经解析的 ``group_return`` 配置。
    - return_panel：可选的收盘到收盘日收益宽表。

    输出：
    - 返回分组定义、分组收益明细、IC、汇总、因子质量和采样日期。

    功能和用途：
    - 为单因子调用准备一次市场上下文并执行完整评价。
    """
    context = _prepare_context(market_data, settings, return_panel)
    return _evaluate_factor(factor_panel, context, settings)


# 共享市场上下文并在线程池中并行评价多个 Factor。
def evaluate_factors(
    factor_panels: Mapping[str, pd.DataFrame],
    market_data: MarketData,
    settings: Mapping[str, Any],
    max_workers: int | None = None,
    return_panel: pd.DataFrame | None = None,
) -> dict[str, dict[str, pd.DataFrame | pd.DatetimeIndex]]:
    """
    批量评价多个因子面板。

    输入：
    - factor_panels：因子名称到标准日频面板的映射。
    - market_data：所有任务共享的只读市场数据。
    - settings：整批任务共用的 ``group_return`` 配置。
    - max_workers：线程数；为空时使用线程池默认值，1 表示串行。
    - return_panel：可选的收盘到收盘日收益宽表。

    输出：
    - 返回保持输入顺序的因子名称到评价结果映射。

    功能和用途：
    - 市场日期、股票池、字段权重和参考价格只准备一次。
    - 线程共享大型面板，避免进程并行复制数据。
    """
    factor_items = list(factor_panels.items())
    completed_results = {
        factor_name: evaluation_result
        for factor_name, _, evaluation_result in iter_factor_evaluations(
            factor_items=factor_items,
            market_data=market_data,
            settings=settings,
            max_workers=max_workers,
            return_panel=return_panel,
        )
    }
    return {
        factor_name: completed_results[factor_name]
        for factor_name, _ in factor_items
    }


def iter_factor_evaluations(
    factor_items: Iterable[tuple[str, pd.DataFrame]],
    market_data: MarketData,
    settings: Mapping[str, Any],
    max_workers: int | None = None,
    return_panel: pd.DataFrame | None = None,
) -> Iterator[
    tuple[
        str,
        pd.DataFrame,
        dict[str, pd.DataFrame | pd.DatetimeIndex],
    ]
]:
    """共享一次市场上下文，按完成顺序产出有界数量的单因子评价结果。"""
    context = _prepare_context(market_data, settings, return_panel)
    factor_iterator = iter(factor_items)
    if max_workers == 1:
        for factor_name, factor_panel in factor_iterator:
            yield (
                factor_name,
                factor_panel,
                _evaluate_factor(factor_panel, context, settings),
            )
        return

    worker_count = max_workers or min(32, (os.cpu_count() or 1) + 4)
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        pending_futures: dict[Future, tuple[str, pd.DataFrame]] = {}
        for _ in range(worker_count):
            factor_item = next(factor_iterator, None)
            if factor_item is None:
                break
            factor_name, factor_panel = factor_item
            pending_futures[
                executor.submit(
                    _evaluate_factor,
                    factor_panel,
                    context,
                    settings,
                )
            ] = factor_item

        while pending_futures:
            completed_futures, _ = wait(
                pending_futures,
                return_when=FIRST_COMPLETED,
            )
            for completed_future in completed_futures:
                factor_name, factor_panel = pending_futures.pop(completed_future)
                evaluation_result = completed_future.result()
                next_factor_item = next(factor_iterator, None)
                if next_factor_item is not None:
                    next_factor_name, next_factor_panel = next_factor_item
                    pending_futures[
                        executor.submit(
                            _evaluate_factor,
                            next_factor_panel,
                            context,
                            settings,
                        )
                    ] = (next_factor_name, next_factor_panel)
                yield factor_name, factor_panel, evaluation_result
