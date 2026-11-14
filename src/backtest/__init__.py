"""正式策略回测统一使用分钟成交账户；因子评价位于 group_return。"""

from src.backtest.engine import run_portfolio

__all__ = ["run_portfolio"]
