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

from src.analysis import evaluate_overall, save_overall_results
from src.backtest import iter_backtests, iter_weight_backtests
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
from src.data.style_exposure import load_or_build_style_exposures
from src.factors import iter_factor_panels, load_factors
from src.factors.domains import build_domain_masks
from src.factors.io import (
    FACTOR_FILE_NAME,
    find_factor_names,
    load_factor_panel,
    save_factor_panels,
)
from src.group_return import iter_factor_evaluations
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
from src.output_layout import (
    factor_output_root,
    strategy_output_root,
    summary_output_root,
)
from src.plotter import (
    plot_factor,
    plot_overall_evaluation,
    plot_strategy_backtest,
    plot_strategy_risk_exposure,
)
from src.strategy import (
    build_strategy_targets,
    calculate_concentration,
    calculate_industry_exposure,
    calculate_style_exposure,
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
    market_data: MarketData | None = None,
) -> RunSummary:
    """按配置运行阶段；批量编排可传入已构造的共享 MarketData。"""
    with _CliProgress(config, show_progress) as progress:
        return _run_pipeline(config, progress, market_data)


def _run_pipeline(
    config: RunConfig,
    progress: _CliProgress,
    shared_market_data: MarketData | None,
) -> RunSummary:
    """以磁盘 checkpoint 隔离各阶段，并在成功后发布最终结果。"""
    cache_root = config.output_root / PIPELINE_CACHE_DIRECTORY
    _prepare_pipeline_cache(cache_root)
    factor_cache_root = factor_output_root(cache_root)
    strategy_cache_root = strategy_output_root(cache_root)
    summary_cache_root = summary_output_root(cache_root)
    config_snapshot_path = save_config_snapshot(config, cache_root)
    _publish_file(
        config_snapshot_path,
        config.output_root / config_snapshot_path.name,
    )
    if config.factor_domains is not None:
        _publish_file(
            cache_root / "domain_config_snapshot.yaml",
            config.output_root / "domain_config_snapshot.yaml",
        )

    run_settings = config.raw["run"]
    stage_counts: dict[str, int] = {}

    progress.start("market_data")
    market_data = shared_market_data or _load_market_data(config)
    progress.complete("market_data")
    return_panel = _load_external_return_panel(config)

    factor_source = config.factor_result_root
    if run_settings["factors"]:
        progress.start("factors")
        factor_names = _calculate_factor_checkpoint(
            config,
            market_data,
            factor_cache_root,
        )
        factor_source = factor_cache_root
        stage_counts["factors"] = len(factor_names)
        progress.complete("factors")
    else:
        factor_names = find_factor_names(config.factor_result_root)

    published_factor_root = factor_output_root(config.output_root)
    published_strategy_root = strategy_output_root(config.output_root)
    group_return_source = published_factor_root
    if run_settings["group_return"]:
        progress.start("group_return")
        group_paths = _calculate_group_return_checkpoint(
            config,
            factor_names,
            factor_source,
            market_data,
            factor_cache_root,
            summary_cache_root,
            return_panel,
        )
        group_return_source = factor_cache_root
        stage_counts["group_return"] = len(group_paths)
        progress.complete("group_return")
        _publish_group_return_stage(
            config,
            factor_names,
            factor_cache_root,
            summary_cache_root,
        )

    if run_settings["overall_evaluation"]:
        progress.start("overall_evaluation")
        _run_overall_evaluation(
            config,
            factor_names,
            factor_source,
            group_return_source,
            market_data,
            cache_root,
        )
        stage_counts["overall_evaluation"] = len(factor_names)
        progress.complete("overall_evaluation")
        _publish_cached_tree(cache_root, config.output_root, "00_overall")

    backtest_sources = {
        "simple": published_factor_root,
        "account": published_factor_root,
    }
    for mode in ["simple", "account"]:
        stage_name = f"{mode}_backtest"
        if not run_settings[stage_name]:
            continue
        progress.start(stage_name)
        backtest_paths = _calculate_backtest_checkpoint(
            config,
            factor_names,
            factor_source,
            market_data,
            factor_cache_root,
            mode,
            return_panel,
        )
        backtest_sources[mode] = factor_cache_root
        stage_counts[stage_name] = len(backtest_paths)
        progress.complete(stage_name)
        _publish_factor_figure_stage(
            config=config,
            factor_names=factor_names,
            cache_root=factor_cache_root,
            figure_name=f"{'02_simple' if mode == 'simple' else '03_account'}_backtest",
        )
        if mode == "simple":
            _save_factor_summary_checkpoint(
                config,
                factor_names,
                factor_cache_root,
                summary_cache_root,
            )
            _publish_factor_summaries(config, summary_cache_root)

    strategy_source = published_strategy_root
    if run_settings["strategies"]:
        progress.start("strategies")
        strategy_names = _calculate_strategy_target_checkpoints(
            config,
            factor_source,
            market_data,
            strategy_cache_root,
        )
        strategy_source = strategy_cache_root
        stage_counts["strategies"] = len(strategy_names)
        progress.complete("strategies")
    else:
        strategy_names = find_strategy_names(published_strategy_root)

    if config.raw["strategy_analysis"]["enabled"]:
        _calculate_strategy_analysis_checkpoints(
            config=config,
            strategy_names=strategy_names,
            strategy_source=strategy_source,
            market_data=market_data,
            cache_root=strategy_cache_root,
        )
        _publish_strategy_figure_stage(
            config=config,
            strategy_names=strategy_names,
            cache_root=strategy_cache_root,
            figure_prefix="risk_exposure_",
        )

    strategy_backtest_sources = {
        "simple": published_strategy_root,
        "account": published_strategy_root,
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
            strategy_cache_root,
            mode,
            return_panel,
        )
        strategy_backtest_sources[mode] = strategy_cache_root
        stage_counts[stage_name] = len(strategy_paths)
        progress.complete(stage_name)
        _publish_strategy_figure_stage(
            config=config,
            strategy_names=strategy_names,
            cache_root=strategy_cache_root,
            figure_prefix=f"{mode}_",
        )

    _save_strategy_summary_checkpoint(
        config,
        strategy_names,
        strategy_source,
        strategy_backtest_sources,
        market_data,
        strategy_cache_root,
        summary_cache_root,
    )

    if run_settings["plotter"]:
        progress.start("plotter")
        remaining_factor_plots = _remaining_factor_plot_names(
            run_settings,
            config.raw["plots"],
        )
        if remaining_factor_plots:
            _plot_factor_checkpoints(
                config,
                factor_names,
                factor_source,
                group_return_source,
                backtest_sources,
                factor_cache_root,
                remaining_factor_plots,
            )
        remaining_strategy_plots = _remaining_strategy_plot_names(run_settings)
        if remaining_strategy_plots:
            _plot_strategy_checkpoints(
                config,
                strategy_names,
                strategy_source,
                strategy_backtest_sources,
                market_data,
                strategy_cache_root,
                remaining_strategy_plots,
            )
        stage_counts["plotter"] = len(factor_names) + len(strategy_names)
        progress.complete("plotter")

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


