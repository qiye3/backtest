"""按照主 YAML 中的阶段开关运行批量因子评价和回测。"""

from __future__ import annotations

import argparse
import shutil
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas as pd
from tqdm.auto import tqdm

from src.backtest import run_backtests, run_weight_backtests
from src.backtest.io import (
    RESULT_FILE_NAMES,
    build_metrics_summary,
    load_backtest_checkpoint,
    load_backtest_checkpoint_summaries,
    load_backtest_result,
    save_backtest_checkpoints,
    save_backtest_results,
)
from src.config import RunConfig, load_config, save_config_snapshot
from src.data.market_data import MarketData
from src.data.return_data import load_return_panel
from src.factors import calc_factors, load_factors
from src.factors.io import (
    FACTOR_FILE_NAME,
    find_factor_names,
    load_factor_panel,
    load_factor_panels,
    save_factor_panels,
)
from src.group_return import evaluate_factors
from src.group_return.io import (
    FACTOR_SUMMARY_FILE_NAMES,
    load_evaluation_result,
    load_evaluation_results,
    load_factor_summaries,
    save_evaluation_results,
    save_factor_summaries,
)
from src.group_return.io import (
    RESULT_FILE_NAME as GROUP_RETURN_FILE_NAME,
)
from src.group_return.screening import (
    build_factor_screening_summary,
    build_frequency_summaries,
)
from src.overall_evaluation import evaluate_overall
from src.plotter import (
    plot_factor,
    plot_overall_evaluation,
    plot_strategy_backtest,
    plot_weight_deviation,
)
from src.strategy import (
    build_strategy_targets,
    calculate_weight_deviation,
    load_strategies,
)
from src.strategy.evaluation import summarize_weight_deviation
from src.strategy.io import (
    TARGET_FILE_NAME,
    find_strategy_names,
    load_strategy_targets,
    save_strategy_targets,
)

PIPELINE_CACHE_DIRECTORY = ".pipeline_cache"


@dataclass(frozen=True)
class RunSummary:
    """记录本次各阶段处理数量及最终输出路径，不持有计算结果。"""

    stage_counts: dict[str, int]
    output_paths: dict[str, tuple[Path, ...]]


class _CliProgress:
    """只为启用阶段维护一个 tqdm 命令行进度条。"""

    def __init__(self, config: RunConfig, enabled: bool) -> None:
        self._stage_names = _enabled_progress_stages(config)
        self._bar = tqdm(
            total=len(self._stage_names),
            desc="Factor backtest",
            unit="stage",
            disable=not enabled,
        )

    def __enter__(self) -> _CliProgress:
        return self

    def __exit__(self, *args: object) -> None:
        self._bar.close()

    def start(self, stage_name: str) -> None:
        """显示当前正在执行的阶段。"""
        if stage_name in self._stage_names:
            self._bar.set_postfix_str(stage_name, refresh=True)

    def complete(self, stage_name: str) -> None:
        """在一个启用阶段成功结束后推进进度。"""
        if stage_name in self._stage_names:
            self._bar.update()


def run(
    config: RunConfig,
    show_progress: bool = False,
) -> RunSummary:
    """按配置运行阶段，并只返回不含 DataFrame 的轻量摘要。"""
    with _CliProgress(config, show_progress) as progress:
        return _run_pipeline(config, progress)


