"""
把日频因子面板转换为各调仓周期、各分位组的目标权重。

本模块负责调仓日程、股票池、因子滞后、字段加权和异常截面动作。
截面排名与分组复用 ``src.group_return.grouping`` 的矩阵化实现；账户状态、
成交和绩效指标不属于本模块。
"""

from __future__ import annotations

from collections.abc import Mapping
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
class TargetContext:
    """保存一批回测共享的股票池、分组和字段权重面板。"""

    calendar: pd.DatetimeIndex
    stock_codes: pd.Index
    membership: pd.DataFrame
    definitions: pd.DataFrame
    weight_panel: pd.DataFrame | None


def prepare_target_context(
    market_data: MarketData,
    settings: Mapping[str, Any],
) -> TargetContext:
    """
    准备批量构造目标权重所需的公共数据。

    输入：
    - market_data：已经对齐交易日和股票列的市场数据。
    - settings：单套 simple 或 account 回测配置。

    输出：
    - 返回可供全部因子和调仓周期只读共享的 ``TargetContext``。

    功能和用途：
    - 按配置合并多个指数的逐日历史成员。
    - 读取字段加权面板并建立稳定的分组定义。
    """
    calendar = market_data.calendar
    stock_codes = market_data.membership.columns
    membership = pd.DataFrame(False, index=calendar, columns=stock_codes)
    for index_code in settings["universe_indices"]:
        index_membership = market_data.get_panel(
            "index_membership",
            "membership",
            index_code=index_code,
        )
        membership |= index_membership.reindex(
            index=calendar,
            columns=stock_codes,
            fill_value=False,
        ).astype(bool)

    weighting = settings["grouping"]["weighting"]
    weight_panel = None
    if weighting["method"] == "field":
        weight_panel = market_data.get_panel(
            weighting["source"],
            weighting["field"],
        ).reindex(
            index=calendar,
            columns=stock_codes,
        )

    definitions = build_group_definitions(
        settings["grouping"]["quantile_edges"]
    )
    return TargetContext(
        calendar=calendar,
        stock_codes=stock_codes,
        membership=membership,
        definitions=definitions,
        weight_panel=weight_panel,
    )


def rebalance_dates(
    calendar: pd.DatetimeIndex,
    start: str,
    end: str,
    rebalance: Mapping[str, Any],
    interval: int,
    initial_entry: str,
) -> pd.DatetimeIndex:
    """
    按日度、固定锚定周或季度月内交易日规则构造真实调仓日。

    输入：交易日历、回测区间、调仓规则、对应频率下的间隔和首次建仓方式。
    输出：按时间升序排列的调仓交易日。

    日度模式从区间首个交易日起每隔 N 个交易日调仓；周度模式的节假日回退只允许
    落在目标日期所在自然周；
    ``initial_entry=start`` 会额外加入区间内第一个交易日。
    """
    start_date = pd.Timestamp(start)
    end_date = pd.Timestamp(end)
    available_dates = calendar[(calendar >= start_date) & (calendar <= end_date)]
    if available_dates.empty:
        raise ValueError("回测配置区间内没有交易日")

    frequency = rebalance["frequency"]
    if frequency == "daily":
        dates = pd.DatetimeIndex(available_dates[::interval], name="date")
    elif frequency == "weekly":
        dates = _weekly_rebalance_dates(
            calendar=calendar,
            start_date=start_date,
            end_date=end_date,
            rebalance=rebalance,
            interval=interval,
        )
    else:
        dates = _quarterly_rebalance_dates(
            available_dates=available_dates,
            rebalance=rebalance,
            interval=interval,
        )
    if initial_entry == "start":
        dates = pd.DatetimeIndex([available_dates[0]], name="date").union(dates)
    if dates.empty:
        raise ValueError("回测区间内没有调仓日")
    return dates


def _quarterly_rebalance_dates(
    available_dates: pd.DatetimeIndex,
    rebalance: Mapping[str, Any],
    interval: int,
) -> pd.DatetimeIndex:
    """选择配置月份的第 N 个交易日，并按季度序列应用间隔。"""
    configured_months = set(rebalance["months"])
    selected_dates = []
    calendar_frame = pd.DataFrame({"date": available_dates})
    calendar_frame["year"] = available_dates.year
    calendar_frame["month"] = available_dates.month
    eligible_months = calendar_frame.loc[
        calendar_frame["month"].isin(configured_months)
    ]
    for _, monthly_dates in eligible_months.groupby(
        ["year", "month"],
        sort=True,
    ):
        trading_day_position = rebalance["trading_day"] - 1
        if len(monthly_dates) > trading_day_position:
            selected_dates.append(
                monthly_dates.iloc[trading_day_position]["date"]
            )
    return pd.DatetimeIndex(selected_dates[::interval], name="date")


