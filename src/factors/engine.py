"""
串行或线程并行计算一组已经实例化的 Factor。

本模块是 Factors 面向 pipeline 的批量计算入口。``calc_factors`` 接收 Factor 序列和
共享的只读 ``MarketData``，调度 ``Factor.calc`` 并统一对齐输出；
``_calc_factor_panel`` 是串行与线程执行共同使用的单任务函数。本模块不解析 YAML、
不构造因子类、不保存结果，也不捕获具体因子的计算异常。
"""

from __future__ import annotations

from collections.abc import Iterator, Sequence
from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait

import pandas as pd

from src.data.market_data import MarketData
from src.factors.base import Factor
from src.factors.utils import align_factor_values
from src.neutralization import demean_by_category, transform_cross_sections


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
    completed_panels = dict(
        iter_factor_panels(
            factors=factors,
            market_data=market_data,
            max_workers=max_workers,
        )
    )
    ordered_names = [
        output_name
        for factor in factors
        for output_name in _factor_output_names(factor)
    ]
    return {name: completed_panels[name] for name in ordered_names}


def _factor_output_names(factor: Factor) -> list[str]:
    """返回单个 YAML 按配置顺序产生的稳定输出名称。"""
    variants = factor.config.get("variants")
    if variants is None:
        return [factor.name]
    return [f"{factor.name}__{variant['suffix']}" for variant in variants]


def iter_factor_panels(
    factors: Sequence[Factor],
    market_data: MarketData,
    max_workers: int = 1,
) -> Iterator[tuple[str, pd.DataFrame]]:
    """按完成顺序产出因子面板，并将同时驻留的结果限制在线程数以内。"""
    if max_workers == 1:
        for factor in factors:
            yield from _calc_factor_panels(factor, market_data)
        return

    factor_iterator = iter(factors)
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        pending_futures: dict[Future, Factor] = {}
        for _ in range(max_workers):
            factor = next(factor_iterator, None)
            if factor is None:
                break
            pending_futures[
                executor.submit(_calc_factor_panels, factor, market_data)
            ] = factor

        while pending_futures:
            completed_futures, _ = wait(
                pending_futures,
                return_when=FIRST_COMPLETED,
            )
            for completed_future in completed_futures:
                pending_futures.pop(completed_future)
                factor_results = completed_future.result()
                next_factor = next(factor_iterator, None)
                if next_factor is not None:
                    pending_futures[
                        executor.submit(
                            _calc_factor_panels,
                            next_factor,
                            market_data,
                        )
                    ] = next_factor
                yield from factor_results


# 计算单个因子并套用统一的日期、股票和成员口径。
def _calc_factor_panels(
    factor: Factor,
    market_data: MarketData,
) -> list[tuple[str, pd.DataFrame]]:
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
    postprocess = factor.config.get("postprocess", {}).get("cross_section")
    variants = factor.config.get("variants")
    if postprocess is None and variants is None:
        return [(factor.name, aligned_values)]
    if postprocess is None or not variants:
        raise ValueError(f"{factor.name} 必须同时配置 postprocess 和 variants")

    transformed = transform_cross_sections(aligned_values, **postprocess)
    industry_panel = None
    output = []
    for variant in variants:
        suffix = variant["suffix"]
        neutralization = variant["neutralization"]
        method = neutralization["method"]
        if method == "none":
            variant_values = transformed.copy()
        elif method == "industry_demean":
            if industry_panel is None:
                industry_panel = market_data.get_panel(
                    neutralization["source"],
                    neutralization["field"],
                )
            variant_values = demean_by_category(
                transformed,
                industry_panel,
                market_data.membership,
            )
        else:
            raise ValueError(f"不支持的因子中性化方法: {method}")
        output.append(
            (f"{factor.name}__{suffix}", variant_values.astype("float32"))
        )
    return output
