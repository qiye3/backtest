"""批量编排因子目标构造、分组组合回测和绩效指标计算。"""

from __future__ import annotations

from collections.abc import Mapping
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from itertools import repeat
from typing import Any

import pandas as pd

from src.backtest.account import _run_account_with_context
from src.backtest.metrics import calculate_metrics
from src.backtest.prices import PriceContext, prepare_price_context
from src.backtest.simple import _run_simple_with_context
from src.backtest.targets import (
    TargetContext,
    build_targets,
    prepare_target_context,
)
from src.data.market_data import MarketData


def run_backtests(
    factor_panels: Mapping[str, pd.DataFrame],
    market_data: MarketData,
    settings: Mapping[str, Any],
    metrics_settings: Mapping[str, Any],
    mode: str,
    max_workers: int | None = None,
) -> dict[str, dict[str, Any]]:
    """
    批量运行一套 simple 或 account 回测配置。

    输入：
    - factor_panels：因子名称到标准日频面板的映射。
    - market_data：全部任务共享的只读市场数据。
    - settings、metrics_settings：已经解析的回测和指标配置。
    - mode：``simple`` 或 ``account``。
    - max_workers：1 表示串行，空值使用线程池默认并发数。

    输出：
    - 返回按因子组织的分组定义、metrics，以及各周期的动作、成员、目标和
      分组结果。

    目标构造以因子乘周期为矩阵任务；账户模拟以因子乘周期乘分组为独立
    任务。两阶段都共享市场上下文，线程执行不会复制大型 DataFrame。
    """
    _validate_mode_settings(settings, mode)
    target_context = prepare_target_context(market_data, settings)
    price_context = prepare_price_context(market_data, settings)
    need_daily = (
        settings["curve_frequency"] in {"daily", "both"}
        or metrics_settings["return_frequency"] == "daily"
    )

    factor_items = list(factor_panels.items())
    rebalance_intervals = settings["rebalance"]["intervals"]
    target_tasks = [
        (factor_name, factor_panel, interval)
        for factor_name, factor_panel in factor_items
        for interval in rebalance_intervals
    ]

    if max_workers == 1:
        target_results = [
            _build_target_task(task, target_context, settings)
            for task in target_tasks
        ]
        group_results = [
            _run_group_task(
                task,
                price_context,
                settings,
                metrics_settings,
                mode,
                need_daily,
            )
            for task in _group_tasks(target_results)
        ]
    else:
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            target_results = list(
                executor.map(
                    _build_target_task,
                    target_tasks,
                    repeat(target_context),
                    repeat(settings),
                )
            )
            group_results = list(
                executor.map(
                    _run_group_task,
                    _group_tasks(target_results),
                    repeat(price_context),
                    repeat(settings),
                    repeat(metrics_settings),
                    repeat(mode),
                    repeat(need_daily),
                )
            )
    return _assemble_results(
        factor_names=[factor_name for factor_name, _ in factor_items],
        definitions=target_context.definitions,
        target_results=target_results,
        group_results=group_results,
        rebalance_frequency=settings["rebalance"]["frequency"],
    )


def _validate_mode_settings(settings: Mapping[str, Any], mode: str) -> None:
    """检查决定引擎行为的模式约束。"""
    if mode not in {"simple", "account"}:
        raise ValueError(f"未知回测模式: {mode}")
    if mode == "simple" and settings["initial_capital"] != 1:
        raise ValueError("simple 回测的 initial_capital 必须为 1")
    if mode == "simple" and settings["execution"]["policy"] != "ideal":
        raise ValueError("simple 回测只支持 ideal execution")
    if mode == "account" and settings["initial_capital"] <= 0:
        raise ValueError("account 回测的 initial_capital 必须为正数")


def _build_target_task(
    task: tuple[str, pd.DataFrame, int],
    target_context: TargetContext,
    settings: Mapping[str, Any],
) -> tuple[str, int, dict[str, Any]]:
    """构造一个因子和一个调仓周期的全部分组目标。"""
    factor_name, factor_panel, interval = task
    target_result = build_targets(
        factor_panel=factor_panel,
        context=target_context,
        settings=settings,
        interval=interval,
    )
    return factor_name, interval, target_result


