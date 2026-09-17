"""公开单组合和批量回测入口。"""

from src.backtest.account import run_account
from src.backtest.engine import (
    iter_backtests,
    iter_weight_backtests,
    run_backtests,
    run_weight_backtests,
)
from src.backtest.simple import run_simple

__all__ = [
    "run_account",
    "run_backtests",
    "run_simple",
    "run_weight_backtests",
    "iter_backtests",
    "iter_weight_backtests",
]