def _run_pipeline(config: RunConfig, progress: _CliProgress) -> RunSummary:
    """以磁盘 checkpoint 隔离各阶段，并在成功后发布最终结果。"""
    cache_root = config.output_root / PIPELINE_CACHE_DIRECTORY
    _prepare_pipeline_cache(cache_root)
    save_config_snapshot(config, cache_root)

    run_settings = config.raw["run"]
    stage_counts: dict[str, int] = {}

    progress.start("market_data")
    market_data = _load_market_data(config)
    progress.complete("market_data")

    factor_source = config.output_root
    if run_settings["factors"]:
        progress.start("factors")
        factor_names = _calculate_factor_checkpoint(
            config,
            market_data,
            cache_root,
        )
        factor_source = cache_root
        stage_counts["factors"] = len(factor_names)
        progress.complete("factors")
    else:
        factor_names = find_factor_names(config.output_root)

    group_return_source = config.output_root
    if run_settings["group_return"]:
        progress.start("group_return")
        group_paths = _calculate_group_return_checkpoint(
            config,
            factor_source,
            market_data,
            cache_root,
        )
        group_return_source = cache_root
        stage_counts["group_return"] = len(group_paths)
        progress.complete("group_return")

    backtest_sources = {
        "simple": config.output_root,
        "account": config.output_root,
    }
    for mode in ["simple", "account"]:
        stage_name = f"{mode}_backtest"
        if not run_settings[stage_name]:
            continue
        progress.start(stage_name)
        backtest_paths = _calculate_backtest_checkpoint(
            config,
            factor_source,
            market_data,
            cache_root,
            mode,
        )
        backtest_sources[mode] = cache_root
        stage_counts[stage_name] = len(backtest_paths)
        progress.complete(stage_name)

    strategy_source = config.output_root
    if run_settings["strategies"]:
        progress.start("strategies")
        strategy_names = _calculate_strategy_target_checkpoints(
            config,
            factor_source,
            market_data,
            cache_root,
        )
        strategy_source = cache_root
        stage_counts["strategies"] = len(strategy_names)
        progress.complete("strategies")
    else:
        strategy_names = find_strategy_names(config.output_root)

    strategy_backtest_sources = {
        "simple": config.output_root,
        "account": config.output_root,
    }
    for mode in ["simple", "account"]:
        stage_name = f"strategy_{mode}_backtest"
        if not run_settings[stage_name]:
            continue
        progress.start(stage_name)
        strategy_paths = _calculate_strategy_backtest_checkpoints(
            config,
            strategy_names,
            strategy_source,
            market_data,
            cache_root,
            mode,
        )
        strategy_backtest_sources[mode] = cache_root
        stage_counts[stage_name] = len(strategy_paths)
        progress.complete(stage_name)

    _save_factor_summary_checkpoint(
        config,
        factor_names,
        cache_root,
    )
    _save_strategy_summary_checkpoint(
        config,
        strategy_names,
        strategy_source,
        strategy_backtest_sources,
        market_data,
        cache_root,
    )

    if run_settings["plotter"]:
        progress.start("plotter")
        _plot_factor_checkpoints(
            config,
            factor_names,
            factor_source,
            group_return_source,
            backtest_sources,
            cache_root,
        )
        _plot_strategy_checkpoints(
            config,
            strategy_names,
            strategy_source,
            strategy_backtest_sources,
            market_data,
            cache_root,
        )
        stage_counts["plotter"] = len(factor_names) + len(strategy_names)
        progress.complete("plotter")

    if run_settings["overall_evaluation"]:
        progress.start("overall_evaluation")
        _run_overall_evaluation(
            config,
            factor_source,
            group_return_source,
            market_data,
            cache_root,
        )
        stage_counts["overall_evaluation"] = len(factor_names)
        progress.complete("overall_evaluation")

    retained_root = _prepare_retained_checkpoints(
        config,
        factor_names,
        strategy_names,
        cache_root,
    )
    output_paths = _publish_successful_run(
        config,
        factor_names,
        strategy_names,
        cache_root,
        retained_root,
    )
    shutil.rmtree(cache_root)
    return RunSummary(stage_counts=stage_counts, output_paths=output_paths)


def _prepare_pipeline_cache(cache_root: Path) -> None:
    """清理上次失败留下的 checkpoint，并创建本次临时目录。"""
    if cache_root.exists():
        shutil.rmtree(cache_root)
    cache_root.mkdir(parents=True)


def _calculate_factor_checkpoint(
    config: RunConfig,
    market_data: MarketData,
    cache_root: Path,
) -> tuple[str, ...]:
    """计算全部因子并立即写入本次 checkpoint。"""
    factors = load_factors(config.factor_config_directory)
    factor_panels = calc_factors(
        factors=factors,
        market_data=market_data,
        max_workers=config.raw["run"]["max_workers"],
    )
    save_factor_panels(factor_panels, cache_root)
    return tuple(factor_panels)


def _calculate_group_return_checkpoint(
    config: RunConfig,
    factor_source: Path,
    market_data: MarketData,
    cache_root: Path,
) -> dict[str, Path]:
    """从磁盘加载因子，计算评价结果并立即写入 checkpoint。"""
    factor_panels = load_factor_panels(factor_source)
    return_panel = (
        load_return_panel(config.external_return_path)
        if config.external_return_path is not None
        else None
    )
    results = evaluate_factors(
        factor_panels=factor_panels,
        market_data=market_data,
        settings=config.raw["group_return"],
        max_workers=config.raw["run"]["max_workers"],
        return_panel=return_panel,
    )
    result_paths = save_evaluation_results(results, cache_root)
    screening_summary = build_factor_screening_summary(
        results,
        config.raw["group_return"],
    )
    save_factor_summaries(
        build_frequency_summaries(screening_summary, None),
        cache_root,
    )
    return result_paths


