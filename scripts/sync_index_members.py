"""同步历史指数成份区间到 factor-backtest 正式数据目录。"""

from __future__ import annotations

import argparse
import json
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Protocol

import pandas as pd

DOCUMENTED_INDEX_CODES = (
    "000300.SH",
    "000905.SH",
    "000906.SH",
    "000852.SH",
    "000932.SH",
)
DEFAULT_SYNTHETIC_INDEX_SIZES = {
    "000300.SH": 300,
    "000905.SH": 500,
    "000906.SH": 800,
    "000852.SH": 1000,
    "000932.SH": 2000,
}
OUTPUT_COLUMNS = [
    "s_con_indate",
    "s_info_windcode",
    "s_con_outdate",
    "cur_sign",
    "s_con_windcode",
]


class IndexMemberSource(Protocol):
    """定义历史指数成份数据源必须提供的读取合同。"""

    def read(self, index_codes: Sequence[str]) -> pd.DataFrame:
        """返回包含指数代码、成份代码和纳入剔除日期的长表。"""


class FilesystemIndexMemberSource:
    """读取数据字典约定的 ``index/members/<code>.csv``。"""

    def __init__(self, source_root: str | Path) -> None:
        self.source_root = Path(source_root).expanduser().resolve()

    def read(self, index_codes: Sequence[str]) -> pd.DataFrame:
        """读取多个指数文件并补齐文件名隐含的指数代码。"""
        member_parts = []
        member_directory = self.source_root / "index" / "members"
        for index_code in index_codes:
            member_path = member_directory / f"{index_code}.csv"
            member_records = pd.read_csv(
                member_path,
                dtype={
                    "s_info_windcode": "string",
                    "s_con_windcode": "string",
                    "s_con_indate": "string",
                    "s_con_outdate": "string",
                },
            )
            member_records["s_info_windcode"] = index_code
            member_parts.append(member_records)
        return pd.concat(member_parts, ignore_index=True)


class SyntheticIndexMemberSource:
    """生成带定期调入调出的可重复历史成份区间。"""

    def __init__(
        self,
        index_sizes: Mapping[str, int],
        start_date: pd.Timestamp,
        end_date: pd.Timestamp,
        reserve_fraction: float = 0.2,
        turnover_rate: float = 0.1,
        rebalance_months: int = 6,
    ) -> None:
        self.index_sizes = dict(index_sizes)
        self.start_date = start_date.normalize()
        self.end_date = end_date.normalize()
        self.reserve_fraction = reserve_fraction
        self.turnover_rate = turnover_rate
        self.rebalance_months = rebalance_months
        self._validate_settings()

    def read(self, index_codes: Sequence[str]) -> pd.DataFrame:
        """按指数生成恒定目标数量、成员会轮换的区间记录。"""
        member_parts = []
        code_offset = 1
        for index_code in index_codes:
            target_size = self.index_sizes[index_code]
            reserve_size = max(1, round(target_size * self.reserve_fraction))
            candidate_count = target_size + reserve_size
            candidate_codes = [
                f"{stock_number:06d}.SZ"
                for stock_number in range(code_offset, code_offset + candidate_count)
            ]
            code_offset += candidate_count
            member_parts.append(
                self._generate_index_intervals(
                    index_code=index_code,
                    candidate_codes=candidate_codes,
                    target_size=target_size,
                )
            )
        return pd.concat(member_parts, ignore_index=True)

    def _generate_index_intervals(
        self,
        index_code: str,
        candidate_codes: Sequence[str],
        target_size: int,
    ) -> pd.DataFrame:
        """轮换候选池并记录每段左闭右开的成员资格。"""
        active_codes = list(candidate_codes[:target_size])
        reserve_codes = list(candidate_codes[target_size:])
        interval_records = [
            {
                "s_con_indate": self.start_date,
                "s_info_windcode": index_code,
                "s_con_outdate": pd.NaT,
                "s_con_windcode": asset_code,
            }
            for asset_code in active_codes
        ]
        open_interval_positions = {
            record["s_con_windcode"]: position for position, record in enumerate(interval_records)
        }
        turnover_count = min(
            len(reserve_codes),
            max(1, round(target_size * self.turnover_rate)),
        )

        for rebalance_date in self._rebalance_dates():
            exiting_codes = active_codes[:turnover_count]
            entering_codes = reserve_codes[:turnover_count]
            for exiting_code in exiting_codes:
                interval_position = open_interval_positions.pop(exiting_code)
                interval_records[interval_position]["s_con_outdate"] = rebalance_date
            for entering_code in entering_codes:
                open_interval_positions[entering_code] = len(interval_records)
                interval_records.append(
                    {
                        "s_con_indate": rebalance_date,
                        "s_info_windcode": index_code,
                        "s_con_outdate": pd.NaT,
                        "s_con_windcode": entering_code,
                    }
                )
            active_codes = active_codes[turnover_count:] + entering_codes
            reserve_codes = reserve_codes[turnover_count:] + exiting_codes

        return pd.DataFrame(interval_records)

    def _rebalance_dates(self) -> list[pd.Timestamp]:
        """生成不包含研究起点、且不晚于研究终点的调仓日期。"""
        rebalance_dates = []
        rebalance_date = self.start_date + pd.DateOffset(months=self.rebalance_months)
        while rebalance_date <= self.end_date:
            rebalance_dates.append(rebalance_date)
            rebalance_date += pd.DateOffset(months=self.rebalance_months)
        return rebalance_dates

    def _validate_settings(self) -> None:
        """校验 synthetic 后端会影响成员数量和轮换节奏的参数。"""
        if self.end_date < self.start_date:
            raise ValueError("synthetic 成份结束日期不能早于开始日期")
        if not self.index_sizes or any(size <= 0 for size in self.index_sizes.values()):
            raise ValueError("synthetic 每个指数的目标成员数必须为正整数")
        if not 0 < self.reserve_fraction <= 1:
            raise ValueError("synthetic reserve_fraction 必须在 (0, 1] 内")
        if not 0 < self.turnover_rate <= 1:
            raise ValueError("synthetic turnover_rate 必须在 (0, 1] 内")
        if self.rebalance_months <= 0:
            raise ValueError("synthetic rebalance_months 必须为正整数")


