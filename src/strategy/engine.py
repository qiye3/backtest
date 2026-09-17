"""按策略调仓规则把一个 Factor 面板转换成多套目标权重。"""

from __future__ import annotations

from typing import Any, Mapping

import pandas as pd

from src.backtest.targets import rebalance_dates
from src.data.market_data import MarketData
from src.strategy.base import PortfolioRule


def build_strategy_targets(
    strategy: PortfolioRule,
    signal_panel: pd.DataFrame,
    market_data: MarketData,
    settings: Mapping[str, Any],
) -> dict[str, Any]:
    """构建一个策略在全部配置调仓间隔下的目标权重。"""
    rebalance = strategy.config["rebalance"]
    period_targets = {}
    for interval in rebalance["intervals"]:
        target_dates = rebalance_dates(
            calendar=market_data.calendar,
            start=settings["start"],
            end=settings["end"],
            rebalance=rebalance,
            interval=interval,
            initial_entry="first_rebalance",
        )
        period_targets[interval] = strategy.build_target_weights(
            signal_panel=signal_panel,
            market_data=market_data,
            rebalance_dates=target_dates,
        )

    return {
        "strategy_name": strategy.name,
        "factor_name": strategy.factor_name,
        "benchmark_index": strategy.benchmark_index,
        "rebalance_frequency": rebalance["frequency"],
        "periods": period_targets,
    }