def _calculate_backtest_checkpoint(
    config: RunConfig,
    factor_source: Path,
    market_data: MarketData,
    cache_root: Path,
    mode: str,
) -> dict[str, Path]:
    """逐因子回测并保存 checkpoint，因子内部任务仍按线程数并行。"""
    factor_panels = load_factor_panels(factor_source)
    return_panel = (
        load_return_panel(config.external_return_path)
        if mode == "simple" and config.external_return_path is not None
        else None
    )
    section_name = f"{mode}_backtest"
    max_workers = config.raw["run"]["max_workers"]
    checkpoint_paths = {}
    for factor_name, factor_panel in factor_panels.items():
        factor_results = run_backtests(
            factor_panels={factor_name: factor_panel},
            market_data=market_data,
            settings=config.raw[section_name],
            metrics_settings=config.raw["metrics"],
            mode=mode,
            max_workers=max_workers,
            return_panel=return_panel,
        )
        checkpoint_paths.update(
            save_backtest_checkpoints(
                factor_results,
                cache_root,
                mode,
            )
        )
    return checkpoint_paths


def _calculate_strategy_target_checkpoints(
    config: RunConfig,
    factor_source: Path,
    market_data: MarketData,
    cache_root: Path,
) -> tuple[str, ...]:
    """逐策略读取 Factor、构建目标权重并立即落盘。"""
    strategies = load_strategies(config.strategy_config_directory)
    strategy_names = []
    for strategy in strategies:
        signal_panel = load_factor_panel(strategy.factor_name, factor_source)
        strategy_result = build_strategy_targets(
            strategy=strategy,
            signal_panel=signal_panel,
            market_data=market_data,
            settings=config.raw["strategies"],
        )
        save_strategy_targets(strategy_result, cache_root)
        strategy_names.append(strategy.name)
    return tuple(strategy_names)


def _calculate_strategy_backtest_checkpoints(
    config: RunConfig,
    strategy_names: Iterable[str],
    strategy_source: Path,
    market_data: MarketData,
    cache_root: Path,
    mode: str,
) -> dict[str, Path]:
    """逐策略运行目标权重回测，并立即保存内部 checkpoint。"""
    return_panel = (
        load_return_panel(config.external_return_path)
        if mode == "simple" and config.external_return_path is not None
        else None
    )
    settings = config.raw[f"{mode}_backtest"]
    checkpoint_paths = {}
    for strategy_name in strategy_names:
        target_result = load_strategy_targets(strategy_name, strategy_source)
        if target_result["benchmark_index"] != market_data.benchmark_index:
            raise ValueError(
                f"{strategy_name} benchmark_index 必须等于 "
                "market_data.benchmark_index"
            )
        period_targets = {
            interval: weights.loc[
                pd.Timestamp(settings["start"]):pd.Timestamp(settings["end"])
            ]
            for interval, weights in target_result["periods"].items()
        }
        backtest_result = run_weight_backtests(
            target_weights_by_interval=period_targets,
            market_data=market_data,
            settings=settings,
            metrics_settings=config.raw["metrics"],
            mode=mode,
            rebalance_frequency=target_result["rebalance_frequency"],
            max_workers=config.raw["run"]["max_workers"],
            return_panel=return_panel,
        )
        checkpoint_paths.update(
            save_backtest_checkpoints(
                {strategy_name: backtest_result},
                cache_root / "strategies",
                mode,
            )
        )
    return checkpoint_paths


def _save_factor_summary_checkpoint(
    config: RunConfig,
    factor_names: Iterable[str],
    cache_root: Path,
) -> dict[str, Path]:
    """用本次评价或 simple G10 回测结果更新各频率汇总表。"""
    group_return_completed = config.raw["run"]["group_return"]
    simple_backtest_completed = config.raw["run"]["simple_backtest"]
    if not group_return_completed and not simple_backtest_completed:
        return {}

    summary_root = cache_root if group_return_completed else config.output_root
    existing_summaries = load_factor_summaries(summary_root)
    backtest_summary = None
    if simple_backtest_completed:
        simple_results = load_backtest_checkpoint_summaries(
            factor_names,
            cache_root,
            "simple",
        )
        backtest_summary = build_metrics_summary(simple_results)
    factor_summaries = build_frequency_summaries(
        screening_summary=None,
        backtest_summary=backtest_summary,
        existing_summaries=existing_summaries,
    )
    return save_factor_summaries(factor_summaries, cache_root)


