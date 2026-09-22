"""公开 Factor 信号到目标权重的策略构建接口。"""

from src.strategy.base import PortfolioRule
from src.strategy.config import load_strategies, load_strategy
from src.strategy.engine import build_strategy_targets
from src.strategy.evaluation import calculate_concentration, calculate_weight_deviation
from src.strategy.exposure import (
    calculate_industry_exposure,
    calculate_style_exposure,
)

__all__ = [
    "PortfolioRule",
    "build_strategy_targets",
    "calculate_concentration",
    "calculate_industry_exposure",
    "calculate_style_exposure",
    "calculate_weight_deviation",
    "load_strategies",
    "load_strategy",
]