def _weekly_rebalance_dates(
    calendar: pd.DatetimeIndex,
    start_date: pd.Timestamp,
    end_date: pd.Timestamp,
    rebalance: Mapping[str, Any],
    interval: int,
) -> pd.DatetimeIndex:
    """根据锚定周、目标星期和节假日规则生成周度调仓日。"""
    anchor_monday = pd.Timestamp(rebalance["anchor_date"]).normalize()
    anchor_monday -= pd.Timedelta(days=anchor_monday.weekday())
    first_monday = start_date.normalize() - pd.Timedelta(days=start_date.weekday())

    selected_dates = []
    for week_start in pd.date_range(first_monday, end_date, freq="7D"):
        week_number = (week_start - anchor_monday).days // 7
        if week_number % interval:
            continue

        target_date = week_start + pd.Timedelta(
            days=WEEKDAY_NUMBER[rebalance["weekday"]]
        )
        if target_date > end_date:
            continue
        if target_date in calendar:
            selected_date = target_date
        elif rebalance["holiday_policy"] == "skip":
            continue
        else:
            earlier_dates = calendar[
                (calendar >= week_start) & (calendar < target_date)
            ]
            if earlier_dates.empty:
                continue
            selected_date = earlier_dates[-1]

        if start_date <= selected_date <= end_date:
            selected_dates.append(selected_date)
    return pd.DatetimeIndex(selected_dates, name="date")


def lagged_rows(
    panel: pd.DataFrame,
    calendar: pd.DatetimeIndex,
    dates: pd.DatetimeIndex,
    lag_days: int,
) -> tuple[pd.DataFrame, pd.DatetimeIndex]:
    """
    按交易日位置取得因子或字段权重的滞后截面。

    输入：完整日频面板、交易日历、目标日期和滞后交易日数。
    输出：以目标日期为索引的面板，以及实际读取的来源日期。
    """
    date_positions = calendar.get_indexer(dates)
    source_positions = date_positions - lag_days
    if (source_positions < 0).any():
        raise ValueError(
            "市场数据没有覆盖因子或权重字段所需的滞后历史"
        )

    source_dates = calendar[source_positions]
    selected_rows = panel.reindex(calendar).iloc[source_positions].copy()
    selected_rows.index = dates
    return selected_rows, source_dates


def build_targets(
    factor_panel: pd.DataFrame,
    context: TargetContext,
    settings: Mapping[str, Any],
    interval: int,
    collect_details: bool = True,
) -> dict[str, Any]:
    """
    矩阵化生成一个因子、一个调仓周期的全部分组目标。

    输入：标准日频因子面板、共享目标上下文、回测配置、调仓间隔和明细开关。
    输出：分组定义、动作、成员、各组目标权重和调仓日期。

    全 ``NaN`` 目标行表示保持真实旧持仓；全零行表示清仓变现金。
    """
    dates = rebalance_dates(
        calendar=context.calendar,
        start=settings["start"],
        end=settings["end"],
        rebalance=settings["rebalance"],
        interval=interval,
        initial_entry=settings["initial_entry"],
    )
    aligned_factor_panel = factor_panel.reindex(columns=context.stock_codes)
    factor_values, factor_dates = lagged_rows(
        panel=aligned_factor_panel,
        calendar=context.calendar,
        dates=dates,
        lag_days=settings["factor_lag_days"],
    )
    membership = context.membership.loc[dates]

    weight_values = None
    if context.weight_panel is not None:
        weight_values, _ = lagged_rows(
            panel=context.weight_panel,
            calendar=context.calendar,
            dates=dates,
            lag_days=settings["grouping"]["weighting"]["lag_days"],
        )

    (
        factor_values,
        factor_percentiles,
        group_membership,
        group_weight_denominators,
    ) = group_cross_sections(
        factor_values=factor_values,
        membership=membership,
        group_definitions=context.definitions,
        missing_factor_policy=settings["grouping"]["missing_factor_policy"],
        weight_values=weight_values,
    )

    factor_array = factor_values.to_numpy(dtype=float)
    valid_stock_counts = np.isfinite(factor_array).sum(axis=1)
    enough_stocks = valid_stock_counts >= settings["grouping"]["min_stocks"]
    if settings["insufficient_stocks_policy"] == "error" and (~enough_stocks).any():
        first_position = np.flatnonzero(~enough_stocks)[0]
        raise ValueError(f"有效因子股票数不足: {dates[first_position].date()}")

    base_weights = (
        np.ones_like(factor_array)
        if weight_values is None
        else weight_values.to_numpy(dtype=float)
    )
    # 区间外缺失字段先清零，否则 False * NaN 仍会污染目标矩阵。
    base_weights = np.where(
        group_membership.any(axis=0),
        base_weights,
        0.0,
    )
    target_values = np.divide(
        group_membership * base_weights[None, :, :],
        group_weight_denominators[:, :, None],
        out=np.zeros_like(group_membership, dtype=float),
        where=group_weight_denominators[:, :, None] > 0,
    )
    group_sizes = group_membership.sum(axis=2)
    empty_groups = (group_sizes == 0) & enough_stocks[None, :]
    if settings["empty_group_policy"] == "error" and empty_groups.any():
        group_position, date_position = np.argwhere(empty_groups)[0]
        group_id = context.definitions.iloc[group_position]["group_id"]
        raise ValueError(f"分组为空: {dates[date_position].date()} {group_id}")

    insufficient_groups = np.broadcast_to(~enough_stocks, group_sizes.shape)
    hold_groups = (
        insufficient_groups
        & (settings["insufficient_stocks_policy"] == "hold")
    ) | (empty_groups & (settings["empty_group_policy"] == "hold"))
    target_values[hold_groups] = np.nan

    actions = _build_actions(
        dates=dates,
        factor_dates=factor_dates,
        definitions=context.definitions,
        valid_stock_counts=valid_stock_counts,
        group_sizes=group_sizes,
        insufficient_groups=insufficient_groups,
        empty_groups=empty_groups,
        settings=settings,
    )
    members = pd.DataFrame()
    if collect_details:
        members = _build_members(
            dates=dates,
            factor_dates=factor_dates,
            stock_codes=context.stock_codes,
            definitions=context.definitions,
            factor_values=factor_values,
            factor_percentiles=factor_percentiles,
            group_membership=group_membership,
            target_values=target_values,
            enough_stocks=enough_stocks,
        )
    target_weights = {
        group_id: pd.DataFrame(
            target_values[group_position],
            index=dates,
            columns=context.stock_codes,
        )
        for group_position, group_id in enumerate(context.definitions["group_id"])
    }
    return {
        "definitions": context.definitions.copy(),
        "actions": actions,
        "members": members,
        "target_weights": target_weights,
        "rebalance_dates": dates,
    }