def _plot_factor_checkpoints(
    config: RunConfig,
    factor_names: Iterable[str],
    factor_source: Path,
    group_return_source: Path,
    backtest_sources: Mapping[str, Path],
    cache_root: Path,
) -> None:
    """逐因子加载计算结果并绘图，避免批量曲线同时驻留内存。"""
    for factor_name in factor_names:
        plot_factor(
            factor_name=factor_name,
            factor_panel=load_factor_panel(factor_name, factor_source),
            settings={**config.raw["plots"], "enabled": True},
            output_directory=cache_root / factor_name / "figures",
            group_return_result=load_evaluation_result(
                factor_name,
                group_return_source,
            ),
            simple_backtest_result=_load_backtest_for_plot(
                config,
                factor_name,
                backtest_sources["simple"],
                "simple",
            ),
            account_backtest_result=_load_backtest_for_plot(
                config,
                factor_name,
                backtest_sources["account"],
                "account",
            ),
            evaluation_settings=_evaluation_plot_settings(config),
            backtest_settings=_backtest_plot_settings(config),
        )


def _plot_strategy_checkpoints(
    config: RunConfig,
    strategy_names: Iterable[str],
    strategy_source: Path,
    backtest_sources: Mapping[str, Path],
    market_data: MarketData,
    cache_root: Path,
) -> None:
    """逐策略、逐调仓周期输出回测图和目标权重偏离图。"""
    if not config.raw["plots"]["strategy"]["enabled"]:
        return
    for strategy_name in strategy_names:
        target_result = load_strategy_targets(strategy_name, strategy_source)
        benchmark_weights = market_data.get_panel(
            "index_weights_monthly",
            "I_WEIGHT",
            index_code=target_result["benchmark_index"],
        )
        figure_directory = (
            cache_root / "strategies" / strategy_name / "figures"
        )
        for interval, target_weights in target_result["periods"].items():
            deviation = calculate_weight_deviation(
                target_weights,
                benchmark_weights,
            )
            interval_label = _strategy_interval_label(
                target_result["rebalance_frequency"],
                interval,
            )
            plot_weight_deviation(
                strategy_name=strategy_name,
                deviation=deviation,
                settings=config.raw["plots"],
                output_stem=figure_directory / f"deviation_{interval_label}",
                rebalance_label=interval_label,
            )
            for mode in ["simple", "account"]:
                backtest_result = _load_strategy_backtest_for_plot(
                    config,
                    strategy_name,
                    backtest_sources[mode],
                    mode,
                )
                if backtest_result is None:
                    continue
                plot_strategy_backtest(
                    strategy_name=strategy_name,
                    backtest_result=backtest_result,
                    mode=mode,
                    interval=interval,
                    settings=config.raw["plots"],
                    output_stem=(
                        figure_directory / f"{mode}_{interval_label}"
                    ),
                    backtest_settings=config.raw[f"{mode}_backtest"],
                    benchmark_index=target_result["benchmark_index"],
                )


def _load_strategy_backtest_for_plot(
    config: RunConfig,
    strategy_name: str,
    result_source: Path,
    mode: str,
) -> dict[str, Any] | None:
    """读取本次策略 checkpoint 或已发布的策略回测结果。"""
    if config.raw["run"][f"strategy_{mode}_backtest"]:
        return load_backtest_checkpoint(
            strategy_name,
            result_source / "strategies",
            mode,
        )
    return load_backtest_result(
        strategy_name,
        result_source / "strategies",
        mode,
    )


