"""分派第一批三类新数据因子的固定经济公式。"""

from __future__ import annotations

import pandas as pd

from factors.first_batch_factors.code.enterprise_value import (
    ENTERPRISE_VALUE_FACTORS,
    calculate_enterprise_value_factor,
)
from factors.first_batch_factors.code.profit_notice import (
    PROFIT_NOTICE_FACTORS,
    calculate_profit_notice_factor,
)
from factors.first_batch_factors.code.repurchase import (
    REPURCHASE_FACTORS,
    calculate_repurchase_factor,
)
from src.data.market_data import MarketData


def calculate_base_factor(
    factor_name: str,
    market_data: MarketData,
) -> pd.DataFrame:
    """按数据域把公开因子名称分派到对应公式。"""
    if factor_name in PROFIT_NOTICE_FACTORS:
        return calculate_profit_notice_factor(factor_name, market_data)
    if factor_name in REPURCHASE_FACTORS:
        return calculate_repurchase_factor(factor_name, market_data)
    if factor_name in ENTERPRISE_VALUE_FACTORS:
        return calculate_enterprise_value_factor(factor_name, market_data)
    raise ValueError(f"未知第一批新数据因子: {factor_name}")
