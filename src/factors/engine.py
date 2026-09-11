"""
串行或线程并行计算一组已经实例化的 Factor。

本模块是 Factors 面向 pipeline 的批量计算入口。``calc_factors`` 接收 Factor 序列和
共享的只读 ``MarketData``，调度 ``Factor.calc`` 并统一对齐输出；
``_calc_factor_panel`` 是串行与线程执行共同使用的单任务函数。本模块不解析 YAML、
不构造因子类、不保存结果，也不捕获具体因子的计算异常。
"""

from __future__ import annotations

from collections.abc import Sequence
from concurrent.futures import ThreadPoolExecutor
from itertools import repeat

import pandas as pd

from src.data.market_data import MarketData
from src.factors.base import Factor
from src.factors.utils import align_factor_values


# 按输入顺序串行或线程并行计算多个因子面板。
def calc_factors(
    factors: Sequence[Factor],
    market_data: MarketData,
    max_workers: int = 1,
) -> dict[str, pd.DataFrame]:
    """
    批量计算已经完成配置加载的因子实例。

    输入：
    - factors：Factor 实例序列；调用方保证每个实例的 ``name`` 唯一。
    - market_data：所有任务共享的只读市场数据对象。
    - max_workers：并发线程数；默认1表示串行，大于1时启用线程池。

    输出：
    - 返回 ``{因子名称: 标准因子面板}`` 字典，键顺序与输入因子顺序一致。

    功能和用途：
    - 串行和并行模式使用同一单因子执行逻辑，输出口径完全一致。
    - 线程共享大型市场面板，避免进程并行复制 DataFrame；具体计算异常直接传播。
    """
    if max_workers == 1:
        factor_results = [
            _calc_factor_panel(factor, market_data)
            for factor in factors
        ]
    else:
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            factor_results = list(
                executor.map(
                    _calc_factor_panel,
                    factors,
                    repeat(market_data),
                )
            )
    return dict(factor_results)


# 计算单个因子并套用统一的日期、股票和成员口径。
def _calc_factor_panel(
    factor: Factor,
    market_data: MarketData,
) -> tuple[str, pd.DataFrame]:
    """
    执行一个批量计算任务。

    输入：
    - factor：已经保存完整配置的具体 Factor 实例。
    - market_data：批量任务共享的只读市场数据对象。

    输出：
    - 返回 ``(factor.name, 对齐后的因子面板)``，供批量入口直接构造结果字典。

    功能和用途：
    - 调用具体因子公式，再按照统一交易日历、股票列和动态成员资格整理结果。
    - 该函数同时作为串行任务单元和 ``ThreadPoolExecutor`` 的工作函数。
    """
    factor_values = factor.calc(market_data)
    aligned_values = align_factor_values(
        factor_values=factor_values,
        trading_calendar=market_data.calendar,
        membership=market_data.membership,
    )
    return factor.name, aligned_values
