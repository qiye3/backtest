"""按照主 YAML 中的阶段开关运行批量因子评价和回测。"""

from __future__ import annotations

import argparse
from collections.abc import Iterable
from pathlib import Path
from typing import Any

import pandas as pd
from tqdm.auto import tqdm

from src.backtest import run_backtests
from src.backtest.io import (
    RESULT_FILE_NAMES,
    load_backtest_results,
    save_backtest_results,
    save_metrics_summary,
)
from src.config import RunConfig, load_config, save_config_snapshot
from src.data.market_data import MarketData
from src.data.return_data import load_return_panel
from src.factors import calc_factors, load_factors
from src.factors.io import (
    FACTOR_FILE_NAME,
    load_factor_panels,
    save_factor_panels,
)
from src.group_return import evaluate_factors
from src.group_return.io import (
    RESULT_FILE_NAME as GROUP_RETURN_FILE_NAME,
)
from src.group_return.io import (
    load_evaluation_results,
    save_evaluation_results,
)
from src.overall_evaluation import evaluate_overall
from src.plotter import plot_factors, plot_overall_evaluation


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
) -> dict[str, Any]:
    """按配置固定顺序运行启用阶段，并优先复用本次内存结果。"""
    with _CliProgress(config, show_progress) as progress:
        return _run_pipeline(config, progress)


def _run_pipeline(
    config: RunConfig,
    progress: _CliProgress,
) -> dict[str, Any]:
    """执行固定阶段链路，并在每个阶段成功后更新 CLI 进度。"""
    save_config_snapshot(config)
    run_settings = config.raw["run"]
    stage_results: dict[str, Any] = {}

    progress.start("market_data")
    market_data = _load_market_data(config)
    progress.complete("market_data")

    needs_external_returns = run_settings["group_return"] or run_settings[
        "simple_backtest"
    ]
    external_return_panel = None
    if config.external_return_path is not None and needs_external_returns:
        progress.start("external_returns")
        external_return_panel = load_return_panel(config.external_return_path)
        progress.complete("external_returns")

    progress.start("factors")
    factor_panels = _calculate_factors(config, market_data)
    if factor_panels is not None:
        stage_results["factors"] = factor_panels
    elif any(
        run_settings[stage_name]
        for stage_name in [
            "group_return",
            "simple_backtest",
            "account_backtest",
            "plotter",
            "overall_evaluation",
        ]
    ):
        factor_panels = load_factor_panels(config.output_root)
    progress.complete("factors")

    progress.start("group_return")
    group_return_results = _run_group_return(
        config,
        factor_panels,
        market_data,
        external_return_panel,
    )
    if group_return_results is not None:
        stage_results["group_return"] = group_return_results
    progress.complete("group_return")

    progress.start("simple_backtest")
    simple_backtest_results = _run_backtest(
        config,
        factor_panels,
        market_data,
        "simple",
        external_return_panel,
    )
    if simple_backtest_results is not None:
        stage_results["simple_backtest"] = simple_backtest_results
    progress.complete("simple_backtest")

    progress.start("account_backtest")
    account_backtest_results = _run_backtest(
        config,
        factor_panels,
        market_data,
        "account",
        None,
    )
    if account_backtest_results is not None:
        stage_results["account_backtest"] = account_backtest_results
    progress.complete("account_backtest")

    completed_backtests = {}
    if simple_backtest_results is not None:
        completed_backtests["simple"] = simple_backtest_results
    if account_backtest_results is not None:
        completed_backtests["account"] = account_backtest_results
    if completed_backtests:
        save_metrics_summary(
            completed_backtests,
            group_return_results,
            config.output_root,
        )

    if run_settings["plotter"]:
        progress.start("plotter")
        if group_return_results is None:
            group_return_results = load_evaluation_results(
                factor_panels,
                config.output_root,
            )
        if simple_backtest_results is None:
            simple_backtest_results = load_backtest_results(
                factor_panels,
                config.output_root,
                "simple",
            )
        if account_backtest_results is None:
            account_backtest_results = load_backtest_results(
                factor_panels,
                config.output_root,
                "account",
            )
        plot_paths = plot_factors(
            factor_panels=factor_panels,
            settings={**config.raw["plots"], "enabled": True},
            output_root=config.output_root,
            group_return_results=group_return_results,
            simple_backtest_results=simple_backtest_results,
            account_backtest_results=account_backtest_results,
            evaluation_settings={
                **config.raw["group_return"],
                "return_source": (
                    "external_return"
                    if config.external_return_path is not None
                    else "market_price"
                ),
            },
            backtest_settings={
                "simple": {
                    **config.raw["simple_backtest"],
                    "return_source": (
                        "external_return"
                        if config.external_return_path is not None
                        else "market_price"
                    ),
                },
                "account": config.raw["account_backtest"],
            },
        )
        stage_results["plotter"] = plot_paths
        progress.complete("plotter")

    progress.start("overall_evaluation")
    overall_result = _run_overall_evaluation(
        config=config,
        factor_panels=factor_panels,
        market_data=market_data,
        group_return_results=group_return_results,
    )
    if overall_result is not None:
        stage_results["overall_evaluation"] = overall_result
    progress.complete("overall_evaluation")
    return stage_results


