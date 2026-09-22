"""定义 Factor 信号转换为目标权重的最小组合构建接口。"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Mapping

import pandas as pd

from src.data.market_data import MarketData


class PortfolioRule(ABC):
    """保存策略配置，并约束单套调仓日期的目标权重构建接口。"""

    def __init__(self, config: Mapping[str, Any]) -> None:
        self.config = dict(config)
        self.name = self.config["name"]
        self.factor_name = self.config["factor_name"]
        self.benchmark_index = self.config["benchmark_index"]
        self.selection_diagnostics = pd.DataFrame()

    @abstractmethod
    def build_target_weights(
        self,
        signal_panel: pd.DataFrame,
        market_data: MarketData,
        rebalance_dates: pd.DatetimeIndex,
    ) -> pd.DataFrame:
        """把日频 Factor 信号转换为调仓日乘股票的目标权重。"""
        raise NotImplementedError
