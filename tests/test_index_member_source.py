"""验证历史指数成份数据源接口和正式文件合同。"""

from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

import pandas as pd

from scripts.sync_index_members import (
    FilesystemIndexMemberSource,
    SyntheticIndexMemberSource,
    sync_index_members,
)
from src.data.load_data import load_index_members
from src.data.process_data import build_membership_panel


class IndexMemberSourceTests(unittest.TestCase):
    """覆盖真实目录适配、synthetic 轮换和正式加载器兼容性。"""

    def test_synthetic_source_writes_pit_intervals_for_formal_loader(self) -> None:
        """模拟成员定期轮换后仍保持每个指数的目标成员数量。"""
        with TemporaryDirectory() as temporary_directory:
            output_root = Path(temporary_directory)
            index_codes = ["000906.SH", "000852.SH"]
            source = SyntheticIndexMemberSource(
                index_sizes={"000906.SH": 4, "000852.SH": 5},
                start_date=pd.Timestamp("2024-01-02"),
                end_date=pd.Timestamp("2025-01-02"),
                reserve_fraction=0.5,
                turnover_rate=0.25,
                rebalance_months=6,
            )

            summary = sync_index_members(source, output_root, index_codes)
            member_intervals = load_index_members(output_root, index_codes)
            trading_calendar = pd.bdate_range("2024-01-02", "2025-01-02")
            membership_panel = build_membership_panel(
                member_intervals=member_intervals,
                trading_calendar=trading_calendar,
                asset_codes=sorted(member_intervals["asset_code"].unique()),
                index_codes=index_codes,
            )

            self.assertEqual(summary["rows_by_index"], {"000906.SH": 6, "000852.SH": 7})
            for index_code, expected_size in [("000906.SH", 4), ("000852.SH", 5)]:
                index_membership = membership_panel.xs(
                    index_code,
                    axis=1,
                    level="index_code",
                )
                self.assertTrue((index_membership.sum(axis=1) == expected_size).all())

            written_columns = pd.read_csv(
                output_root / "index" / "members" / "000906.SH.csv"
            ).columns.tolist()
            self.assertEqual(
                written_columns,
                [
                    "s_con_indate",
                    "s_info_windcode",
                    "s_con_outdate",
                    "cur_sign",
                    "s_con_windcode",
                ],
            )

    def test_filesystem_source_reads_documented_member_layout(self) -> None:
        """外部数据根可通过统一接口复制到另一个正式数据目录。"""
        with TemporaryDirectory() as temporary_directory:
            workspace = Path(temporary_directory)
            source_root = workspace / "source"
            output_root = workspace / "output"
            source_directory = source_root / "index" / "members"
            source_directory.mkdir(parents=True)
            source_records = pd.DataFrame(
                {
                    "s_con_indate": ["20240102", "20240701"],
                    "s_info_windcode": ["stale", "stale"],
                    "s_con_outdate": ["20240701", pd.NA],
                    "cur_sign": [0, 1],
                    "s_con_windcode": ["000001.SZ", "000002.SZ"],
                }
            )
            source_records.to_csv(
                source_directory / "000906.SH.csv",
                index=False,
            )

            source = FilesystemIndexMemberSource(source_root)
            sync_index_members(source, output_root, ["000906.SH"])
            written_records = pd.read_csv(
                output_root / "index" / "members" / "000906.SH.csv",
                dtype="string",
            )

            self.assertEqual(
                written_records["s_info_windcode"].unique().tolist(),
                ["000906.SH"],
            )
            self.assertEqual(
                written_records["s_con_windcode"].tolist(),
                ["000001.SZ", "000002.SZ"],
            )

    def test_overlapping_member_intervals_are_rejected(self) -> None:
        """同一指数股票的重叠资格区间不能进入正式数据。"""

        class OverlappingSource:
            """返回两段重叠成员区间的测试数据源。"""

            def read(self, index_codes: list[str]) -> pd.DataFrame:
                return pd.DataFrame(
                    {
                        "s_info_windcode": [index_codes[0], index_codes[0]],
                        "s_con_windcode": ["000001.SZ", "000001.SZ"],
                        "s_con_indate": ["20240102", "20240601"],
                        "s_con_outdate": [pd.NA, pd.NA],
                    }
                )

        with TemporaryDirectory() as temporary_directory:
            with self.assertRaisesRegex(ValueError, "指数成份区间重叠"):
                sync_index_members(
                    OverlappingSource(),
                    Path(temporary_directory),
                    ["000906.SH"],
                )


if __name__ == "__main__":
    unittest.main()
