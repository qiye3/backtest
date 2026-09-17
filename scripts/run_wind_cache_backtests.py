"""从本地 Wind Parquet 缓存运行日度和周度因子回测。"""

from __future__ import annotations

import argparse
import json
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from functools import partial
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from src.backtest import run_backtests
from src.backtest.io import save_backtest_results
from src.config import RunConfig, load_config
from src.data.market_data import MarketData
from src.factors import calc_factors, load_factors
from src.factors.io import save_factor_panels
from src.plotter.backtest import plot_backtest

BENCHMARK_CODE = "000906.SH"
UNIVERSE_INDEX_CODES = ("000906.SH", "000852.SH")


def load_wind_market_data(
    wind_cache_root: Path,
    start_date: pd.Timestamp,
    end_date: pd.Timestamp,
    max_workers: int,
) -> tuple[MarketData, dict[str, Any]]:
    """读取 Wind 中证1800缓存并构造当前项目使用的市场面板。"""
    csi1800_root = wind_cache_root / "raw" / "csi1800_2010"
    csi800_root = wind_cache_root / "raw" / "csi800_2010"
    csi1800_codes = pd.Index(
        pd.read_parquet(csi1800_root / "universe.parquet")["code"],
        name="asset_code",
    )
    csi800_codes = pd.Index(
        pd.read_parquet(csi800_root / "universe.parquet")["code"],
        name="asset_code",
    )
    csi1000_codes = csi1800_codes.difference(csi800_codes, sort=False)

    benchmark_path = (
        csi800_root / "daily_bars" / f"{BENCHMARK_CODE}.parquet"
    )
    benchmark_close = _load_adjusted_close(
        benchmark_path,
        start_date,
        end_date,
    )
    calendar = pd.DatetimeIndex(benchmark_close.index, name="date")

    stock_paths = [
        csi1800_root / "daily_bars" / f"{code}.parquet"
        for code in csi1800_codes
    ]
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        stock_series = list(
            executor.map(
                partial(
                    _load_adjusted_close,
                    start_date=start_date,
                    end_date=end_date,
                ),
                stock_paths,
            )
        )
    stock_close = pd.concat(stock_series, axis=1).reindex(
        index=calendar,
        columns=csi1800_codes,
    )

    membership_by_index = pd.concat(
        {
            UNIVERSE_INDEX_CODES[0]: pd.DataFrame(
                True,
                index=calendar,
                columns=csi800_codes,
            ).reindex(columns=csi1800_codes, fill_value=False),
            UNIVERSE_INDEX_CODES[1]: pd.DataFrame(
                True,
                index=calendar,
                columns=csi1000_codes,
            ).reindex(columns=csi1800_codes, fill_value=False),
        },
        axis=1,
        names=["index_code", "asset_code"],
    )
    membership_panel = pd.concat(
        {"membership": membership_by_index},
        axis=1,
        names=["field", "index_code", "asset_code"],
    )
    membership = membership_by_index.T.groupby(level="asset_code").any().T
    source_panels = {
        "stock_quote": pd.concat(
            {"S_DQ_ADJCLOSE": stock_close},
            axis=1,
            names=["field", "asset_code"],
        ),
        "index_price": pd.concat(
            {"S_DQ_CLOSE": benchmark_close.to_frame(BENCHMARK_CODE)},
            axis=1,
            names=["field", "asset_code"],
        ),
        "index_membership": membership_panel,
    }
    quality_summary = {
        "source": str(csi1800_root),
        "benchmark_source": str(benchmark_path),
        "calendar_start": str(calendar.min().date()),
        "calendar_end": str(calendar.max().date()),
        "trading_days": len(calendar),
        "stock_count": len(csi1800_codes),
        "csi800_count": len(csi800_codes),
        "csi1000_count": len(csi1000_codes),
        "price_observations": int(stock_close.notna().sum().sum()),
        "price_missing_rate": float(stock_close.isna().mean().mean()),
        "survivorship_bias": "2026-09-08 current constituent snapshot",
        "adjustment": "cumprod(close / prev_close)",
    }
    return (
        MarketData(
            source_panels=source_panels,
            calendar=calendar,
            membership=membership,
            benchmark_index=BENCHMARK_CODE,
        ),
        quality_summary,
    )


def _load_adjusted_close(
    source_path: Path,
    start_date: pd.Timestamp,
    end_date: pd.Timestamp,
) -> pd.Series:
    """用 close/prev_close 日收益链接 Wind 原始价格，消除公司行动跳点。"""
    raw_bars = pd.read_parquet(
        source_path,
        columns=["trade_date", "prev_close", "close", "code"],
    )
    raw_bars = raw_bars.loc[
        raw_bars["trade_date"].between(start_date, end_date)
    ].sort_values("trade_date")
    if raw_bars["trade_date"].duplicated().any():
        raise ValueError(f"行情日期重复: {source_path}")

    daily_growth = raw_bars["close"] / raw_bars["prev_close"]
    if (~np.isfinite(daily_growth) | (daily_growth <= 0)).any():
        raise ValueError(f"行情价格无效: {source_path}")
    adjusted_close = raw_bars["prev_close"].iloc[0] * daily_growth.cumprod()
    adjusted_close.index = pd.DatetimeIndex(raw_bars["trade_date"], name="date")
    adjusted_close.name = str(raw_bars["code"].iloc[0])
    return adjusted_close


