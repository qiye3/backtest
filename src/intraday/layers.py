"""因子分层是可选的目标仓位生成器；所有分层共享正式分钟成交账户引擎。"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from src.intraday.targets import normalize_stock_code, normalize_target_weights
from src.intraday.universe import HistoricalIndexUniverse


def build_factor_layer_targets(
    factor_path: str | Path,
    *,
    layer_count: int = 10,
    factor_column: str = "factor_value",
    descending: bool = False,
    signal_time: str = "15:00:00",
    universe: HistoricalIndexUniverse | None = None,
) -> dict[str, pd.DataFrame]:
    """读取日频因子宽表或长表，按历史当日有效股票分组并等权构建目标。"""
    if layer_count < 2:
        raise ValueError("至少需要两个分组")
    path = Path(factor_path)
    if path.suffix.lower() == ".parquet":
        source = pd.read_parquet(path)
    elif path.suffix.lower() == ".csv":
        source = pd.read_csv(path, dtype={"code": "string", "stock_code": "string"})
    else:
        raise ValueError("因子文件只支持 CSV 和 Parquet")
    if {"date", "code", factor_column}.issubset(source.columns):
        factor = source[["date", "code", factor_column]].copy()
    elif {"date", "stock_code", factor_column}.issubset(source.columns):
        factor = source[["date", "stock_code", factor_column]].rename(columns={"stock_code": "code"})
    else:
        # 原因子框架使用 DatetimeIndex × 股票列的宽表 Parquet。
        if not isinstance(source.index, pd.DatetimeIndex):
            raise ValueError("因子文件需要 date/code/因子值长表，或日期索引×股票代码宽表")
        factor = source.stack(dropna=True).rename(factor_column).reset_index()
        factor.columns = ["date", "code", factor_column]
    if factor.empty:
        raise ValueError("因子数据为空")
    factor["date"] = pd.to_datetime(factor["date"], errors="raise").dt.normalize()
    if factor["date"].dt.tz is not None:
        raise ValueError("因子日期应为无时区交易日期")
    factor["code"] = factor["code"].map(normalize_stock_code)
    factor[factor_column] = pd.to_numeric(factor[factor_column], errors="raise")
    factor = factor[np.isfinite(factor[factor_column])].copy()
    if factor.duplicated(["date", "code"]).any():
        raise ValueError("一个交易日的同一股票不能出现多个因子值")
    if factor.empty:
        raise ValueError("因子数据没有有效的非空数值")
    rows = {f"G{i:02d}": [] for i in range(1, layer_count + 1)}
    prior_codes = {group: set() for group in rows}
    for day, group in factor.groupby("date", sort=True):
        if universe is not None:
            permitted = set(universe.codes_on(day))
            group = group[group["code"].isin(permitted)]
        if group.empty:
            raise ValueError(f"{day.date()} 没有历史成份内的有效因子值")
        # 同分值用代码打破平局，保证按日期重复运行结果稳定。
        ordered = group.sort_values(
            [factor_column, "code"], ascending=[not descending, True], kind="stable",
        )
        partitions = np.array_split(ordered["code"].to_numpy(dtype=str), layer_count)
        for name, codes in zip(rows, partitions):
            current_codes = set(codes)
            # 用零权重显式标记上期持仓的清仓；无新股时也会产生清仓信号。
            all_codes = sorted(current_codes | prior_codes[name])
            for code in all_codes:
                rows[name].append({
                    "signal_timestamp": str(day.date()),
                    "code": code,
                    "target_weight": (1.0 / len(current_codes) if code in current_codes else 0.0),
                })
            prior_codes[name] = current_codes
    return {
        name: normalize_target_weights(
            pd.DataFrame(records, columns=["signal_timestamp", "code", "target_weight"]),
            signal_time,
        )
        for name, records in rows.items()
    }
