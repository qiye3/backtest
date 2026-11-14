"""统一的正式回测入口。

原日频 simple/account 引擎已退役；正式净值全部由 MinuteBacktestEngine 给出。
"""

from __future__ import annotations

from collections.abc import Iterable

import pandas as pd

from src.intraday.config import MinuteBacktestConfig
from src.intraday.engine import BacktestResult, MinuteBacktestEngine


def run_portfolio(
    config: MinuteBacktestConfig,
    daily_bars: Iterable[pd.DataFrame],
    target_weights: pd.DataFrame,
    corporate_actions: pd.DataFrame | None = None,
    *,
    record_frequency: str = "daily",
) -> BacktestResult:
    """直接运行一套策略目标权重；分层也只需为每层单独调用此函数。"""
    return MinuteBacktestEngine(config).run_stream(
        daily_bars, target_weights, corporate_actions,
        record_frequency=record_frequency,
    )