def sync_index_members(
    source: IndexMemberSource,
    output_root: str | Path,
    index_codes: Sequence[str],
) -> dict[str, object]:
    """读取、校验并覆盖写入正式历史成份文件。"""
    normalized_records = _normalize_member_records(source.read(index_codes))
    requested_records = normalized_records[
        normalized_records["s_info_windcode"].isin(index_codes)
    ].copy()
    missing_indices = sorted(set(index_codes) - set(requested_records["s_info_windcode"]))
    if missing_indices:
        raise ValueError(f"数据源缺少指数成份记录: {missing_indices}")

    member_directory = Path(output_root).expanduser().resolve() / "index" / "members"
    member_directory.mkdir(parents=True, exist_ok=True)
    rows_by_index = {}
    for index_code in index_codes:
        index_records = requested_records[
            requested_records["s_info_windcode"] == index_code
        ].sort_values(["s_con_indate", "s_con_windcode"])
        index_records.to_csv(member_directory / f"{index_code}.csv", index=False)
        rows_by_index[index_code] = len(index_records)

    exit_dates = requested_records["s_con_outdate"].dropna()
    last_exit_date = None if exit_dates.empty else exit_dates.max()

    return {
        "output_directory": str(member_directory),
        "index_codes": list(index_codes),
        "rows_by_index": rows_by_index,
        "total_rows": len(requested_records),
        "start_date": requested_records["s_con_indate"].min(),
        "end_date": last_exit_date,
    }


def _normalize_member_records(member_records: pd.DataFrame) -> pd.DataFrame:
    """把真实或模拟数据统一为文档约定的五字段成员格式。"""
    required_columns = {
        "s_info_windcode",
        "s_con_windcode",
        "s_con_indate",
        "s_con_outdate",
    }
    missing_columns = sorted(required_columns - set(member_records.columns))
    if missing_columns:
        raise ValueError(f"指数成份数据缺少字段: {missing_columns}")

    normalized_records = member_records.loc[:, list(required_columns)].copy()
    normalized_records["s_info_windcode"] = normalized_records["s_info_windcode"].astype("string")
    normalized_records["s_con_windcode"] = normalized_records["s_con_windcode"].astype("string")
    for date_column in ["s_con_indate", "s_con_outdate"]:
        normalized_records[date_column] = pd.to_datetime(
            normalized_records[date_column],
            format="%Y%m%d",
            errors="coerce",
        )

    invalid_required = (
        normalized_records[["s_info_windcode", "s_con_windcode", "s_con_indate"]].isna().any(axis=1)
    )
    if invalid_required.any():
        raise ValueError("指数成份数据包含缺失或无效的指数、股票或纳入日期")
    invalid_intervals = normalized_records["s_con_outdate"].notna() & (
        normalized_records["s_con_outdate"] <= normalized_records["s_con_indate"]
    )
    if invalid_intervals.any():
        raise ValueError("指数成份数据包含剔除日期不晚于纳入日期的区间")
    duplicate_intervals = normalized_records.duplicated(
        ["s_info_windcode", "s_con_windcode", "s_con_indate"]
    )
    if duplicate_intervals.any():
        raise ValueError("指数成份数据包含重复的指数、股票和纳入日期")

    _validate_non_overlapping_intervals(normalized_records)
    normalized_records["cur_sign"] = normalized_records["s_con_outdate"].isna().astype(int)
    for date_column in ["s_con_indate", "s_con_outdate"]:
        normalized_records[date_column] = normalized_records[date_column].dt.strftime("%Y%m%d")
    return normalized_records[OUTPUT_COLUMNS]