def _load_external_return_panel(config: RunConfig) -> pd.DataFrame | None:
    """一次读取本次评价和 simple 回测共享的外部日收益。"""
    if config.external_return_path is None:
        return None
    return_consumers = [
        "group_return",
        "simple_backtest",
        "strategy_simple_backtest",
    ]
    if not any(config.raw["run"][stage_name] for stage_name in return_consumers):
        return None
    return load_return_panel(config.external_return_path)


def _load_factor_items(
    factor_names: Iterable[str],
    factor_source: Path,
) -> Iterable[tuple[str, pd.DataFrame]]:
    """按需逐个读取因子面板，使在途内存由并发数而非因子总数决定。"""
    return (
        (factor_name, load_factor_panel(factor_name, factor_source)) for factor_name in factor_names
    )


def _remaining_factor_plot_names(
    run_settings: Mapping[str, Any],
    plot_settings: Mapping[str, Any],
) -> set[str]:
    """列出已启用且没有随计算阶段生成、需要补画的因子图。"""
    plot_names = set()
    if not run_settings["group_return"]:
        plot_names.update({"distribution", "evaluation"})
    if not run_settings["simple_backtest"]:
        plot_names.add("simple")
    if not run_settings["account_backtest"]:
        plot_names.add("account")
    return {plot_name for plot_name in plot_names if plot_settings[plot_name]["enabled"]}


def _remaining_strategy_plot_names(
    run_settings: Mapping[str, Any],
) -> set[str]:
    """列出没有随本次策略阶段生成、需要从既有结果补画的图。"""
    plot_names = set()
    if not run_settings["strategy_simple_backtest"]:
        plot_names.add("simple")
    if not run_settings["strategy_account_backtest"]:
        plot_names.add("account")
    return plot_names


def _publish_group_return_stage(
    config: RunConfig,
    factor_names: Iterable[str],
    factor_cache_root: Path,
    summary_cache_root: Path,
) -> None:
    """在评价阶段整体成功后立即发布汇总及分布、评价图。"""
    _publish_factor_summaries(config, summary_cache_root)
    if not config.raw["run"]["plotter"]:
        return
    for figure_name in ["00_factor_distribution", "01_evaluation"]:
        _publish_factor_figure_stage(
            config=config,
            factor_names=factor_names,
            cache_root=factor_cache_root,
            figure_name=figure_name,
        )


