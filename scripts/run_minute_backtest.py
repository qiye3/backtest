"""运行基于 zxy 分钟归档的真实成交账户回测。"""

from __future__ import annotations

import argparse
from collections.abc import Iterable, Iterator

import pandas as pd

from src.intraday.config import MinuteBacktestConfig, load_minute_config
from src.intraday.data import (
    MinuteArchiveReader,
    attach_daily_trade_status,
    load_corporate_actions,
    load_daily_trade_status,
)
from src.intraday.engine import MinuteBacktestEngine
from src.intraday.io import save_run_outputs
from src.intraday.strategy import (
    generate_daily_strategy_targets,
    load_daily_minute_strategy,
)
from src.intraday.targets import load_target_weights, load_universe_codes


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", required=True, help="分钟回测 YAML 路径")
    parser.add_argument(
        "--validate-only",
        action="store_true",
        help="只校验配置、数据覆盖和策略入口，不运行回测",
    )
    arguments = parser.parse_args()

    config = load_minute_config(arguments.config)
    reader = MinuteArchiveReader(
        config.data.minute_root,
        config.data.cache_root,
        config.data.universe_name,
    )
    _validate_data_coverage(config, reader)
    codes = _load_research_codes(config)

    if arguments.validate_only:
        _validate_strategy_entry(config)
        _print_validation_summary(config, reader, codes)
        return

    targets = _load_or_generate_targets(config, reader, codes)
    daily_status = load_daily_trade_status(
        config.data.daily_status_path,
        codes,
        config.data.start_date,
        config.data.end_date,
    )
    daily_bars = _bars_with_daily_status(
        reader.iter_days(config.data.start_date, config.data.end_date, codes),
        daily_status,
    )
    corporate_actions = None
    if config.data.daily_root is not None:
        corporate_actions = load_corporate_actions(config.data.daily_root, codes)

    result = MinuteBacktestEngine(config).run_stream(
        daily_bars,
        targets,
        corporate_actions,
    )
    source_snapshot = reader.source_snapshot(
        config.data.start_date,
        config.data.end_date,
    )
    output_directory = save_run_outputs(
        config,
        result,
        reader.issues,
        source_snapshot,
    )
    print(f"分钟回测完成: {output_directory}")
    print(f"最终净值: {result.metrics.get('final_nav', float('nan')):,.2f}")


def _load_research_codes(config: MinuteBacktestConfig) -> list[str]:
    if config.targets.mode == "file":
        assert config.targets.path is not None
        targets = load_target_weights(
            config.targets.path,
            config.targets.date_only_signal_time,
        )
        return sorted(targets["code"].unique())
    assert config.targets.universe_path is not None
    return load_universe_codes(config.targets.universe_path)


def _load_or_generate_targets(
    config: MinuteBacktestConfig,
    reader: MinuteArchiveReader,
    codes: list[str],
) -> pd.DataFrame:
    if config.targets.mode == "file":
        assert config.targets.path is not None
        return load_target_weights(
            config.targets.path,
            config.targets.date_only_signal_time,
        )
    assert config.targets.implementation is not None
    strategy = load_daily_minute_strategy(config.targets.implementation)
    strategy_bars = reader.iter_days(
        config.data.start_date,
        config.data.end_date,
        codes,
    )
    return generate_daily_strategy_targets(strategy, strategy_bars, codes)


def _validate_strategy_entry(config: MinuteBacktestConfig) -> None:
    if config.targets.mode != "daily_minute_strategy":
        return
    assert config.targets.implementation is not None
    load_daily_minute_strategy(config.targets.implementation)


def _validate_data_coverage(
    config: MinuteBacktestConfig,
    reader: MinuteArchiveReader,
) -> None:
    available_dates = reader.available_dates()
    if not available_dates:
        raise ValueError(f"分钟归档目录为空: {config.data.minute_root}")
    if config.data.start_date < available_dates[0]:
        raise ValueError(
            f"回测开始日 {config.data.start_date.date()} 早于数据起点 "
            f"{available_dates[0].date()}"
        )
    if config.data.end_date > available_dates[-1]:
        raise ValueError(
            f"回测结束日 {config.data.end_date.date()} 晚于数据截止日 "
            f"{available_dates[-1].date()}"
        )
    reader.dates_in_range(config.data.start_date, config.data.end_date)


def _bars_with_daily_status(
    daily_bars: Iterable[pd.DataFrame],
    daily_status: pd.DataFrame,
) -> Iterator[pd.DataFrame]:
    for bars in daily_bars:
        yield attach_daily_trade_status(bars, daily_status)


def _print_validation_summary(
    config: MinuteBacktestConfig,
    reader: MinuteArchiveReader,
    codes: list[str],
) -> None:
    dates = reader.dates_in_range(config.data.start_date, config.data.end_date)
    print("分钟回测预检通过")
    print(f"目标模式: {config.targets.mode}")
    print(f"股票数量: {len(codes)}")
    print(f"归档交易日: {len(dates)}")
    print(f"数据区间: {dates[0].date()} 至 {dates[-1].date()}")
    print(f"数据截止日: {reader.latest_available_date().date()}")


if __name__ == "__main__":
    main()