def _save_strategy_summary_checkpoint(
    config: RunConfig,
    strategy_names: Iterable[str],
    strategy_source: Path,
    backtest_sources: Mapping[str, Path],
    market_data: MarketData,
    cache_root: Path,
) -> tuple[Path, ...]:
    """生成每个调仓频率一张、每个策略一行的宽表。"""
    summaries: dict[tuple[str, int], list[dict[str, Any]]] = {}
    for strategy_name in strategy_names:
        target_result = load_strategy_targets(strategy_name, strategy_source)
        benchmark_weights = market_data.get_panel(
            "index_weights_monthly",
            "I_WEIGHT",
            index_code=target_result["benchmark_index"],
        )
        mode_results = {
            mode: _load_strategy_backtest_for_plot(
                config,
                strategy_name,
                backtest_sources[mode],
                mode,
            )
            for mode in ["simple", "account"]
        }
        for interval, target_weights in target_result["periods"].items():
            deviation = calculate_weight_deviation(
                target_weights,
                benchmark_weights,
            )
            summary_row = {
                "strategy_name": strategy_name,
                "factor_name": target_result["factor_name"],
                "benchmark_index": target_result["benchmark_index"],
                "rebalance_frequency": target_result["rebalance_frequency"],
                "rebalance_interval": interval,
                **summarize_weight_deviation(deviation),
            }
            for mode, mode_result in mode_results.items():
                if mode_result is not None:
                    summary_row.update(
                        _strategy_metric_columns(mode, mode_result, interval)
                    )
            summary_key = (target_result["rebalance_frequency"], interval)
            summaries.setdefault(summary_key, []).append(summary_row)

    output_paths = []
    for (frequency, interval), rows in summaries.items():
        interval_label = _strategy_interval_label(frequency, interval)
        output_path = cache_root / f"strategy_summary_{interval_label}.csv"
        pd.DataFrame(rows).to_csv(output_path, index=False)
        output_paths.append(output_path)
    return tuple(output_paths)


def _strategy_metric_columns(
    mode: str,
    result: Mapping[str, Any],
    interval: int,
) -> dict[str, Any]:
    """提取策略汇总表需要的一行 simple 或 account 指标。"""
    metric_row = result["metrics"].loc[
        result["metrics"]["rebalance_interval"] == interval
    ].iloc[0]
    metric_names = [
        "total_return",
        "annual_return",
        "sharpe",
        "max_drawdown",
        "annual_turnover",
        "benchmark_total_return",
        "excess_total_return",
        "tracking_error",
        "information_ratio",
    ]
    return {
        f"{mode}_{metric_name.replace('annual_turnover', 'turnover')}": (
            metric_row[metric_name]
        )
        for metric_name in metric_names
    }


def _strategy_interval_label(frequency: str, interval: int) -> str:
    """生成策略图和汇总文件使用的稳定调仓周期名称。"""
    suffixes = {"daily": "d", "weekly": "w", "quarterly": "q"}
    return f"{frequency}_{interval}{suffixes[frequency]}"


def _load_backtest_for_plot(
    config: RunConfig,
    factor_name: str,
    result_source: Path,
    mode: str,
) -> dict[str, Any] | None:
    """按本次阶段状态读取内部 checkpoint 或既有最终结果。"""
    if config.raw["run"][f"{mode}_backtest"]:
        return load_backtest_checkpoint(factor_name, result_source, mode)
    return load_backtest_result(factor_name, result_source, mode)


def _evaluation_plot_settings(config: RunConfig) -> dict[str, Any]:
    """补充评价图需要展示的收益来源。"""
    return {
        **config.raw["group_return"],
        "return_source": (
            "external_return"
            if config.external_return_path is not None
            else "market_price"
        ),
    }


def _backtest_plot_settings(
    config: RunConfig,
) -> dict[str, Mapping[str, Any]]:
    """补充两类回测图需要展示的收益来源。"""
    return {
        "simple": {
            **config.raw["simple_backtest"],
            "return_source": (
                "external_return"
                if config.external_return_path is not None
                else "market_price"
            ),
        },
        "account": config.raw["account_backtest"],
    }


def _run_overall_evaluation(
    config: RunConfig,
    factor_source: Path,
    group_return_source: Path,
    market_data: MarketData,
    cache_root: Path,
) -> None:
    """只为整体评价同时加载因子与评价结果，并输出到 checkpoint。"""
    factor_panels = load_factor_panels(factor_source)
    evaluation_results = load_evaluation_results(
        factor_panels,
        group_return_source,
    )
    overall_result = evaluate_overall(
        factor_panels=factor_panels,
        evaluation_results=evaluation_results,
        market_data=market_data,
        evaluation_settings=config.raw["group_return"],
        max_workers=config.raw["run"]["max_workers"],
    )
    plot_overall_evaluation(
        overall_result=overall_result,
        settings=config.raw["plots"],
        output_directory=cache_root / "00_overall",
    )