def _publish_factor_summaries(
    config: RunConfig,
    summary_cache_root: Path,
) -> None:
    """原子发布本次已经形成的各调仓频率因子汇总表。"""
    published_summary_root = summary_output_root(config.output_root)
    for file_name in FACTOR_SUMMARY_FILE_NAMES.values():
        source_path = summary_cache_root / file_name
        if source_path.exists():
            _publish_file(source_path, published_summary_root / file_name)


def _publish_factor_figure_stage(
    config: RunConfig,
    factor_names: Iterable[str],
    cache_root: Path,
    figure_name: str,
) -> None:
    """原子发布一个已完成计算阶段对应的单因子图。"""
    published_factor_root = factor_output_root(config.output_root)
    for factor_name in factor_names:
        for output_format in config.raw["plots"]["formats"]:
            relative_path = Path(factor_name) / "figures" / f"{figure_name}.{output_format}"
            source_path = cache_root / relative_path
            if source_path.exists():
                _publish_file(
                    source_path,
                    published_factor_root / relative_path,
                )


def _publish_strategy_figure_stage(
    config: RunConfig,
    strategy_names: Iterable[str],
    cache_root: Path,
    figure_prefix: str,
) -> None:
    """原子发布一个已完成策略阶段对应的全部调仓周期图。"""
    published_strategy_root = strategy_output_root(config.output_root)
    for strategy_name in strategy_names:
        figure_directory = cache_root / strategy_name / "figures"
        for output_format in config.raw["plots"]["formats"]:
            pattern = f"{figure_prefix}*.{output_format}"
            for source_path in sorted(figure_directory.glob(pattern)):
                relative_path = source_path.relative_to(cache_root)
                _publish_file(
                    source_path,
                    published_strategy_root / relative_path,
                )


def _calculate_factor_checkpoint(
    config: RunConfig,
    market_data: MarketData,
    cache_root: Path,
) -> tuple[str, ...]:
    """有界并行计算因子，并在单个结果完成后立即写入 checkpoint。"""
    factors = load_factors(config.factor_config_directory)
    domain_masks = None
    domain_factor_names: tuple[str, ...] = ()
    if config.factor_domains is not None:
        loaded_factor_names = {factor.name for factor in factors}
        missing_factor_names = (
            set(config.factor_domains.factor_names) - loaded_factor_names
        )
        if missing_factor_names:
            raise ValueError(
                "domain factor_names 不在本次 Factor 配置中: "
                f"{sorted(missing_factor_names)}"
            )
        domain_masks = build_domain_masks(
            config.factor_domains.domains,
            market_data,
        )
        domain_factor_names = config.factor_domains.factor_names
    output_names = []
    for factor_name, factor_panel in iter_factor_panels(
        factors=factors,
        market_data=market_data,
        max_workers=config.raw["run"]["max_workers"],
        domain_masks=domain_masks,
        domain_factor_names=domain_factor_names,
    ):
        save_factor_panels({factor_name: factor_panel}, cache_root)
        output_names.append(factor_name)
    return tuple(output_names)


def _calculate_group_return_checkpoint(
    config: RunConfig,
    factor_names: Iterable[str],
    factor_source: Path,
    market_data: MarketData,
    factor_cache_root: Path,
    summary_cache_root: Path,
    return_panel: pd.DataFrame | None,
) -> dict[str, Path]:
    """逐因子评价、保存和绘图，仅累计轻量筛选汇总。"""
    factor_items = _load_factor_items(factor_names, factor_source)
    result_paths = {}
    screening_summaries = []
    for factor_name, factor_panel, evaluation_result in iter_factor_evaluations(
        factor_items=factor_items,
        market_data=market_data,
        settings=config.raw["group_return"],
        max_workers=config.raw["run"]["max_workers"],
        return_panel=return_panel,
    ):
        result_paths.update(
            save_evaluation_results(
                {factor_name: evaluation_result},
                factor_cache_root,
            )
        )
        screening_summaries.append(
            build_factor_screening_summary(
                {factor_name: evaluation_result},
                config.raw["group_return"],
            )
        )
        if config.raw["run"]["plotter"]:
            plot_factor(
                factor_name=factor_name,
                factor_panel=factor_panel,
                settings={**config.raw["plots"], "enabled": True},
                output_directory=factor_cache_root / factor_name / "figures",
                group_return_result=evaluation_result,
                evaluation_settings=_evaluation_plot_settings(config),
                plot_names={"distribution", "evaluation"},
            )

    screening_summary = pd.concat(screening_summaries, ignore_index=True)
    save_factor_summaries(
        build_frequency_summaries(screening_summary, None),
        summary_cache_root,
    )
    return result_paths


