"""统一目标权重、开收盘事件顺序和回测曲线视图。"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Literal

import numpy as np
import pandas as pd

from src.backtest.prices import PriceContext


def prepare_targets(
    target_weights: pd.DataFrame,
    context: PriceContext,
    settings: Mapping[str, Any],
) -> pd.DataFrame:
    """
    将内部或外部目标权重对齐到回测股票列并检查交易语义。

    普通目标必须有限、非负且总和不超过 1；只有整行 ``NaN`` 才表示
    hold。
    """
    targets = target_weights.copy()
    targets.index = pd.DatetimeIndex(targets.index)
    if targets.empty:
        raise ValueError("目标权重不能为空")
    if targets.index.has_duplicates or not targets.index.is_monotonic_increasing:
        raise ValueError("目标日期必须唯一且按时间升序排列")
    if targets.columns.has_duplicates:
        raise ValueError("目标股票代码不能重复")
    if not targets.index.isin(context.calendar).all():
        raise ValueError("目标日期不在市场交易日历中")
    if (
        targets.index.min() < pd.Timestamp(settings["start"])
        or targets.index.max() > pd.Timestamp(settings["end"])
    ):
        raise ValueError("目标日期超出回测区间")
    if set(targets.columns) - set(context.stock_codes):
        raise ValueError("目标权重包含未知股票代码")

    hold_rows = targets.isna().all(axis=1)
    targets = targets.reindex(
        columns=context.stock_codes,
        fill_value=0.0,
    ).astype(float)
    targets.loc[hold_rows] = np.nan
    active_targets = targets.loc[~hold_rows]
    partial_missing = active_targets.isna().any(axis=1)
    if partial_missing.any():
        raise ValueError("只有整行 NaN 可以表示 hold")
    if (active_targets < 0).any().any() or (
        active_targets.sum(axis=1) > 1 + 1e-8
    ).any():
        raise ValueError("目标权重必须非负且总和不超过 1")
    return targets


def event_plan(
    target_weights: pd.DataFrame,
    context: PriceContext,
    settings: Mapping[str, Any],
    need_daily: bool,
) -> list[tuple[int, Literal["open", "close"], bool, bool]]:
    """
    构造开盘成交、收盘估值和末日清算使用的有序事件。

    开盘调仓与当日收盘估值是两个独立事件；即使不需要每日曲线，
    调仓日和回测末日仍保留收盘事件。
    """
    target_positions = context.calendar.get_indexer(target_weights.index)
    target_position_set = set(target_positions)
    end_position = context.calendar.searchsorted(
        pd.Timestamp(settings["end"]),
        side="right",
    ) - 1
    first_position = target_positions[0]
    events = []
    for date_position in range(first_position, end_position + 1):
        is_rebalance = date_position in target_position_set
        is_terminal = date_position == end_position
        if is_rebalance and settings["trade_price"] == "open":
            events.append((date_position, "open", True, False))
        if need_daily or is_rebalance or is_terminal:
            close_rebalance = is_rebalance and settings["trade_price"] == "close"
            events.append(
                (date_position, "close", close_rebalance, is_terminal)
            )
    return events


def event_timestamp(
    date: pd.Timestamp,
    kind: Literal["open", "close"],
) -> pd.Timestamp:
    """把交易日和价格类型转换为稳定的日内事件时间戳。"""
    if kind == "open":
        return date + pd.Timedelta(hours=9, minutes=30)
    return date + pd.Timedelta(hours=15)


def make_curve_views(
    rows: list[dict[str, Any]],
    need_daily: bool,
) -> dict[str, pd.DataFrame]:
    """从完整事件记录构造 all、rebalance 和可选 daily 曲线。"""
    all_events = pd.DataFrame(rows)
    all_events["timestamp"] = pd.to_datetime(all_events["timestamp"])
    initial_event = all_events.loc[all_events["event"] == "initial"]
    valuation_events = all_events.loc[all_events["event"] != "initial"]
    rebalance_events = valuation_events.loc[
        valuation_events["is_rebalance"] | valuation_events["is_terminal"]
    ]
    curves = {
        "all": all_events,
        "rebalance": pd.concat(
            [initial_event, rebalance_events],
            ignore_index=True,
        ),
    }
    if need_daily:
        daily_events = valuation_events.loc[
            valuation_events["price_kind"] == "close"
        ].groupby("date", sort=False).tail(1)
        curves["daily"] = pd.concat(
            [initial_event, daily_events],
            ignore_index=True,
        )
    return curves
