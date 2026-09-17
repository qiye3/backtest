"""批量编排因子目标构造、分组组合回测和绩效指标计算。"""

from __future__ import annotations

from collections.abc import Iterable, Iterator, Mapping
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from dataclasses import dataclass
from itertools import repeat
from typing import Any

import pandas as pd

from src.backtest.account import _run_account_with_context
from src.backtest.metrics import calculate_metrics
from src.backtest.prices import PriceContext, prepare_price_context
from src.backtest.returns import ReturnContext, prepare_return_context
from src.backtest.simple import (
    _run_simple_returns_with_context,
    _run_simple_with_context,
)
from src.backtest.targets import (
    TargetContext,
    build_targets,
    prepare_target_context,
)
from src.data.market_data import MarketData


@dataclass(frozen=True)
class _BacktestContext:
    """保存一整批因子回测共享的目标、价格和曲线频率上下文。"""

    target: TargetContext
    simulation: PriceContext | ReturnContext
    need_daily: bool


def run_backtests(
    factor_panels: Mapping[str, pd.DataFrame],
    market_data: MarketData,
    settings: Mapping[str, Any],
    metrics_settings: Mapping[str, Any],
    mode: str,
    max_workers: int | None = None,
    return_panel: pd.DataFrame | None = None,
    collect_details: bool = True,
) -> dict[str, dict[str, Any]]:
    """
    批量运行一套 simple 或 account 回测配置。

    输入：
    - factor_panels：因子名称到标准日频面板的映射。
    - market_data：全部任务共享的只读市场数据。
    - settings、metrics_settings：已经解析的回测和指标配置。
    - mode：``simple`` 或 ``account``。
    - max_workers：1 表示串行，空值使用线程池默认并发数。
    - return_panel：可选的收盘到收盘日收益宽表，仅用于 simple。
    - collect_details：是否构造成交、持仓和分组成员明细。

    输出：
    - 返回按因子组织的分组定义、metrics，以及各周期的动作、成员、目标和
      分组结果。

    目标构造以因子乘周期为矩阵任务；账户模拟以因子乘周期乘分组为独立
    任务。两阶段都共享市场上下文，线程执行不会复制大型 DataFrame。
    """
    factor_items = list(factor_panels.items())
    completed_results = dict(
        iter_backtests(
            factor_items=factor_items,
            market_data=market_data,
            settings=settings,
            metrics_settings=metrics_settings,
            mode=mode,
            max_workers=max_workers,
            return_panel=return_panel,
            collect_details=collect_details,
        )
    )
    return {
        factor_name: completed_results[factor_name]
        for factor_name, _ in factor_items
    }


def iter_backtests(
    factor_items: Iterable[tuple[str, pd.DataFrame]],
    market_data: MarketData,
    settings: Mapping[str, Any],
    metrics_settings: Mapping[str, Any],
    mode: str,
    max_workers: int | None = None,
    return_panel: pd.DataFrame | None = None,
    collect_details: bool = True,
) -> Iterator[tuple[str, dict[str, Any]]]:
    """复用整阶段上下文和线程池，逐因子产出完整回测结果。"""
    context = _prepare_backtest_context(
        market_data=market_data,
        settings=settings,
        metrics_settings=metrics_settings,
        mode=mode,
        return_panel=return_panel,
    )
    if max_workers == 1:
        for factor_name, factor_panel in factor_items:
            yield factor_name, _run_factor_backtest(
                factor_name=factor_name,
                factor_panel=factor_panel,
                context=context,
                settings=settings,
                metrics_settings=metrics_settings,
                mode=mode,
                executor=None,
                collect_details=collect_details,
            )
        return

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        for factor_name, factor_panel in factor_items:
            yield factor_name, _run_factor_backtest(
                factor_name=factor_name,
                factor_panel=factor_panel,
                context=context,
                settings=settings,
                metrics_settings=metrics_settings,
                mode=mode,
                executor=executor,
                collect_details=collect_details,
            )


def _prepare_backtest_context(
    market_data: MarketData,
    settings: Mapping[str, Any],
    metrics_settings: Mapping[str, Any],
    mode: str,
    return_panel: pd.DataFrame | None,
) -> _BacktestContext:
    """校验一次模式并准备整批因子共享的目标和模拟上下文。"""
    _validate_mode_settings(settings, mode)
    if mode == "account" and return_panel is not None:
        raise ValueError("account backtest 不接受外部收益面板")
    if return_panel is not None and settings["trade_price"] != "close":
        raise ValueError("外部日收益回测要求 trade_price 为 close")

    target_context = prepare_target_context(market_data, settings)
    if mode == "simple" and return_panel is not None:
        simulation_context = prepare_return_context(
            return_panel,
            market_data,
            settings,
        )
    else:
        simulation_context = prepare_price_context(market_data, settings)
    need_daily = (
        settings["curve_frequency"] in {"daily", "both"}
        or metrics_settings["return_frequency"] == "daily"
    )
    return _BacktestContext(
        target=target_context,
        simulation=simulation_context,
        need_daily=need_daily,
    )


