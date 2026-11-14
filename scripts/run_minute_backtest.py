"""运行基于 zxy 分钟归档的真实成交账户回测。"""

from __future__ import annotations

import argparse
import os
import tempfile
from dataclasses import replace
from collections.abc import Iterable, Iterator
from pathlib import Path

import pandas as pd

from src.intraday.config import MinuteBacktestConfig, load_minute_config
from src.intraday.data import (
    MinuteArchiveReader,
    attach_daily_trade_status,
    load_corporate_actions,
    load_daily_trade_status,
)
from src.intraday.engine import MinuteBacktestEngine
from src.intraday.layers import build_factor_layer_targets
from src.intraday.io import save_run_outputs
from src.intraday.strategy import (
    generate_daily_strategy_targets,
    load_daily_minute_strategy,
)
from src.intraday.targets import (
    load_target_weights, load_strategy_output_targets, load_universe_codes,
)
from src.intraday.universe import HistoricalIndexUniverse


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
    universe = (
        HistoricalIndexUniverse(config.universe.members_root, config.universe.index_code)
        if config.universe is not None else None
    )
    codes = _load_research_codes(config, universe)

    if arguments.validate_only:
        _validate_strategy_entry(config)
        _print_validation_summary(config, reader, codes)
        return

    if config.targets.mode == "factor_layers":
        _run_factor_layers(config, reader, codes, universe)
        return

    targets = _load_or_generate_targets(config, reader, codes, universe)
    if universe is not None:
        universe.validate_targets(targets)
        # 退出现有股票池的股票仍需估值和清仓。
        codes = sorted(set(codes) | set(targets["code"]))
    daily_status = load_daily_trade_status(
        config.data.daily_status_path,
        codes,
        config.data.start_date,
        config.data.end_date,
    )
    # 回测和事后模拟账户共用每天有效成份 + 已持有/待补单标的的行情范围。
    engine = MinuteBacktestEngine(config)
    stream_codes = (
        lambda date: _execution_codes_for_day(universe, engine, date, targets)
        if universe is not None else codes
    )
    daily_bars = _bars_with_daily_status(
        reader.iter_days(config.data.start_date, config.data.end_date, stream_codes),
        daily_status,
    )
    corporate_actions = None
    if config.data.daily_root is not None:
        corporate_actions = load_corporate_actions(config.data.daily_root, codes)

    result = engine.run_stream(
        daily_bars,
        targets,
        corporate_actions,
        record_frequency="daily",
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


def _load_research_codes(
    config: MinuteBacktestConfig,
    universe: HistoricalIndexUniverse | None = None,
) -> list[str]:
    if universe is not None:
        return list(universe.codes_between(config.data.start_date, config.data.end_date))
    if config.targets.mode in {"file", "strategy_output"}:
        return sorted(_load_file_targets(config)["code"].unique())
    assert config.targets.universe_path is not None
    return load_universe_codes(config.targets.universe_path)


def _execution_codes_for_day(
    universe: HistoricalIndexUniverse,
    engine: MinuteBacktestEngine,
    date: pd.Timestamp,
    targets: pd.DataFrame,
) -> list[str]:
    """每日历史成份、实际持仓、在途目标，以及当日首次激活的信号股票。"""
    # 已完成且不在当日指数中的历史目标无需反复读取行情；
    # 实际持仓、尚需补单的目标和新信号会单独保留。
    active = set(engine._fixed_pending_codes)
    active.update(code for code, pos in engine.positions.items() if pos.shares)
    eligible = targets[
        targets["signal_timestamp"].dt.tz_localize(None).dt.normalize() < date
    ]
    last_seen = engine._last_applied_signal_timestamp
    if last_seen is not None:
        eligible = eligible[eligible["signal_timestamp"] > last_seen]
    if not eligible.empty:
        latest = eligible["signal_timestamp"].max()
        active.update(eligible.loc[eligible["signal_timestamp"] == latest, "code"])
    return universe.execution_codes(date, active)


def _load_or_generate_targets(
    config: MinuteBacktestConfig,
    reader: MinuteArchiveReader,
    codes: list[str],
    universe: HistoricalIndexUniverse | None = None,
) -> pd.DataFrame:
    if config.targets.mode in {"file", "strategy_output", "factor_layers"}:
        return _load_file_targets(config)
    assert config.targets.implementation is not None
    strategy = load_daily_minute_strategy(config.targets.implementation)
    strategy_bars = reader.iter_days(
        config.data.start_date,
        config.data.end_date,
        universe.codes_on if universe is not None else codes,
    )
    return generate_daily_strategy_targets(
        strategy, strategy_bars, codes,
        universe_for_date=universe.codes_on if universe is not None else None,
    )


def _load_file_targets(config: MinuteBacktestConfig) -> pd.DataFrame:
    assert config.targets.path is not None
    if config.targets.mode == "strategy_output":
        assert config.targets.rebalance_interval is not None
        return load_strategy_output_targets(
            config.targets.path, config.targets.rebalance_interval,
            config.targets.date_only_signal_time,
        )
    return load_target_weights(config.targets.path, config.targets.date_only_signal_time)


def _validate_strategy_entry(config: MinuteBacktestConfig) -> None:
    if config.targets.mode not in {"strategy"}:
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




def _run_factor_layers(
    config: MinuteBacktestConfig, reader: MinuteArchiveReader,
    codes: list[str], universe: HistoricalIndexUniverse | None,
) -> None:
    """分层可选；每层一套独立账户，但撮合、记账和普通策略完全一致。"""
    targets_by_layer = build_factor_layer_targets(
        config.targets.path,
        layer_count=config.targets.layer_count,
        factor_column=config.targets.factor_column,
        descending=config.targets.descending,
        signal_time=config.targets.date_only_signal_time,
        universe=universe,
    )
    layer_root = config.output_root / config.run_name
    if layer_root.exists():
        raise FileExistsError(f"分层结果目录已存在: {layer_root}")
    config.output_root.mkdir(parents=True, exist_ok=True)
    codes = sorted(set(codes) | set().union(*(set(frame["code"]) for frame in targets_by_layer.values())))
    trade_status = load_daily_trade_status(
        config.data.daily_status_path, codes,
        config.data.start_date, config.data.end_date,
    )
    actions = (
        load_corporate_actions(config.data.daily_root, codes)
        if config.data.daily_root is not None else None
    )
    snapshots = reader.source_snapshot(config.data.start_date, config.data.end_date)
    # 全部层成功后一次发布汇总目录，避免把半成品当作完整分层回测结果。
    with tempfile.TemporaryDirectory(
        prefix=f".{config.run_name}.", dir=config.output_root,
    ) as temporary_directory:
        working = Path(temporary_directory)
        all_nav, all_metrics = [], []
        for group, targets in targets_by_layer.items():
            if universe is not None:
                universe.validate_targets(targets)
            group_reader = MinuteArchiveReader(
                config.data.minute_root, config.data.cache_root, config.data.universe_name,
            )
            engine = MinuteBacktestEngine(config)
            stream_codes = (
                lambda date: _execution_codes_for_day(universe, engine, date, targets)
                if universe is not None else codes
            )
            stream = _bars_with_daily_status(
                group_reader.iter_days(config.data.start_date, config.data.end_date, stream_codes),
                trade_status,
            )
            result = engine.run_stream(
                stream, targets, actions, record_frequency="daily",
            )
            layer_config = replace(config, run_name=group, output_root=working)
            save_run_outputs(layer_config, result, group_reader.issues, snapshots)
            daily = result.nav[["timestamp", "nav", "cash"]].copy()
            daily["group"] = group
            daily["unit_nav"] = daily["nav"] / config.account.initial_capital
            daily["cumulative_return"] = daily["unit_nav"] - 1
            daily["daily_return"] = daily["unit_nav"].pct_change()
            if not daily.empty:
                daily.loc[daily.index[0], "daily_return"] = daily.iloc[0]["unit_nav"] - 1
            all_nav.append(daily)
            all_metrics.append({"group": group, **result.metrics})
        pd.concat(all_nav, ignore_index=True).to_parquet(working / "layer_daily_nav.parquet", index=False)
        pd.DataFrame(all_metrics).to_parquet(working / "layer_metrics.parquet", index=False)
        os.replace(working, layer_root)
    print(f"分层账户完成: {layer_root} ({len(targets_by_layer)} 个独立账户)")


if __name__ == "__main__":
    main()