def _enabled_progress_stages(config: RunConfig) -> tuple[str, ...]:
    """按真实执行顺序列出 CLI 需要展示的阶段。"""
    run_settings = config.raw["run"]
    calculation_stages = {
        "factors",
        "group_return",
        "simple_backtest",
        "account_backtest",
        "overall_evaluation",
    }
    stages = []
    if any(run_settings[stage_name] for stage_name in calculation_stages):
        stages.append("market_data")
    if config.external_return_path is not None and (
        run_settings["group_return"] or run_settings["simple_backtest"]
    ):
        stages.append("external_returns")
    if run_settings["factors"] or any(
        run_settings[stage_name]
        for stage_name in {
            "group_return",
            "simple_backtest",
            "account_backtest",
            "plotter",
            "overall_evaluation",
        }
    ):
        stages.append("factors")
    stages.extend(
        stage_name
        for stage_name in [
            "group_return",
            "simple_backtest",
            "account_backtest",
            "plotter",
            "overall_evaluation",
        ]
        if run_settings[stage_name]
    )
    return tuple(stages)


def _load_market_data(config: RunConfig) -> MarketData | None:
    """在任一计算阶段启用时构建或复用共享市场数据。"""
    run_settings = config.raw["run"]
    calculation_enabled = any(
        run_settings[stage_name]
        for stage_name in [
            "factors",
            "group_return",
            "simple_backtest",
            "account_backtest",
            "overall_evaluation",
        ]
    )
    if not calculation_enabled:
        return None
    return MarketData.from_yaml(
        config.path,
        refresh=run_settings["refresh_market_data"],
    )


def _calculate_factors(
    config: RunConfig,
    market_data: MarketData | None,
) -> dict[str, pd.DataFrame] | None:
    """运行启用的 Factor 阶段并按输出开关处理标准面板。"""
    if not config.raw["run"]["factors"]:
        return None
    factors = load_factors(config.factor_config_directory)
    factor_panels = calc_factors(
        factors=factors,
        market_data=market_data,
        max_workers=config.raw["run"]["max_workers"],
    )
    if config.raw["output"]["save_parquet"]["factor"]:
        save_factor_panels(factor_panels, config.output_root)
    else:
        _remove_factor_parquets(
            factor_panels,
            config.output_root,
            FACTOR_FILE_NAME,
        )
    return factor_panels


def _run_group_return(
    config: RunConfig,
    factor_panels: dict[str, pd.DataFrame] | None,
    market_data: MarketData | None,
    return_panel: pd.DataFrame | None,
) -> dict[str, dict[str, Any]] | None:
    """运行启用的评价阶段并按输出开关处理 Parquet。"""
    if not config.raw["run"]["group_return"]:
        return None
    results = evaluate_factors(
        factor_panels=factor_panels,
        market_data=market_data,
        settings=config.raw["group_return"],
        max_workers=config.raw["run"]["max_workers"],
        return_panel=return_panel,
    )
    if config.raw["output"]["save_parquet"]["group_return"]:
        save_evaluation_results(results, config.output_root)
    else:
        _remove_factor_parquets(
            results,
            config.output_root,
            GROUP_RETURN_FILE_NAME,
        )
    return results


def _run_backtest(
    config: RunConfig,
    factor_panels: dict[str, pd.DataFrame] | None,
    market_data: MarketData | None,
    mode: str,
    return_panel: pd.DataFrame | None,
) -> dict[str, dict[str, Any]] | None:
    """运行启用的一类回测并按输出开关处理 Parquet。"""
    section_name = f"{mode}_backtest"
    if not config.raw["run"][section_name]:
        return None
    results = run_backtests(
        factor_panels=factor_panels,
        market_data=market_data,
        settings=config.raw[section_name],
        metrics_settings=config.raw["metrics"],
        mode=mode,
        max_workers=config.raw["run"]["max_workers"],
        return_panel=return_panel,
    )
    if config.raw["output"]["save_parquet"][section_name]:
        save_backtest_results(
            results,
            config.output_root,
            mode,
            save_details=config.raw["output"]["save_backtest_details"],
        )
    else:
        _remove_factor_parquets(
            results,
            config.output_root,
            RESULT_FILE_NAMES[mode],
        )
    return results


def _run_overall_evaluation(
    config: RunConfig,
    factor_panels: dict[str, pd.DataFrame],
    market_data: MarketData,
    group_return_results: dict[str, dict[str, Any]] | None,
) -> dict[str, pd.DataFrame] | None:
    """计算一批因子的整体统计并输出三张根目录图。"""
    if not config.raw["run"]["overall_evaluation"]:
        return None
    if group_return_results is None:
        group_return_results = load_evaluation_results(
            factor_panels,
            config.output_root,
        )
    overall_result = evaluate_overall(
        factor_panels=factor_panels,
        evaluation_results=group_return_results,
        market_data=market_data,
        evaluation_settings=config.raw["group_return"],
        max_workers=config.raw["run"]["max_workers"],
    )
    plot_overall_evaluation(
        overall_result=overall_result,
        settings=config.raw["plots"],
        output_directory=config.output_root / "00_overall",
    )
    return overall_result


def _remove_factor_parquets(
    factor_names: Iterable[str],
    output_root: Path,
    file_name: str,
) -> None:
    """删除已启用阶段遗留的同类 Parquet，保证关闭开关后不保留旧结果。"""
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
    stage_results = run(config, show_progress=True)
    for stage_name, results in stage_results.items():
        print(f"{stage_name}: {len(results)} factor(s)")


if __name__ == "__main__":
    main()
