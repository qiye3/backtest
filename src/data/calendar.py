"""
根据基准指数实际行情生成回测共享交易日日历。

本模块位于原始指数行情读取与各类日频面板构造之间，只包含
``build_trading_calendar``。输入是 ``load_data`` 已规范化的指数行情长表，输出是
目标区间内真实存在的交易日；本模块不人工生成工作日，也不处理调仓频率。
"""

from __future__ import annotations

import pandas as pd


# 从基准指数真实行情日期中建立所有数据面板共享的日历。
def build_trading_calendar(
    index_records: pd.DataFrame,
    benchmark_index: str,
    start_date: pd.Timestamp,
    end_date: pd.Timestamp,
) -> pd.DatetimeIndex:
    """
    构建指定回测区间的交易日日历。

    输入：
    - index_records：包含 ``date`` 和 ``asset_code`` 的指数行情长表。
    - benchmark_index：定义本次回测交易日的基准指数 Wind 代码。
    - start_date、end_date：需要保留的首尾日期，均按闭区间处理。

    输出：
    - 返回名称为 ``date``、升序且无重复值的 ``DatetimeIndex``。

    功能和用途：
    - 只采用基准指数确实存在行情的日期，不把自然工作日误当成交易日。
    - 股票停牌或单个数据源缺记录不会改变全局日历，缺失值由对应面板保留。
    - 基准指数在目标区间没有行情时直接报错，避免生成没有时间轴的数据缓存。
    """
    benchmark_dates = index_records.loc[
        index_records["asset_code"] == benchmark_index,
        "date",
    ]
    benchmark_dates = benchmark_dates[
        benchmark_dates.between(start_date, end_date)
    ]
    trading_calendar = pd.DatetimeIndex(
        benchmark_dates.dropna().drop_duplicates().sort_values(),
        name="date",
    )
    if trading_calendar.empty:
        raise ValueError(f"基准指数在配置区间没有行情: {benchmark_index}")
    return trading_calendar