def _prepare_retained_checkpoints(
    config: RunConfig,
    factor_names: Iterable[str],
    strategy_names: Iterable[str],
    cache_root: Path,
) -> Path:
    """按最终明细开关在发布前生成可直接替换的 Parquet。"""
    retained_root = cache_root / ".retained"
    for mode in ["simple", "account"]:
        stage_name = f"{mode}_backtest"
        if not (
            config.raw["run"][stage_name]
            and config.raw["output"]["save_parquet"][stage_name]
        ):
            continue
        for factor_name in factor_names:
            result = load_backtest_checkpoint(
                factor_name,
                cache_root,
                mode,
            )
            save_backtest_results(
                {factor_name: result},
                retained_root,
                mode,
                save_details=config.raw["output"]["save_backtest_details"],
            )
    for mode in ["simple", "account"]:
        stage_name = f"strategy_{mode}_backtest"
        if not (
            config.raw["run"][stage_name]
            and config.raw["output"]["save_parquet"][stage_name]
        ):
            continue
        for strategy_name in strategy_names:
            result = load_backtest_checkpoint(
                strategy_name,
                cache_root / "strategies",
                mode,
            )
            save_backtest_results(
                {strategy_name: result},
                retained_root / "strategies",
                mode,
                save_details=config.raw["output"]["save_backtest_details"],
            )
    return retained_root


def _publish_successful_run(
    config: RunConfig,
    factor_names: Iterable[str],
    strategy_names: Iterable[str],
    cache_root: Path,
    retained_root: Path,
) -> dict[str, tuple[Path, ...]]:
    """原子替换本次成功结果，并执行各类 Parquet 保留策略。"""
    output_paths: dict[str, tuple[Path, ...]] = {}
    snapshot_path = _publish_file(
        cache_root / "config_snapshot.yaml",
        config.output_root / "config_snapshot.yaml",
    )
    output_paths["config"] = (snapshot_path,)

    factor_summary_paths = [
        cache_root / file_name
        for file_name in FACTOR_SUMMARY_FILE_NAMES.values()
        if (cache_root / file_name).exists()
    ]
    if factor_summary_paths:
        published_factor_summaries = tuple(
            _publish_file(
                factor_summary_path,
                config.output_root / factor_summary_path.name,
            )
            for factor_summary_path in factor_summary_paths
        )
        output_paths["factor_summary"] = published_factor_summaries
        for legacy_summary_name in [
            "metrics_summary.csv",
            "factor_screening_summary.csv",
            "factor_summary.csv",
        ]:
            (config.output_root / legacy_summary_name).unlink(missing_ok=True)

    strategy_summary_paths = sorted(cache_root.glob("strategy_summary_*.csv"))
    if strategy_summary_paths:
        output_paths["strategy_summary"] = tuple(
            _publish_file(
                summary_path,
                config.output_root / summary_path.name,
            )
            for summary_path in strategy_summary_paths
        )

    for stage_name, file_name in [
        ("factors", FACTOR_FILE_NAME),
        ("group_return", GROUP_RETURN_FILE_NAME),
        ("simple_backtest", RESULT_FILE_NAMES["simple"]),
        ("account_backtest", RESULT_FILE_NAMES["account"]),
    ]:
        if not config.raw["run"][stage_name]:
            continue
        retention_name = "factor" if stage_name == "factors" else stage_name
        if not config.raw["output"]["save_parquet"][retention_name]:
            _remove_factor_parquets(
                factor_names,
                config.output_root,
                file_name,
            )
            continue
        source_root = (
            retained_root
            if stage_name in {"simple_backtest", "account_backtest"}
            else cache_root
        )
        published = tuple(
            _publish_file(
                source_root / factor_name / file_name,
                config.output_root / factor_name / file_name,
            )
            for factor_name in factor_names
        )
        output_paths[stage_name] = published

    if config.raw["run"]["strategies"]:
        if config.raw["output"]["save_parquet"]["strategy_weights"]:
            output_paths["strategies"] = tuple(
                _publish_file(
                    cache_root
                    / "strategies"
                    / strategy_name
                    / TARGET_FILE_NAME,
                    config.output_root
                    / "strategies"
                    / strategy_name
                    / TARGET_FILE_NAME,
                )
                for strategy_name in strategy_names
            )
        else:
            for strategy_name in strategy_names:
                target_path = (
                    config.output_root
                    / "strategies"
                    / strategy_name
                    / TARGET_FILE_NAME
                )
                target_path.unlink(missing_ok=True)

    for mode in ["simple", "account"]:
        stage_name = f"strategy_{mode}_backtest"
        if not config.raw["run"][stage_name]:
            continue
        file_name = RESULT_FILE_NAMES[mode]
        if not config.raw["output"]["save_parquet"][stage_name]:
            for strategy_name in strategy_names:
                result_path = (
                    config.output_root
                    / "strategies"
                    / strategy_name
                    / file_name
                )
                result_path.unlink(missing_ok=True)
            continue
        output_paths[stage_name] = tuple(
            _publish_file(
                retained_root / "strategies" / strategy_name / file_name,
                config.output_root
                / "strategies"
                / strategy_name
                / file_name,
            )
            for strategy_name in strategy_names
        )

    if config.raw["run"]["plotter"]:
        output_paths["plotter"] = tuple(
            _publish_cached_tree(cache_root, config.output_root, "figures")
        )
    if config.raw["run"]["overall_evaluation"]:
        output_paths["overall_evaluation"] = tuple(
            _publish_cached_tree(cache_root, config.output_root, "00_overall")
        )
    return output_paths


