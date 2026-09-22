"""分派第二批四类新数据因子的固定经济公式。"""

from __future__ import annotations

import pandas as pd

from factors.second_batch_factors.code.business_structure import (
    BUSINESS_STRUCTURE_FACTORS,
    calculate_business_structure_factor,
)
from factors.second_batch_factors.code.dividend import (
    DIVIDEND_FACTORS,
    calculate_dividend_factor,
)
from factors.second_batch_factors.code.insider_trade import (
    INSIDER_TRADE_FACTORS,
    calculate_insider_trade_factor,
)
from factors.second_batch_factors.code.profit_express import (
    PROFIT_EXPRESS_FACTORS,
    calculate_profit_express_factor,
)
from src.data.market_data import MarketData


def calculate_base_factor(
    factor_name: str,
    market_data: MarketData,
) -> pd.DataFrame:
    """按数据域把公开因子名称分派到对应公式。"""
    if factor_name in DIVIDEND_FACTORS:
        return calculate_dividend_factor(factor_name, market_data)
    if factor_name in PROFIT_EXPRESS_FACTORS:
        return calculate_profit_express_factor(factor_name, market_data)
    if factor_name in INSIDER_TRADE_FACTORS:
        return calculate_insider_trade_factor(factor_name, market_data)
    if factor_name in BUSINESS_STRUCTURE_FACTORS:
        return calculate_business_structure_factor(factor_name, market_data)
    raise ValueError(f"未知第二批新数据因子: {factor_name}")
