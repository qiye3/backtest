"""
串行或线程并行计算一组已经实例化的 Factor。

本模块是 Factors 面向 pipeline 的批量计算入口。``calc_factors`` 接收 Factor 序列和
共享的只读 ``MarketData``，调度 ``Factor.calc`` 并统一对齐输出；
``_calc_factor_panel`` 是串行与线程执行共同使用的单任务函数。本模块不解析 YAML、
不构造因子类、不保存结果，也不捕获具体因子的计算异常。
"""

from __future__ import annotations

from collections.abc import Iterator, Mapping, Sequence
from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
from typing import Any

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
    domain_masks: Mapping[str, pd.DataFrame] | None = None,
    domain_factor_names: Sequence[str] = (),
    selected_variants: Sequence[str] | None = None,
) -> dict[str, pd.DataFrame]:
    """
    批量计算已经完成配置加载的因子实例。

    输入：
    - factors：Factor 实例序列；调用方保证每个实例的 ``name`` 唯一。
    - market_data：所有任务共享的只读市场数据对象。
    - max_workers：并发线程数；默认1表示串行，大于1时启用线程池。
    - domain_masks：域名到日频成员面板的映射；为空时不生成域 variants。
    - domain_factor_names：本次需要追加域 variants 的基础因子名称。
    - selected_variants：主配置选择的 raw 或 industry_neutral；为空时保留全部。

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
            domain_masks=domain_masks,
            domain_factor_names=domain_factor_names,
            selected_variants=selected_variants,
        )
    )
    selected_domain_factors = set(domain_factor_names)
    domain_names = tuple((domain_masks or {}).keys())
    ordered_names = [
        output_name
        for factor in factors
        for output_name in _factor_output_names(
            factor,
            domain_names if factor.name in selected_domain_factors else (),
            selected_variants,
        )
    ]
    return {name: completed_panels[name] for name in ordered_names}


def _factor_output_names(
    factor: Factor,
    domain_names: Sequence[str] = (),
    selected_variants: Sequence[str] | None = None,
) -> list[str]:
    """返回单个 YAML 按配置顺序产生的稳定输出名称。"""
    variants = _selected_factor_variants(factor, selected_variants)
    if factor.config.get("variants") is None:
        output_names = [factor.name]
    else:
        output_names = [
            f"{factor.name}__{variant['suffix']}"
            for variant in variants
        ]
    output_names.extend(
        f"{factor.name}__domain_{domain_name}"
        for domain_name in domain_names
    )
    return output_names


def _selected_factor_variants(
    factor: Factor,
    selected_variants: Sequence[str] | None,
) -> list[Mapping[str, Any]]:
    """按主配置筛选单个因子的 YAML variants，并明确拒绝缺失项。"""
    configured_variants = factor.config.get("variants")
    if configured_variants is None:
        if selected_variants is not None and set(selected_variants) != {"raw"}:
            raise ValueError(f"{factor.name} 没有 industry_neutral variant")
        return []
    if selected_variants is None:
        return list(configured_variants)

    selected_suffixes = set(selected_variants)
    available_suffixes = {variant["suffix"] for variant in configured_variants}
    missing_suffixes = selected_suffixes - available_suffixes
    if missing_suffixes:
        raise ValueError(
            f"{factor.name} 缺少 variants: {sorted(missing_suffixes)}"
        )
    return [
        variant
        for variant in configured_variants
        if variant["suffix"] in selected_suffixes
    ]


def iter_factor_panels(
    factors: Sequence[Factor],
    market_data: MarketData,
    max_workers: int = 1,
    domain_masks: Mapping[str, pd.DataFrame] | None = None,
    domain_factor_names: Sequence[str] = (),
    selected_variants: Sequence[str] | None = None,
) -> Iterator[tuple[str, pd.DataFrame]]:
    """按完成顺序产出全市场和选定域面板，并限制同时驻留的结果数量。"""
    resolved_domain_masks = domain_masks or {}
    selected_domain_factors = set(domain_factor_names)
    if max_workers == 1:
        for factor in factors:
            factor_results, domain_base = _calc_factor_panels(
                factor,
                market_data,
                factor.name in selected_domain_factors,
                selected_variants,
            )
            yield from _iter_factor_outputs(
                factor,
                factor_results,
                domain_base,
                resolved_domain_masks,
            )
        return

    factor_iterator = iter(factors)
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        pending_futures: dict[Future, Factor] = {}
        for _ in range(max_workers):
            factor = next(factor_iterator, None)
            if factor is None:
                break
            pending_futures[
                executor.submit(
                    _calc_factor_panels,
                    factor,
                    market_data,
                    factor.name in selected_domain_factors,
                    selected_variants,
                )
            ] = factor

        while pending_futures:
            completed_futures, _ = wait(
                pending_futures,
                return_when=FIRST_COMPLETED,
            )
            for completed_future in completed_futures:
                factor = pending_futures.pop(completed_future)
                factor_results = completed_future.result()
                next_factor = next(factor_iterator, None)
                if next_factor is not None:
                    pending_futures[
                        executor.submit(
                            _calc_factor_panels,
                            next_factor,
                            market_data,
                            next_factor.name in selected_domain_factors,
                            selected_variants,
                        )
                    ] = next_factor
                full_universe_results, domain_base = factor_results
                yield from _iter_factor_outputs(
                    factor,
                    full_universe_results,
                    domain_base,
                    resolved_domain_masks,
                )


# 计算单个因子并套用统一的日期、股票和成员口径。
def _calc_factor_panels(
    factor: Factor,
    market_data: MarketData,
    include_domain_base: bool = False,
    selected_variants: Sequence[str] | None = None,
) -> tuple[list[tuple[str, pd.DataFrame]], pd.DataFrame | None]:
    """
    执行一个批量计算任务。

    输入：
    - factor：已经保存完整配置的具体 Factor 实例。
    - market_data：批量任务共享的只读市场数据对象。

    输出：
    - 返回原有全市场 variants，以及供调用方逐个生成域 variants 的 raw 面板引用。

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
    configured_variants = factor.config.get("variants")
    variants = _selected_factor_variants(factor, selected_variants)
    if postprocess is None and configured_variants is None:
        return (
            [(factor.name, aligned_values)],
            aligned_values if include_domain_base else None,
        )
    if postprocess is None or not configured_variants:
        raise ValueError(f"{factor.name} 必须同时配置 postprocess 和 variants")

    transformed = transform_cross_sections(aligned_values, **postprocess)
    industry_panel = None
    output = []
    domain_base = None
    raw_variant_count = 0
    for variant in variants:
        suffix = variant["suffix"]
        neutralization = variant["neutralization"]
        method = neutralization["method"]
        if method == "none":
            variant_values = transformed.copy()
            raw_variant_count += 1
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
        output_values = variant_values.astype("float32")
        output.append((f"{factor.name}__{suffix}", output_values))
        if include_domain_base and method == "none":
            domain_base = output_values
    if include_domain_base:
        if raw_variant_count != 1:
            raise ValueError(f"{factor.name} 的 domain variants 需要唯一 raw variant")
    return output, domain_base


def _iter_factor_outputs(
    factor: Factor,
    full_universe_results: list[tuple[str, pd.DataFrame]],
    domain_base: pd.DataFrame | None,
    domain_masks: Mapping[str, pd.DataFrame],
) -> Iterator[tuple[str, pd.DataFrame]]:
    """先产出原有 variants，再从同一基础面板逐个生成同级域 variant。"""
    yield from full_universe_results
    if domain_base is None:
        return
    for domain_name, domain_mask in domain_masks.items():
        yield (
            f"{factor.name}__domain_{domain_name}",
            domain_base.where(domain_mask),
        )
