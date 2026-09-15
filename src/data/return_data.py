"""读取 evaluation 与 simple backtest 共用的外部日收益面板。"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd


def load_return_panel(path: str | Path) -> pd.DataFrame:
    """
    读取日期乘股票的日收益宽表。

    索引必须是唯一且升序的交易日，列必须是唯一股票代码。日期 t 的值表示
    t-1 收盘至 t 收盘的收益，因此未来区间从评价日后一交易日开始累计。
    """
    return_panel = pd.read_parquet(Path(path))
    if not isinstance(return_panel.index, pd.DatetimeIndex):
        raise ValueError("外部收益 Parquet 的索引必须是 DatetimeIndex")
    if return_panel.index.has_duplicates or not return_panel.index.is_monotonic_increasing:
        raise ValueError("外部收益日期必须唯一且按时间升序排列")
    if return_panel.columns.has_duplicates:
        raise ValueError("外部收益股票代码不能重复")

    return_panel = return_panel.astype(float)
    return_values = return_panel.to_numpy()
    if np.isinf(return_values).any():
        raise ValueError("外部收益只能包含有限值或 NaN")
    finite_returns = return_values[np.isfinite(return_values)]
    if (finite_returns <= -1).any():
        raise ValueError("外部单日收益必须大于 -1")
    return_panel.columns = pd.Index(
        return_panel.columns.astype(str),
        name="asset_code",
    )
    return_panel.index = pd.DatetimeIndex(return_panel.index, name="date")
    return return_panel
