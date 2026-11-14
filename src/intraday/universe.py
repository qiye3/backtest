"""按历史生效区间维护唯一的中证1000研究股票池。"""

from __future__ import annotations

from pathlib import Path
from typing import Iterable

import pandas as pd

from src.data.load_data import load_index_members
from src.intraday.targets import normalize_stock_code

CSI1000 = "000852.SH"


class HistoricalIndexUniverse:
    """复用研究数据层的历史成份区间，采用纳入日含、剔除日不含的口径。"""

    def __init__(self, members_root: str | Path, index_code: str = CSI1000) -> None:
        if index_code != CSI1000:
            raise ValueError("第一版历史股票池固定为中证1000（000852.SH）")
        self.index_code = index_code
        self.members_root = Path(members_root).expanduser().resolve()
        # 现有正式加载器期望的是 data_root/index/members/<index>.csv
        raw = load_index_members(self.members_root.parent.parent, [index_code])
        if raw.empty:
            raise ValueError(f"{index_code} 历史成份文件为空")
        raw["asset_code"] = raw["asset_code"].map(normalize_stock_code)
        raw = raw.sort_values(["asset_code", "start_date", "end_date"]).reset_index(drop=True)
        for _, group in raw.groupby("asset_code", sort=False):
            if group["start_date"].duplicated().any():
                raise ValueError("历史成份含重复的生效区间")
            previous_end = None
            for row in group.itertuples(index=False):
                if pd.notna(row.end_date) and row.end_date <= row.start_date:
                    raise ValueError("历史成份剔除日应晚于纳入日")
                if previous_end is not None and (pd.isna(previous_end) or row.start_date < previous_end):
                    raise ValueError("历史成份存在重叠区间")
                previous_end = row.end_date
        self.intervals = raw

    def codes_on(self, date: object) -> tuple[str, ...]:
        """返回指定交易日真实有效的历史成份；无覆盖则报错，不回填当前成份。"""
        day = pd.Timestamp(date).tz_localize(None).normalize() if pd.Timestamp(date).tzinfo else pd.Timestamp(date).normalize()
        selected = self.intervals[
            (self.intervals["start_date"] <= day)
            & (self.intervals["end_date"].isna() | (self.intervals["end_date"] > day))
        ]
        codes = tuple(sorted(selected["asset_code"].unique()))
        if not codes:
            raise ValueError(f"{day.date()} 无中证1000历史成份，不能使用现时名单替代")
        return codes

    def codes_between(self, start_date: object, end_date: object) -> tuple[str, ...]:
        start = pd.Timestamp(start_date).normalize()
        end = pd.Timestamp(end_date).normalize()
        selected = self.intervals[
            (self.intervals["start_date"] <= end)
            & (self.intervals["end_date"].isna() | (self.intervals["end_date"] > start))
        ]
        return tuple(sorted(selected["asset_code"].unique()))

    def validate_targets(self, targets: pd.DataFrame) -> None:
        """正权重必须在信号产生当天属于指数；零权重允许用于调出成份的清仓。"""
        positive = targets[targets["target_weight"] > 0]
        if positive.empty:
            return
        for timestamp, group in positive.groupby("signal_timestamp", sort=True):
            members = set(self.codes_on(timestamp))
            outside = sorted(set(group["code"]) - members)
            if outside:
                raise ValueError(
                    f"{timestamp} 目标正权重包含非当日中证1000成份: {outside[:12]}"
                )

    def execution_codes(self, trading_date: object, additional: Iterable[str] = ()) -> list[str]:
        """保留退出指数的持仓和未完成目标，以便继续估值及卖出。"""
        return sorted(set(self.codes_on(trading_date)) | {
            normalize_stock_code(code) for code in additional
        })