def _group_tasks(
    target_results: list[tuple[str, int, dict[str, Any]]],
) -> list[tuple[str, int, str, pd.DataFrame]]:
    """按因子、周期和分组的稳定顺序展开账户模拟任务。"""
    return [
        (
            factor_name,
            interval,
            group_id,
            target_result["target_weights"][group_id],
        )
        for factor_name, interval, target_result in target_results
        for group_id in target_result["definitions"]["group_id"]
    ]


def _run_group_task(
    task: tuple[str, int, str, pd.DataFrame],
    price_context: PriceContext,
    settings: Mapping[str, Any],
    metrics_settings: Mapping[str, Any],
    mode: str,
    need_daily: bool,
) -> tuple[str, int, str, dict[str, Any], dict[str, Any]]:
    """运行一个分组组合的费后和零费率对照，并计算指标。"""
    factor_name, interval, group_id, target_weights = task
    runner = (
        _run_simple_with_context
        if mode == "simple"
        else _run_account_with_context
    )
    result = runner(target_weights, price_context, settings, need_daily)
    if settings["transaction_cost_rate"] == 0:
        gross_result = result
    else:
        gross_settings = deepcopy(settings)
        gross_settings["transaction_cost_rate"] = 0.0
        gross_result = runner(
            target_weights,
            price_context,
            gross_settings,
            need_daily,
        )

    metrics = {
        "mode": mode,
        "transaction_cost_rate": settings["transaction_cost_rate"],
        **calculate_metrics(
            result=result,
            gross_result=gross_result,
            mode=mode,
            metrics_settings=metrics_settings,
            rebalance_frequency=settings["rebalance"]["frequency"],
            rebalance_interval=interval,
        ),
    }
    _attach_gross_curves(result, gross_result, mode)
    group_result = {
        "target_weights": target_weights,
        **result,
    }
    return factor_name, interval, group_id, group_result, metrics


def _attach_gross_curves(
    result: dict[str, Any],
    gross_result: Mapping[str, Any],
    mode: str,
) -> None:
    """把费前主曲线附到费后曲线，避免重复返回全部明细。"""
    net_column = "cumulative_return" if mode == "simple" else "nav"
    gross_column = "gross_cumulative_return" if mode == "simple" else "gross_nav"
    for frequency, curve in result["curves"].items():
        curve[gross_column] = gross_result["curves"][frequency][
            net_column
        ].to_numpy()


def _assemble_results(
    factor_names: list[str],
    definitions: pd.DataFrame,
    target_results: list[tuple[str, int, dict[str, Any]]],
    group_results: list[
        tuple[str, int, str, dict[str, Any], dict[str, Any]]
    ],
    rebalance_frequency: str,
) -> dict[str, dict[str, Any]]:
    """按因子和周期组装稳定的嵌套返回结构。"""
    results = {
        factor_name: {
            "definitions": definitions.copy(),
            "rebalance_frequency": rebalance_frequency,
            "metrics": [],
            "periods": {},
        }
        for factor_name in factor_names
    }
    for factor_name, interval, target_result in target_results:
        results[factor_name]["periods"][interval] = {
            "actions": target_result["actions"],
            "members": target_result["members"],
            "groups": {},
        }

    definition_by_group = definitions.set_index("group_id")
    for factor_name, interval, group_id, group_result, metrics in group_results:
        period_groups = results[factor_name]["periods"][interval]["groups"]
        period_groups[group_id] = group_result
        group_definition = definition_by_group.loc[group_id]
        metric_row = {
            "group_id": group_id,
            "quantile_lower": group_definition["quantile_lower"],
            "quantile_upper": group_definition["quantile_upper"],
            "label": group_definition["label"],
            "rebalance_frequency": rebalance_frequency,
            "rebalance_interval": interval,
            **metrics,
        }
        results[factor_name]["metrics"].append(metric_row)

    for factor_result in results.values():
        factor_result["metrics"] = pd.DataFrame(factor_result["metrics"])
    return results
