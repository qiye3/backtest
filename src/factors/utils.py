"""
统一具体因子输出的交易日、股票列和研究股票池口径。

本模块位于单因子公式和批量引擎之间，只包含 ``align_factor_values``。函数接收具体
因子的原始二维面板、标准交易日历和动态成员面板，输出可直接交给评价与回测的因子
面板；本模块不实现具体因子公式，也不做填充、标准化或去极值。
"""

from __future__ import annotations

import pandas as pd


# 将原始因子值对齐到标准时间和股票范围，并清空非成员位置。
def align_factor_values(
    factor_values: pd.DataFrame,
    trading_calendar: pd.DatetimeIndex,
    membership: pd.DataFrame,
) -> pd.DataFrame:
    """
    生成符合下游输入口径的标准因子面板。

    输入：
    - factor_values：具体因子计算得到的日期乘股票面板。
    - trading_calendar：``MarketData.calendar`` 提供的标准交易日日历。
    - membership：``MarketData.membership`` 提供的日期乘股票布尔成员面板；其股票列
      定义最终输出列顺序。

    输出：
    - 返回索引严格等于 ``trading_calendar``、列严格等于 ``membership.columns`` 的
      DataFrame，股票不在当日研究池时对应值为缺失。

    功能和用途：
    - 统一不同因子可能返回的日期范围和股票列范围。
    - 只执行标签对齐和成员掩码，不填补原始缺失，也不改变有效因子数值。
    """
    aligned_values = factor_values.reindex(
        index=trading_calendar,
        columns=membership.columns,
    )
    return aligned_values.where(membership)