def _calculate_backtest_checkpoint(
    config: RunConfig,
    factor_names: Iterable[str],
    factor_source: Path,
    market_data: MarketData,
    cache_root: Path,
    mode: str,
    return_panel: pd.DataFrame | None,
) -> dict[str, Path]:
    """复用整阶段回测上下文，逐因子保存结果并绘制当前模式。"""
    section_name = f"{mode}_backtest"
    max_workers = config.raw["run"]["max_workers"]
    checkpoint_paths = {}
    factor_items = _load_factor_items(factor_names, factor_source)
    stage_return_panel = return_panel if mode == "simple" else None
    for factor_name, backtest_result in iter_backtests(
        factor_items=factor_items,
        market_data=market_data,
        settings=config.raw[section_name],
        metrics_settings=config.raw["metrics"],
        mode=mode,
        max_workers=max_workers,
        return_panel=stage_return_panel,
        collect_details=config.raw["output"]["save_backtest_details"],
    ):
        checkpoint_paths.update(
            save_backtest_checkpoints(
                {factor_name: backtest_result},
                cache_root,
                mode,
            )
        )
        if config.raw["run"]["plotter"]:
            plot_factor(
                factor_name=factor_name,
                factor_panel=None,
                settings={**config.raw["plots"], "enabled": True},
                output_directory=cache_root / factor_name / "figures",
                simple_backtest_result=(backtest_result if mode == "simple" else None),
                account_backtest_result=(backtest_result if mode == "account" else None),
                backtest_settings=_backtest_plot_settings(config),
                plot_names={mode},
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


def _calculate_strategy_analysis_checkpoints(
    config: RunConfig,
    strategy_names: Iterable[str],
    strategy_source: Path,
    market_data: MarketData,
    cache_root: Path,
) -> None:
    """复用全周期风格缓存并保存各策略风险暴露明细。"""
    style_exposures = load_or_build_style_exposures(
        market_data,
        refresh=config.raw["run"]["refresh_market_data"],
    )
    industry_panel = market_data.get_panel(
        "industry_history",
        "ind_class_code",
    )
    benchmark_weights_by_index: dict[str, pd.DataFrame] = {}
    for strategy_name in strategy_names:
        strategy_result = load_strategy_targets(strategy_name, strategy_source)
        benchmark_index = strategy_result["benchmark_index"]
        if benchmark_index not in benchmark_weights_by_index:
            benchmark_weights_by_index[benchmark_index] = market_data.get_panel(
                "index_weights_monthly",
                "I_WEIGHT",
                index_code=benchmark_index,
            )
        benchmark_weights = benchmark_weights_by_index[benchmark_index]
        for interval, target_weights in strategy_result["periods"].items():
            interval_label = _strategy_interval_label(
                strategy_result["rebalance_frequency"],
                interval,
            )
            concentration = calculate_concentration(
                target_weights,
                benchmark_weights,
            )
            industry_exposure = calculate_industry_exposure(
                target_weights,
                benchmark_weights,
                industry_panel,
            )
            style_exposure = calculate_style_exposure(
                target_weights,
                benchmark_weights,
                style_exposures,
                minimum_coverage=config.raw["strategy_analysis"]["minimum_style_coverage"],
            )
            analysis_directory = cache_root / strategy_name / "analysis"
            analysis_directory.mkdir(parents=True, exist_ok=True)
            concentration.to_parquet(
                analysis_directory / f"concentration_{interval_label}.parquet",
                index=False,
            )
            industry_exposure.to_parquet(
                analysis_directory / f"industry_exposure_{interval_label}.parquet",
                index=False,
            )
            style_exposure.to_parquet(
                analysis_directory / f"style_exposure_{interval_label}.parquet",
                index=False,
            )
            if config.raw["run"]["plotter"] and config.raw["plots"]["strategy"]["enabled"]:
                plot_strategy_risk_exposure(
                    strategy_name=strategy_name,
                    concentration=concentration,
                    industry_exposure=industry_exposure,
                    style_exposure=style_exposure,
                    settings=config.raw["plots"],
                    output_stem=(
                        cache_root / strategy_name / "figures" / f"risk_exposure_{interval_label}"
                    ),
                    rebalance_label=interval_label,
                )


def _calculate_strategy_backtest_checkpoints(
    config: RunConfig,
    strategy_names: Iterable[str],
    strategy_source: Path,
    market_data: MarketData,
    cache_root: Path,
    mode: str,
    return_panel: pd.DataFrame | None,
) -> dict[str, Path]:
    """复用整阶段价格上下文，逐策略运行并保存目标权重回测。"""
    settings = config.raw[f"{mode}_backtest"]
    checkpoint_paths = {}
    strategy_items = _load_strategy_backtest_items(
        strategy_names=strategy_names,
        strategy_source=strategy_source,
        market_data=market_data,
        settings=settings,
    )
    for strategy_name, backtest_result in iter_weight_backtests(
        strategy_items=strategy_items,
        market_data=market_data,
        settings=settings,
        metrics_settings=config.raw["metrics"],
        mode=mode,
        max_workers=config.raw["run"]["max_workers"],
        return_panel=return_panel if mode == "simple" else None,
        collect_details=config.raw["output"]["save_backtest_details"],
    ):
        checkpoint_paths.update(
            save_backtest_checkpoints(
                {strategy_name: backtest_result},
                cache_root,
                mode,
            )
        )
        if config.raw["run"]["plotter"] and config.raw["plots"]["strategy"]["enabled"]:
            target_result = load_strategy_targets(
                strategy_name,
                strategy_source,
            )
            _plot_strategy_backtest_result(
                strategy_name=strategy_name,
                target_result=target_result,
                backtest_result=backtest_result,
                mode=mode,
                settings=config.raw["plots"],
                backtest_settings=settings,
                cache_root=cache_root,
            )
    return checkpoint_paths


def _load_strategy_backtest_items(
    strategy_names: Iterable[str],
    strategy_source: Path,
    market_data: MarketData,
    settings: Mapping[str, Any],
) -> Iterable[tuple[str, Mapping[int, pd.DataFrame], str]]:
    """逐策略读取并裁剪目标权重，供共享上下文的回测迭代器消费。"""
    for strategy_name in strategy_names:
        target_result = load_strategy_targets(strategy_name, strategy_source)
        if target_result["benchmark_index"] != market_data.benchmark_index:
            raise ValueError(
                f"{strategy_name} benchmark_index 必须等于 market_data.benchmark_index"
            )
        period_targets = {
            interval: weights.loc[pd.Timestamp(settings["start"]) : pd.Timestamp(settings["end"])]
            for interval, weights in target_result["periods"].items()
        }
        yield (
            strategy_name,
            period_targets,
            target_result["rebalance_frequency"],
        )


def _save_factor_summary_checkpoint(
    config: RunConfig,
    factor_names: Iterable[str],
    factor_cache_root: Path,
    summary_cache_root: Path,
) -> dict[str, Path]:
    """用本次评价或 simple G10 回测结果更新各频率汇总表。"""
    group_return_completed = config.raw["run"]["group_return"]
    simple_backtest_completed = config.raw["run"]["simple_backtest"]
    if not group_return_completed and not simple_backtest_completed:
        return {}

    summary_root = (
        summary_cache_root if group_return_completed else summary_output_root(config.output_root)
    )
    existing_summaries = load_factor_summaries(summary_root)
    backtest_summary = None
    if simple_backtest_completed:
        simple_results = load_backtest_checkpoint_summaries(
            factor_names,
            factor_cache_root,
            "simple",
        )
        backtest_summary = build_metrics_summary(simple_results)
    factor_summaries = build_frequency_summaries(
        screening_summary=None,
        backtest_summary=backtest_summary,
        existing_summaries=existing_summaries,
    )
    return save_factor_summaries(factor_summaries, summary_cache_root)


def _plot_factor_checkpoints(
    config: RunConfig,
    factor_names: Iterable[str],
    factor_source: Path,
    group_return_source: Path,
    backtest_sources: Mapping[str, Path],
    cache_root: Path,
    plot_names: Iterable[str],
) -> None:
    """逐因子加载既有结果，只补画尚未随计算阶段生成的图。"""
    requested_plots = set(plot_names)
    if not requested_plots:
        return
    for factor_name in factor_names:
        plot_factor(
            factor_name=factor_name,
            factor_panel=(
                load_factor_panel(factor_name, factor_source)
                if "distribution" in requested_plots
                else None
            ),
            settings={**config.raw["plots"], "enabled": True},
            output_directory=cache_root / factor_name / "figures",
            group_return_result=(
                load_evaluation_result(factor_name, group_return_source)
                if "evaluation" in requested_plots
                else None
            ),
            simple_backtest_result=(
                _load_backtest_for_plot(
                    config,
                    factor_name,
                    backtest_sources["simple"],
                    "simple",
                )
                if "simple" in requested_plots
                else None
            ),
            account_backtest_result=(
                _load_backtest_for_plot(
                    config,
                    factor_name,
                    backtest_sources["account"],
                    "account",
                )
                if "account" in requested_plots
                else None
            ),
            evaluation_settings=(
                _evaluation_plot_settings(config)
                if "sampling" in config.raw["group_return"]
                else None
            ),
            backtest_settings=_backtest_plot_settings(config),
            plot_names=requested_plots,
        )


def _plot_strategy_checkpoints(
    config: RunConfig,
    strategy_names: Iterable[str],
    strategy_source: Path,
    backtest_sources: Mapping[str, Path],
    market_data: MarketData,
    cache_root: Path,
    plot_names: Iterable[str],
) -> None:
    """逐策略加载既有结果，只补画尚未随计算阶段生成的图。"""
    if not config.raw["plots"]["strategy"]["enabled"]:
        return
    requested_plots = set(plot_names)
    for strategy_name in strategy_names:
        target_result = load_strategy_targets(strategy_name, strategy_source)
        for mode in ["simple", "account"]:
            if mode not in requested_plots:
                continue
            backtest_result = _load_strategy_backtest_for_plot(
                config,
                strategy_name,
                backtest_sources[mode],
                mode,
            )
            if backtest_result is None:
                continue
            _plot_strategy_backtest_result(
                strategy_name=strategy_name,
                target_result=target_result,
                backtest_result=backtest_result,
                mode=mode,
                settings=config.raw["plots"],
                backtest_settings=config.raw[f"{mode}_backtest"],
                cache_root=cache_root,
            )


def _plot_strategy_backtest_result(
    strategy_name: str,
    target_result: Mapping[str, Any],
    backtest_result: Mapping[str, Any],
    mode: str,
    settings: Mapping[str, Any],
    backtest_settings: Mapping[str, Any],
    cache_root: Path,
) -> None:
    """绘制一个策略当前回测模式下的全部调仓周期图。"""
    figure_directory = cache_root / strategy_name / "figures"
    for interval in target_result["periods"]:
        interval_label = _strategy_interval_label(
            target_result["rebalance_frequency"],
            interval,
        )
        plot_strategy_backtest(
            strategy_name=strategy_name,
            backtest_result=backtest_result,
            mode=mode,
            interval=interval,
            settings=settings,
            output_stem=figure_directory / f"{mode}_{interval_label}",
            backtest_settings=backtest_settings,
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
            result_source,
            mode,
        )
    return load_backtest_result(
        strategy_name,
        result_source,
        mode,
    )


def _save_strategy_summary_checkpoint(
    config: RunConfig,
    strategy_names: Iterable[str],
    strategy_source: Path,
    backtest_sources: Mapping[str, Path],
    market_data: MarketData,
    strategy_cache_root: Path,
    summary_cache_root: Path,
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
            if config.raw["strategy_analysis"]["enabled"]:
                summary_row.update(
                    _strategy_exposure_summary(
                        strategy_cache_root / strategy_name / "analysis",
                        _strategy_interval_label(
                            target_result["rebalance_frequency"],
                            interval,
                        ),
                    )
                )
            for mode, mode_result in mode_results.items():
                if mode_result is not None:
                    summary_row.update(_strategy_metric_columns(mode, mode_result, interval))
            summary_key = (target_result["rebalance_frequency"], interval)
            summaries.setdefault(summary_key, []).append(summary_row)

    output_paths = []
    for (frequency, interval), rows in summaries.items():
        interval_label = _strategy_interval_label(frequency, interval)
        output_path = summary_cache_root / f"strategy_summary_{interval_label}.csv"
        output_path.parent.mkdir(parents=True, exist_ok=True)
        pd.DataFrame(rows).to_csv(output_path, index=False)
        output_paths.append(output_path)
    return tuple(output_paths)


def _strategy_exposure_summary(
    analysis_directory: Path,
    interval_label: str,
) -> dict[str, float]:
    """从已保存明细提取少量可跨策略比较的风险暴露指标。"""
    concentration = pd.read_parquet(analysis_directory / f"concentration_{interval_label}.parquet")
    industry_exposure = pd.read_parquet(
        analysis_directory / f"industry_exposure_{interval_label}.parquet"
    )
    style_exposure = pd.read_parquet(
        analysis_directory / f"style_exposure_{interval_label}.parquet"
    )
    industry_active_share = industry_exposure.groupby("date")["active_weight"].apply(
        lambda weights: 0.5 * weights.abs().sum()
    )
    style_coverage = style_exposure[["portfolio_coverage", "benchmark_coverage"]].min(axis=1)
    unknown_industry_weights = industry_exposure.loc[
        industry_exposure["industry_code"] == "UNKNOWN",
        "portfolio_weight",
    ]
    return {
        "mean_effective_holdings": float(concentration["effective_holdings"].mean()),
        "min_effective_holdings": float(concentration["effective_holdings"].min()),
        "mean_top10_share": float(concentration["top10_share"].mean()),
        "max_top10_share": float(concentration["top10_share"].max()),
        "mean_industry_active_share": float(industry_active_share.mean()),
        "max_industry_active_share": float(industry_active_share.max()),
        "max_unknown_industry_weight": float(
            unknown_industry_weights.max() if not unknown_industry_weights.empty else 0.0
        ),
        "max_abs_active_style": float(style_exposure["active_exposure"].abs().max()),
        "min_style_coverage": float(style_coverage.min()),
    }


def _strategy_metric_columns(
    mode: str,
    result: Mapping[str, Any],
    interval: int,
) -> dict[str, Any]:
    """提取策略汇总表需要的一行 simple 或 account 指标。"""
    metric_row = result["metrics"].loc[result["metrics"]["rebalance_interval"] == interval].iloc[0]
    metric_names = [
        "total_return",
        "annual_return",
        "sharpe",
        "max_drawdown",
        "mean_turnover",
        "annual_turnover",
        "benchmark_total_return",
        "excess_total_return",
        "tracking_error",
        "information_ratio",
    ]
    return {
        f"{mode}_{metric_name.replace('annual_turnover', 'turnover')}": (metric_row[metric_name])
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
            "external_return" if config.external_return_path is not None else "market_price"
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
                "external_return" if config.external_return_path is not None else "market_price"
            ),
        },
        "account": config.raw["account_backtest"],
    }