def _publish_cached_tree(
    cache_root: Path,
    output_root: Path,
    directory_name: str,
) -> list[Path]:
    """发布 checkpoint 中指定目录下的全部文件。"""
    published_paths = []
    for source_path in sorted(cache_root.glob(f"**/{directory_name}/*")):
        if not source_path.is_file():
            continue
        relative_path = source_path.relative_to(cache_root)
        published_paths.append(
            _publish_file(source_path, output_root / relative_path)
        )
    return published_paths


def _publish_file(source_path: Path, output_path: Path) -> Path:
    """先复制到同目录临时文件，再原子替换最终文件。"""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = output_path.with_name(f".{output_path.name}.tmp")
    shutil.copy2(source_path, temporary_path)
    temporary_path.replace(output_path)
    return output_path


def _enabled_progress_stages(config: RunConfig) -> tuple[str, ...]:
    """按真实执行顺序列出 CLI 需要展示的阶段。"""
    run_settings = config.raw["run"]
    calculation_stages = {
        "factors",
        "group_return",
        "simple_backtest",
        "account_backtest",
        "strategies",
        "strategy_simple_backtest",
        "strategy_account_backtest",
        "overall_evaluation",
    }
    stages = []
    if any(run_settings[stage_name] for stage_name in calculation_stages):
        stages.append("market_data")
    stages.extend(
        stage_name
        for stage_name in [
            "factors",
            "group_return",
            "simple_backtest",
            "account_backtest",
            "strategies",
            "strategy_simple_backtest",
            "strategy_account_backtest",
            "plotter",
            "overall_evaluation",
        ]
        if run_settings[stage_name]
    )
    return tuple(stages)


def _load_market_data(config: RunConfig) -> MarketData | None:
    """在任一计算阶段启用时构建或复用共享市场数据。"""
    calculation_enabled = any(
        config.raw["run"][stage_name]
        for stage_name in [
            "factors",
            "group_return",
            "simple_backtest",
            "account_backtest",
            "strategies",
            "strategy_simple_backtest",
            "strategy_account_backtest",
            "overall_evaluation",
        ]
    )
    if not calculation_enabled:
        return None
    return MarketData.from_yaml(
        config.path,
        refresh=config.raw["run"]["refresh_market_data"],
    )


def _remove_factor_parquets(
    factor_names: Iterable[str],
    output_root: Path,
    file_name: str,
) -> None:
    """删除已启用阶段遗留的同类 Parquet，落实关闭保留开关。"""
    for factor_name in factor_names:
        (output_root / factor_name / file_name).unlink(missing_ok=True)


def main() -> None:
    """解析唯一的配置路径参数并报告各阶段处理数量。"""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--config",
        required=True,
        help="包含阶段开关和全部设置的主 YAML 路径",
    )
    arguments = parser.parse_args()
    config = load_config(arguments.config)
    summary = run(config, show_progress=True)
    for stage_name, count in summary.stage_counts.items():
        print(f"{stage_name}: {count} item(s)")


if __name__ == "__main__":
    main()
