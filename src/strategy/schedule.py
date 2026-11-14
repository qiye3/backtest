"""为日频 Strategy 生成日度、周度和季度的调仓日程。"""
from __future__ import annotations
from collections.abc import Mapping
from typing import Any
import pandas as pd

WEEKDAY_NUMBER = {"MON": 0, "TUE": 1, "WED": 2, "THU": 3, "FRI": 4}

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
    """按月内交易日或第二个星期五的下一交易日生成调整日期。"""
    configured_months = set(rebalance["months"])
    if rebalance.get("date_rule") == "second_friday_next_trading_day":
        return _second_friday_effective_dates(
            available_dates,
            configured_months,
            interval,
        )
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



def _second_friday_effective_dates(
    available_dates: pd.DatetimeIndex,
    configured_months: set[int],
    interval: int,
) -> pd.DatetimeIndex:
    """选择配置月份第二个星期五之后的首个交易日。"""
    selected_dates = []
    for year in range(available_dates.min().year, available_dates.max().year + 1):
        for month in sorted(configured_months):
            month_start = pd.Timestamp(year=year, month=month, day=1)
            month_end = month_start + pd.offsets.MonthEnd(1)
            fridays = pd.date_range(month_start, month_end, freq="W-FRI")
            if len(fridays) < 2:
                continue
            date_position = available_dates.searchsorted(fridays[1], side="right")
            if date_position < len(available_dates):
                effective_date = available_dates[date_position]
                if effective_date <= month_end + pd.Timedelta(days=7):
                    selected_dates.append(effective_date)
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

