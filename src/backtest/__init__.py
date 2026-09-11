"""公开单组合和批量回测入口。"""

from src.backtest.account import run_account
from src.backtest.engine import run_backtests
from src.backtest.simple import run_simple

__all__ = ["run_account", "run_backtests", "run_simple"]