def _build_actions(
    dates: pd.DatetimeIndex,
    factor_dates: pd.DatetimeIndex,
    definitions: pd.DataFrame,
    valid_stock_counts: np.ndarray,
    group_sizes: np.ndarray,
    insufficient_groups: np.ndarray,
    empty_groups: np.ndarray,
    settings: Mapping[str, Any],
) -> pd.DataFrame:
    """把日期乘分组的目标状态矩阵展开为动作表。"""
    date_count = len(dates)
    group_count = len(definitions)
    actions = np.full((group_count, date_count), "rebalance", dtype=object)
    reasons = np.full((group_count, date_count), "", dtype=object)
    actions[insufficient_groups] = settings["insufficient_stocks_policy"]
    reasons[insufficient_groups] = "insufficient_stocks"
    actions[empty_groups] = settings["empty_group_policy"]
    reasons[empty_groups] = "empty_group"

    return pd.DataFrame(
        {
            "date": np.repeat(dates.to_numpy(), group_count),
            "factor_date": np.repeat(factor_dates.to_numpy(), group_count),
            "group_id": np.tile(definitions["group_id"].to_numpy(), date_count),
            "action": actions.T.reshape(-1),
            "reason": reasons.T.reshape(-1),
            "n_stocks": np.repeat(valid_stock_counts, group_count),
            "n_group_stocks": group_sizes.T.reshape(-1),
        }
    )


def _build_members(
    dates: pd.DatetimeIndex,
    factor_dates: pd.DatetimeIndex,
    stock_codes: pd.Index,
    definitions: pd.DataFrame,
    factor_values: pd.DataFrame,
    factor_percentiles: pd.DataFrame,
    group_membership: np.ndarray,
    target_values: np.ndarray,
    enough_stocks: np.ndarray,
) -> pd.DataFrame:
    """通过非零数组坐标批量构造有效调仓截面的成员明细。"""
    valid_membership = group_membership & enough_stocks[None, :, None]
    date_positions, group_positions, stock_positions = np.nonzero(
        valid_membership.transpose(1, 0, 2)
    )
    return pd.DataFrame(
        {
            "date": dates.to_numpy()[date_positions],
            "factor_date": factor_dates.to_numpy()[date_positions],
            "group_id": definitions["group_id"].to_numpy()[group_positions],
            "code": stock_codes.to_numpy()[stock_positions],
            "factor_value": factor_values.to_numpy()[
                date_positions,
                stock_positions,
            ],
            "percentile": factor_percentiles.to_numpy()[
                date_positions,
                stock_positions,
            ],
            "target_weight": target_values[
                group_positions,
                date_positions,
                stock_positions,
            ],
        }
    )