def _run_factor_backtest(
    factor_name: str,
    factor_panel: pd.DataFrame,
    context: _BacktestContext,
    settings: Mapping[str, Any],
    metrics_settings: Mapping[str, Any],
    mode: str,
    executor: ThreadPoolExecutor | None,
    collect_details: bool,
) -> dict[str, Any]:
    """使用共享上下文完成一个因子的全部周期和分组任务。"""
    target_tasks = [
        (factor_name, factor_panel, interval)
        for interval in settings["rebalance"]["intervals"]
    ]
    if executor is None:
        target_results = [
            _build_target_task(
                task,
                context.target,
                settings,
                collect_details,
            )
            for task in target_tasks
        ]
        group_results = [
            _run_group_task(
                task,
                context.simulation,
                settings,
                metrics_settings,
                mode,
                context.need_daily,
                collect_details,
            )
            for task in _group_tasks(target_results)
        ]
    else:
        target_results = list(
            executor.map(
                _build_target_task,
                target_tasks,
                repeat(context.target),
                repeat(settings),
                repeat(collect_details),
            )
        )
        group_results = list(
            executor.map(
                _run_group_task,
                _group_tasks(target_results),
                repeat(context.simulation),
                repeat(settings),
                repeat(metrics_settings),
                repeat(mode),
                repeat(context.need_daily),
                repeat(collect_details),
            )
        )
    return _assemble_results(
        factor_names=[factor_name],
        definitions=context.target.definitions,
        target_results=target_results,
        group_results=group_results,
        rebalance_frequency=settings["rebalance"]["frequency"],
    )[factor_name]


def run_weight_backtests(
    target_weights_by_interval: Mapping[int, pd.DataFrame],
    market_data: MarketData,
    settings: Mapping[str, Any],
    metrics_settings: Mapping[str, Any],
    mode: str,
    rebalance_frequency: str,
    max_workers: int | None = None,
    return_panel: pd.DataFrame | None = None,
    collect_details: bool = True,
) -> dict[str, Any]:
    """直接回测各调仓周期的目标权重，不再构造因子分组。"""
    return next(
        iter_weight_backtests(
            strategy_items=[
                (
                    "strategy",
                    target_weights_by_interval,
                    rebalance_frequency,
                )
            ],
            market_data=market_data,
            settings=settings,
            metrics_settings=metrics_settings,
            mode=mode,
            max_workers=max_workers,
            return_panel=return_panel,
            collect_details=collect_details,
        )
    )[1]


def iter_weight_backtests(
    strategy_items: Iterable[
        tuple[str, Mapping[int, pd.DataFrame], str]
    ],
    market_data: MarketData,
    settings: Mapping[str, Any],
    metrics_settings: Mapping[str, Any],
    mode: str,
    max_workers: int | None = None,
    return_panel: pd.DataFrame | None = None,
    collect_details: bool = True,
) -> Iterator[tuple[str, dict[str, Any]]]:
    """共享一次价格上下文和线程池，逐策略产出目标权重回测结果。"""
    _validate_mode_settings(settings, mode)
    if mode == "account" and return_panel is not None:
        raise ValueError("account backtest 不接受外部收益面板")
    if return_panel is not None and settings["trade_price"] != "close":
        raise ValueError("外部日收益回测要求 trade_price 为 close")

    if mode == "simple" and return_panel is not None:
        simulation_context = prepare_return_context(
            return_panel,
            market_data,
            settings,
        )
    else:
        simulation_context = prepare_price_context(market_data, settings)
    need_daily = (
        settings["curve_frequency"] in {"daily", "both"}
        or metrics_settings["return_frequency"] == "daily"
    )
    if max_workers == 1:
        for strategy_name, period_targets, rebalance_frequency in strategy_items:
            yield strategy_name, _run_weight_backtest_with_context(
                target_weights_by_interval=period_targets,
                simulation_context=simulation_context,
                settings=settings,
                metrics_settings=metrics_settings,
                mode=mode,
                rebalance_frequency=rebalance_frequency,
                need_daily=need_daily,
                executor=None,
                collect_details=collect_details,
            )
        return

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        for strategy_name, period_targets, rebalance_frequency in strategy_items:
            yield strategy_name, _run_weight_backtest_with_context(
                target_weights_by_interval=period_targets,
                simulation_context=simulation_context,
                settings=settings,
                metrics_settings=metrics_settings,
                mode=mode,
                rebalance_frequency=rebalance_frequency,
                need_daily=need_daily,
                executor=executor,
                collect_details=collect_details,
            )


