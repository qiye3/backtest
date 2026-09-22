"""价值因子的日频历史分位算子。"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd


@dataclass(frozen=True)
class ValueBasePanel:
    """保存一个已按交易日对齐的价值基础因子。"""

    values: pd.DataFrame


def apply_value_operator(
    base_panel: ValueBasePanel,
    operator_name: str,
) -> pd.DataFrame:
    """应用原值或固定交易日窗口的逐股票历史分位算子。"""
    if operator_name == "raw":
        return base_panel.values.copy()
    windows = {
        "percentile_1y": (240, 120),
        "percentile_3y": (720, 360),
        "percentile_5y": (1200, 600),
    }
    if operator_name not in windows:
        raise ValueError(f"未知价值因子算子: {operator_name}")
    window, min_periods = windows[operator_name]
    return base_panel.values.rolling(
        window=window,
        min_periods=min_periods,
    ).rank(pct=True)
