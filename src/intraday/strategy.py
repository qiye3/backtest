"""使用分钟数据在每日收盘后生成下一交易日目标仓位。"""

from __future__ import annotations

import importlib
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from typing import Protocol

import pandas as pd

from src.intraday.config import StrategyImplementationConfig
from src.intraday.targets import normalize_stock_code, normalize_target_weights


@dataclass(frozen=True)
class DailyMinuteContext:
    """提供不含未来信息的策略运行上下文。"""

    completed_dates: tuple[pd.Timestamp, ...]
    universe_codes: tuple[str, ...]


class DailyMinuteStrategy(Protocol):
    """分钟衍生日频目标策略应实现的最小接口。"""

    def on_day_close(
        self,
        trading_date: pd.Timestamp,
        bars: pd.DataFrame,
        context: DailyMinuteContext,
    ) -> pd.DataFrame:
        """返回包含 ``code,target_weight`` 的完整目标仓位快照。"""


def load_daily_minute_strategy(
    implementation: StrategyImplementationConfig,
) -> DailyMinuteStrategy:
    """按配置动态加载策略，并用 params 作为构造参数。"""
    module = importlib.import_module(implementation.module)
    strategy_class = getattr(module, implementation.class_name)
    strategy = strategy_class(**implementation.params)
    if not callable(getattr(strategy, "on_day_close", None)):
        raise TypeError(
            f"{implementation.module}.{implementation.class_name} "
            "必须实现 on_day_close()"
        )
    return strategy


def generate_daily_strategy_targets(
    strategy: DailyMinuteStrategy,
    daily_bars: Iterable[pd.DataFrame],
    universe_codes: Sequence[str],
    universe_for_date: Callable[[pd.Timestamp], Sequence[str]] | None = None,
) -> pd.DataFrame:
    """逐日调用策略；D 日完整分钟数据产生的信号最早在 D+1 成交。"""
    normalized_universe = tuple(sorted({normalize_stock_code(code) for code in universe_codes}))
    completed_dates: list[pd.Timestamp] = []
    target_frames: list[pd.DataFrame] = []

    for bars in daily_bars:
        if bars.empty:
            continue
        timestamps = pd.to_datetime(bars["timestamp"])
        if timestamps.dt.tz is None:
            raise ValueError("策略分钟行情 timestamp 必须带时区")
        trading_dates = timestamps.dt.tz_localize(None).dt.normalize().unique()
        if len(trading_dates) != 1:
            raise ValueError("分钟日频策略每次只能接收一个交易日")
        trading_date = pd.Timestamp(trading_dates[0])
        active_codes = (
            tuple(sorted({normalize_stock_code(code) for code in universe_for_date(trading_date)}))
            if universe_for_date is not None else normalized_universe
        )
        context = DailyMinuteContext(
            completed_dates=tuple(completed_dates),
            universe_codes=active_codes,
        )
        active_bars = bars[bars["code"].isin(active_codes)].copy()
        daily_target = strategy.on_day_close(trading_date, active_bars, context)
        target_frames.append(
            _stamp_daily_target(daily_target, timestamps.max(), active_codes)
        )
        completed_dates.append(trading_date)

    if not target_frames:
        raise ValueError("分钟日频策略没有产生任何目标仓位")
    targets = pd.concat(target_frames, ignore_index=True)
    return normalize_target_weights(targets, "15:00:00")


def _stamp_daily_target(
    target: pd.DataFrame,
    signal_timestamp: pd.Timestamp,
    universe_codes: tuple[str, ...],
) -> pd.DataFrame:
    if not isinstance(target, pd.DataFrame):
        raise TypeError("on_day_close() 必须返回 pandas.DataFrame")
    required = {"code", "target_weight"}
    missing = required - set(target)
    if missing:
        raise ValueError(f"分钟日频策略输出缺少字段: {sorted(missing)}")
    stamped = target.loc[:, ["code", "target_weight"]].copy()
    stamped["code"] = stamped["code"].map(normalize_stock_code)
    unknown_codes = sorted(set(stamped["code"]) - set(universe_codes))
    if unknown_codes:
        raise ValueError(f"分钟日频策略输出股票不在研究股票池: {unknown_codes}")
    if stamped.empty:
        raise ValueError(
            "分钟日频策略必须返回完整目标；清仓时请为股票池输出零权重"
        )
    stamped.insert(0, "signal_timestamp", signal_timestamp)
    return stamped