def run_frequency(
    factor_panels: dict[str, pd.DataFrame],
    market_data: MarketData,
    config: RunConfig,
    frequency: str,
    output_root: Path,
) -> pd.DataFrame:
    """运行并保存一个调仓频率下的 simple 与 account 回测。"""
    frequency_output_root = output_root / frequency
    save_factor_panels(factor_panels, frequency_output_root)
    metrics_frames = []
    for mode in ["simple", "account"]:
        settings = _backtest_settings(config.raw[f"{mode}_backtest"], frequency)
        for factor_name, factor_panel in factor_panels.items():
            print(f"[{frequency}] {mode}: {factor_name}", flush=True)
            factor_results = run_backtests(
                factor_panels={factor_name: factor_panel},
                market_data=market_data,
                settings=settings,
                metrics_settings=config.raw["metrics"],
                mode=mode,
                max_workers=config.raw["run"]["max_workers"],
                collect_details=config.raw["output"]["save_backtest_details"],
            )
            save_backtest_results(
                factor_results,
                frequency_output_root,
                mode,
                save_details=config.raw["output"]["save_backtest_details"],
            )
            plot_backtest(
                factor_name=factor_name,
                backtest_result=factor_results[factor_name],
                mode=mode,
                settings=config.raw["plots"],
                output_stem=(
                    frequency_output_root
                    / factor_name
                    / "figures"
                    / f"{mode}_backtest"
                ),
            )
            factor_metrics = factor_results[factor_name]["metrics"].copy()
            factor_metrics.insert(0, "factor_name", factor_name)
            metrics_frames.append(factor_metrics)
    metrics = pd.concat(metrics_frames, ignore_index=True)
    metrics.to_csv(frequency_output_root / "metrics_summary.csv", index=False)
    return metrics


def _backtest_settings(
    base_settings: dict[str, Any],
    frequency: str,
) -> dict[str, Any]:
    """生成真实行情实验统一使用的可成交时点与费用设置。"""
    settings = deepcopy(base_settings)
    settings["factor_lag_days"] = 1
    settings["transaction_cost_rate"] = 0.001
    settings["missing_price_policy"] = "previous_close"
    if frequency == "daily":
        settings["rebalance"] = {
            "frequency": "daily",
            "intervals": [1],
        }
    else:
        settings["rebalance"] = {
            "frequency": "weekly",
            "intervals": [1],
            "weekday": "FRI",
            "anchor_date": settings["start"],
            "holiday_policy": "previous_trading_day",
        }
    return settings


def main() -> None:
    """解析路径和日期，构建一次真实面板并依次运行两种频率。"""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", required=True, type=Path)
    parser.add_argument("--wind-cache-root", required=True, type=Path)
    parser.add_argument("--output-root", required=True, type=Path)
    parser.add_argument("--market-start", required=True)
    parser.add_argument("--backtest-start", required=True)
    parser.add_argument("--end", required=True)
    arguments = parser.parse_args()

    config = load_config(arguments.config)
    market_start = pd.Timestamp(arguments.market_start)
    backtest_start = pd.Timestamp(arguments.backtest_start)
    end_date = pd.Timestamp(arguments.end)
    market_data, quality_summary = load_wind_market_data(
        wind_cache_root=arguments.wind_cache_root.expanduser().resolve(),
        start_date=market_start,
        end_date=end_date,
        max_workers=config.raw["run"]["max_workers"],
    )
    print(
        "[data] "
        f"{quality_summary['trading_days']} days, "
        f"{quality_summary['stock_count']} stocks, "
        f"missing={quality_summary['price_missing_rate']:.2%}",
        flush=True,
    )
    factors = load_factors(config.factor_config_directory)
    factor_panels = calc_factors(
        factors=factors,
        market_data=market_data,
        max_workers=config.raw["run"]["max_workers"],
    )
    for section_name in ["simple_backtest", "account_backtest"]:
        config.raw[section_name]["start"] = str(backtest_start.date())
        config.raw[section_name]["end"] = str(end_date.date())

    output_root = arguments.output_root.expanduser().resolve()
    output_root.mkdir(parents=True, exist_ok=True)
    (output_root / "data_quality.json").write_text(
        json.dumps(quality_summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    for frequency in ["daily", "weekly"]:
        run_frequency(
            factor_panels=factor_panels,
            market_data=market_data,
            config=config,
            frequency=frequency,
            output_root=output_root,
        )


if __name__ == "__main__":
    main()
