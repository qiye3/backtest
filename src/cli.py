"""按照主 YAML 中的阶段开关运行批量因子评价和回测。"""

from __future__ import annotations

import argparse
from typing import Any

import pandas as pd

from src.backtest import run_backtests
from src.backtest.io import (
    load_backtest_results,
    save_backtest_results,
    save_metrics_summary,
)
from src.config import RunConfig, load_config, save_config_snapshot
from src.data.market_data import MarketData
from src.factors import calc_factors, load_factors
from src.factors.io import load_factor_panels, save_factor_panels
from src.group_return import evaluate_factors
from src.group_return.io import (
    load_evaluation_results,
    save_evaluation_results,
)
from src.plotter import plot_factors


def run(config: RunConfig) -> dict[str, Any]:
    """按配置固定顺序运行启用阶段，并优先复用本次内存结果。"""
    save_config_snapshot(config)
    run_settings = config.raw["run"]
    stage_results: dict[str, Any] = {}
    market_data = _load_market_data(config)
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
        ]
    ):
        factor_panels = load_factor_panels(config.output_root)

    group_return_results = _run_group_return(
        config,
        factor_panels,
        market_data,
    )
    if group_return_results is not None:
        stage_results["group_return"] = group_return_results
    simple_backtest_results = _run_backtest(
        config,
        factor_panels,
        market_data,
        "simple",
    )
    if simple_backtest_results is not None:
        stage_results["simple_backtest"] = simple_backtest_results
    account_backtest_results = _run_backtest(
        config,
        factor_panels,
        market_data,
        "account",
    )
    if account_backtest_results is not None:
        stage_results["account_backtest"] = account_backtest_results

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
            evaluation_settings=config.raw["group_return"],
            backtest_settings={
                "simple": config.raw["simple_backtest"],
                "account": config.raw["account_backtest"],
            },
        )
        stage_results["plotter"] = plot_paths
    return stage_results


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
    """运行启用的 Factor 阶段并覆盖保存标准面板。"""
    if not config.raw["run"]["factors"]:
        return None
    factors = load_factors(config.factor_config_directory)
    factor_panels = calc_factors(
        factors=factors,
        market_data=market_data,
        max_workers=config.raw["run"]["max_workers"],
    )
    save_factor_panels(factor_panels, config.output_root)
    return factor_panels


def _run_group_return(
    config: RunConfig,
    factor_panels: dict[str, pd.DataFrame] | None,
    market_data: MarketData | None,
) -> dict[str, dict[str, Any]] | None:
    """运行启用的评价阶段并覆盖保存紧凑结果。"""
    if not config.raw["run"]["group_return"]:
        return None
    results = evaluate_factors(
        factor_panels=factor_panels,
        market_data=market_data,
        settings=config.raw["group_return"],
        max_workers=config.raw["run"]["max_workers"],
    )
    save_evaluation_results(results, config.output_root)
    return results


def _run_backtest(
    config: RunConfig,
    factor_panels: dict[str, pd.DataFrame] | None,
    market_data: MarketData | None,
    mode: str,
) -> dict[str, dict[str, Any]] | None:
    """运行启用的一类回测并覆盖保存指标、曲线和交易结果。"""
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
    )
    save_backtest_results(
        results,
        config.output_root,
        mode,
        save_details=config.raw["output"]["save_backtest_details"],
    )
    return results


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
    stage_results = run(config)
    for stage_name, results in stage_results.items():
        print(f"{stage_name}: {len(results)} factor(s)")


if __name__ == "__main__":
    main()