def _run_weight_backtest_with_context(
    target_weights_by_interval: Mapping[int, pd.DataFrame],
    simulation_context: PriceContext | ReturnContext,
    settings: Mapping[str, Any],
    metrics_settings: Mapping[str, Any],
    mode: str,
    rebalance_frequency: str,
    need_daily: bool,
    executor: ThreadPoolExecutor | None,
    collect_details: bool,
) -> dict[str, Any]:
    """使用既有价格上下文完成一个策略的全部调仓周期。"""
    strategy_settings = deepcopy(settings)
    strategy_settings["rebalance"] = {"frequency": rebalance_frequency}
    simulation_tasks = [
        ("strategy", interval, "strategy", target_weights)
        for interval, target_weights in target_weights_by_interval.items()
    ]
    if executor is None:
        simulation_results = [
            _run_group_task(
                task,
                simulation_context,
                strategy_settings,
                metrics_settings,
                mode,
                need_daily,
                collect_details,
            )
            for task in simulation_tasks
        ]
    else:
        simulation_results = list(
            executor.map(
                _run_group_task,
                simulation_tasks,
                repeat(simulation_context),
                repeat(strategy_settings),
                repeat(metrics_settings),
                repeat(mode),
                repeat(need_daily),
                repeat(collect_details),
            )
        )

    metrics = []
    periods = {}
    for _, interval, group_id, group_result, metric_values in simulation_results:
        target_dates = target_weights_by_interval[interval].index
        periods[interval] = {
            "actions": pd.DataFrame(
                {
                    "date": target_dates,
                    "action": "rebalance",
                }
            ),
            "groups": {group_id: group_result},
        }
        metrics.append(
            {
                "group_id": group_id,
                "rebalance_frequency": rebalance_frequency,
                "rebalance_interval": interval,
                **metric_values,
            }
        )
    return {
        "definitions": pd.DataFrame(
            {"group_id": ["strategy"], "label": ["Strategy"]}
        ),
        "metrics": pd.DataFrame(metrics),
        "rebalance_frequency": rebalance_frequency,
        "periods": periods,
    }


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
    collect_details: bool,
) -> tuple[str, int, dict[str, Any]]:
    """构造一个因子和一个调仓周期的全部分组目标。"""
    factor_name, factor_panel, interval = task
    target_result = build_targets(
        factor_panel=factor_panel,
        context=target_context,
        settings=settings,
        interval=interval,
        collect_details=collect_details,
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
    simulation_context: PriceContext | ReturnContext,
    settings: Mapping[str, Any],
    metrics_settings: Mapping[str, Any],
    mode: str,
    need_daily: bool,
    collect_details: bool,
) -> tuple[str, int, str, dict[str, Any], dict[str, Any]]:
    """运行一个分组组合，优先单次生成费前费后曲线并计算指标。"""
    factor_name, interval, group_id, target_weights = task
    if isinstance(simulation_context, ReturnContext):
        runner = _run_simple_returns_with_context
    elif mode == "simple":
        runner = _run_simple_with_context
    else:
        runner = _run_account_with_context
    result = runner(
        target_weights,
        simulation_context,
        settings,
        need_daily,
        collect_details,
    )
    gross_curve_is_embedded = mode == "simple" or (
        mode == "account" and settings["execution"]["policy"] == "ideal"
    )
    if not gross_curve_is_embedded and settings["transaction_cost_rate"] == 0:
        _attach_gross_curves(result, result, mode)
    elif not gross_curve_is_embedded:
        gross_settings = deepcopy(settings)
        gross_settings["transaction_cost_rate"] = 0.0
        gross_result = runner(
            target_weights,
            simulation_context,
            gross_settings,
            need_daily,
            False,
        )
        _attach_gross_curves(result, gross_result, mode)

    metrics = {
        "mode": mode,
        "transaction_cost_rate": settings["transaction_cost_rate"],
        **calculate_metrics(
            result=result,
            mode=mode,
            metrics_settings=metrics_settings,
            rebalance_frequency=settings["rebalance"]["frequency"],
            rebalance_interval=interval,
        ),
    }
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