def _validate_non_overlapping_intervals(member_records: pd.DataFrame) -> None:
    """拒绝同一指数股票相互重叠的 PIT 成员区间。"""
    group_columns = ["s_info_windcode", "s_con_windcode"]
    for group_key, stock_intervals in member_records.groupby(group_columns):
        ordered_intervals = stock_intervals.sort_values("s_con_indate")
        previous_end_dates = ordered_intervals["s_con_outdate"].shift()
        overlapping = previous_end_dates.isna() & (
            ordered_intervals.index != ordered_intervals.index[0]
        )
        overlapping |= previous_end_dates.notna() & (
            ordered_intervals["s_con_indate"] < previous_end_dates
        )
        if overlapping.any():
            raise ValueError(f"指数成份区间重叠: {group_key}")


def _parse_index_sizes(
    specifications: Sequence[str],
    index_codes: Sequence[str],
) -> dict[str, int]:
    """解析 ``指数代码=目标数量``，未指定时使用指数常见规模。"""
    index_sizes = {
        index_code: DEFAULT_SYNTHETIC_INDEX_SIZES[index_code] for index_code in index_codes
    }
    for specification in specifications:
        index_code, separator, raw_size = specification.partition("=")
        if not separator or index_code not in index_sizes:
            raise ValueError(f"synthetic-index-size 格式或指数无效: {specification}")
        index_sizes[index_code] = int(raw_size)
    return index_sizes


def _build_source(arguments: argparse.Namespace) -> IndexMemberSource:
    """根据 CLI 参数构造真实文件或 synthetic 数据源。"""
    if arguments.source == "filesystem":
        if arguments.source_root is None:
            raise ValueError("filesystem 数据源必须提供 --source-root")
        return FilesystemIndexMemberSource(arguments.source_root)

    index_sizes = _parse_index_sizes(
        arguments.synthetic_index_size,
        arguments.index_code,
    )
    return SyntheticIndexMemberSource(
        index_sizes=index_sizes,
        start_date=pd.Timestamp(arguments.start),
        end_date=pd.Timestamp(arguments.end),
        reserve_fraction=arguments.synthetic_reserve_fraction,
        turnover_rate=arguments.synthetic_turnover_rate,
        rebalance_months=arguments.synthetic_rebalance_months,
    )


def main() -> None:
    """解析数据源、指数范围和正式输出目录并执行同步。"""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", choices=["filesystem", "synthetic"], required=True)
    parser.add_argument("--source-root", type=Path)
    parser.add_argument("--output-root", required=True, type=Path)
    parser.add_argument(
        "--index-code",
        action="append",
        choices=DOCUMENTED_INDEX_CODES,
        default=None,
    )
    parser.add_argument("--start", default="2010-01-01")
    parser.add_argument("--end", default=str(pd.Timestamp.today().date()))
    parser.add_argument("--synthetic-index-size", action="append", default=[])
    parser.add_argument("--synthetic-reserve-fraction", type=float, default=0.2)
    parser.add_argument("--synthetic-turnover-rate", type=float, default=0.1)
    parser.add_argument("--synthetic-rebalance-months", type=int, default=6)
    arguments = parser.parse_args()
    if arguments.index_code is None:
        arguments.index_code = list(DOCUMENTED_INDEX_CODES)

    source = _build_source(arguments)
    summary = sync_index_members(
        source=source,
        output_root=arguments.output_root,
        index_codes=arguments.index_code,
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