def _run_overall_evaluation(
    config: RunConfig,
    factor_names: Iterable[str],
    factor_source: Path,
    group_return_source: Path,
    market_data: MarketData,
    cache_root: Path,
) -> None:
    """只为整体评价同时加载因子与评价结果，并输出到 checkpoint。"""
    factor_panels = {
        factor_name: load_factor_panel(factor_name, factor_source)
        for factor_name in factor_names
    }
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
    save_overall_results(overall_result, cache_root / "00_overall")
    plot_overall_evaluation(
        overall_result=overall_result,
        settings=config.raw["plots"],
        output_directory=cache_root / "00_overall",
        evaluation_results=evaluation_results,
        factor_panels=factor_panels,
        evaluation_settings=config.raw["group_return"],
    )


def _prepare_retained_checkpoints(
    config: RunConfig,
    factor_names: Iterable[str],
    strategy_names: Iterable[str],
    cache_root: Path,
) -> Path:
    """按最终明细开关在发布前生成可直接替换的 Parquet。"""
    retained_root = cache_root / ".retained"
    factor_cache_root = factor_output_root(cache_root)
    strategy_cache_root = strategy_output_root(cache_root)
    retained_factor_root = factor_output_root(retained_root)
    retained_strategy_root = strategy_output_root(retained_root)
    for mode in ["simple", "account"]:
        stage_name = f"{mode}_backtest"
        if not (config.raw["run"][stage_name] and config.raw["output"]["save_parquet"][stage_name]):
            continue
        for factor_name in factor_names:
            result = load_backtest_checkpoint(
                factor_name,
                factor_cache_root,
                mode,
            )
            save_backtest_results(
                {factor_name: result},
                retained_factor_root,
                mode,
                save_details=config.raw["output"]["save_backtest_details"],
            )
    for mode in ["simple", "account"]:
        stage_name = f"strategy_{mode}_backtest"
        if not (config.raw["run"][stage_name] and config.raw["output"]["save_parquet"][stage_name]):
            continue
        for strategy_name in strategy_names:
            result = load_backtest_checkpoint(
                strategy_name,
                strategy_cache_root,
                mode,
            )
            save_backtest_results(
                {strategy_name: result},
                retained_strategy_root,
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
    factor_cache_root = factor_output_root(cache_root)
    strategy_cache_root = strategy_output_root(cache_root)
    summary_cache_root = summary_output_root(cache_root)
    published_factor_root = factor_output_root(config.output_root)
    published_strategy_root = strategy_output_root(config.output_root)
    published_summary_root = summary_output_root(config.output_root)
    retained_factor_root = factor_output_root(retained_root)
    retained_strategy_root = strategy_output_root(retained_root)
    if not _factor_figures_enabled(config):
        _remove_factor_figure_directories(
            factor_names,
            published_factor_root,
        )
    snapshot_names = ["config_snapshot.yaml"]
    if config.factor_domains is not None:
        snapshot_names.append("domain_config_snapshot.yaml")
    snapshot_paths = tuple(
        _publish_file(
            cache_root / snapshot_name,
            config.output_root / snapshot_name,
        )
        for snapshot_name in snapshot_names
    )
    output_paths["config"] = snapshot_paths

    factor_summary_paths = [
        summary_cache_root / file_name
        for file_name in FACTOR_SUMMARY_FILE_NAMES.values()
        if (summary_cache_root / file_name).exists()
    ]
    if factor_summary_paths:
        published_factor_summaries = tuple(
            _publish_file(
                factor_summary_path,
                published_summary_root / factor_summary_path.name,
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

    strategy_summary_paths = sorted(summary_cache_root.glob("strategy_summary_*.csv"))
    if strategy_summary_paths:
        output_paths["strategy_summary"] = tuple(
            _publish_file(
                summary_path,
                published_summary_root / summary_path.name,
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
                published_factor_root,
                file_name,
            )
            continue
        source_root = (
            retained_factor_root
            if stage_name in {"simple_backtest", "account_backtest"}
            else factor_cache_root
        )
        published = tuple(
            _publish_file(
                source_root / factor_name / file_name,
                published_factor_root / factor_name / file_name,
            )
            for factor_name in factor_names
        )
        output_paths[stage_name] = published

    if config.raw["run"]["strategies"]:
        if config.raw["output"]["save_parquet"]["strategy_weights"]:
            output_paths["strategies"] = tuple(
                _publish_file(
                    strategy_cache_root / strategy_name / TARGET_FILE_NAME,
                    published_strategy_root / strategy_name / TARGET_FILE_NAME,
                )
                for strategy_name in strategy_names
            )
        else:
            for strategy_name in strategy_names:
                target_path = published_strategy_root / strategy_name / TARGET_FILE_NAME
                target_path.unlink(missing_ok=True)

    for mode in ["simple", "account"]:
        stage_name = f"strategy_{mode}_backtest"
        if not config.raw["run"][stage_name]:
            continue
        file_name = RESULT_FILE_NAMES[mode]
        if not config.raw["output"]["save_parquet"][stage_name]:
            for strategy_name in strategy_names:
                result_path = published_strategy_root / strategy_name / file_name
                result_path.unlink(missing_ok=True)
            continue
        output_paths[stage_name] = tuple(
            _publish_file(
                retained_strategy_root / strategy_name / file_name,
                published_strategy_root / strategy_name / file_name,
            )
            for strategy_name in strategy_names
        )

    if config.raw["run"]["plotter"]:
        factor_figures = _publish_cached_tree(
            factor_cache_root,
            published_factor_root,
            "figures",
        )
        strategy_figures = _publish_cached_tree(
            strategy_cache_root,
            published_strategy_root,
            "figures",
        )
        output_paths["plotter"] = tuple(factor_figures + strategy_figures)
    if config.raw["strategy_analysis"]["enabled"]:
        _remove_legacy_strategy_deviation_figures(
            strategy_names,
            published_strategy_root,
        )
        output_paths["strategy_analysis"] = tuple(
            _publish_cached_tree(
                strategy_cache_root,
                published_strategy_root,
                "analysis",
            )
        )
    if config.raw["run"]["overall_evaluation"]:
        output_paths["overall_evaluation"] = tuple(
            _publish_cached_tree(cache_root, config.output_root, "00_overall")
        )
    return output_paths


def _factor_figures_enabled(config: RunConfig) -> bool:
    """判断本次是否允许发布任何单因子图。"""
    if not config.raw["run"]["plotter"]:
        return False
    factor_plot_names = ("distribution", "evaluation", "simple", "account")
    return any(config.raw["plots"][plot_name]["enabled"] for plot_name in factor_plot_names)


def _remove_factor_figure_directories(
    factor_names: Iterable[str],
    output_root: Path,
) -> None:
    """清理当前因子上次运行遗留的单因子图目录。"""
    for factor_name in factor_names:
        figure_directory = output_root / factor_name / "figures"
        if figure_directory.is_dir():
            shutil.rmtree(figure_directory)


def _remove_legacy_strategy_deviation_figures(
    strategy_names: Iterable[str],
    output_root: Path,
) -> None:
    """启用新版总览后清理输出目录中遗留的独立 deviation 图。"""
    for strategy_name in strategy_names:
        figure_directory = output_root / strategy_name / "figures"
        for legacy_path in figure_directory.glob("deviation_*"):
            legacy_path.unlink()


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
        published_paths.append(_publish_file(source_path, output_root / relative_path))
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
    if (
        any(run_settings[stage_name] for stage_name in calculation_stages)
        or config.raw["strategy_analysis"]["enabled"]
    ):
        stages.append("market_data")
    stages.extend(
        stage_name
        for stage_name in [
            "factors",
            "group_return",
            "overall_evaluation",
            "simple_backtest",
            "account_backtest",
            "strategies",
            "strategy_simple_backtest",
            "strategy_account_backtest",
            "plotter",
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
    calculation_enabled |= config.raw["strategy_analysis"]["enabled"]
    if not calculation_enabled:
        return None
    return MarketData.from_yaml(
        config.path,
        refresh=config.raw["run"]["refresh_market_data"],
        market_data_config=config.raw["market_data"],
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
