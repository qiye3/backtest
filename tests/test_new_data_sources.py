"""验证更新数据字典新增来源的读取、面板和明细接口。"""

from __future__ import annotations

import shutil
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

import pandas as pd
import yaml

from src.data.load_data import DATA_SOURCE_SPECS, load_data
from src.data.market_data import MarketData
from src.data.process_data import build_source_panel

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SYNTHETIC_DATA_ROOT = PROJECT_ROOT / "examples" / "data"

NEW_SOURCE_NAMES = (
    "dividend_wind",
    "exright_dividend",
    "repo_summary",
    "repo_wind",
    "actual_controller",
    "management_latest",
    "management_reward",
    "financial_ttm",
    "profit_express",
    "profit_notice",
    "customer",
    "customer_summary",
    "mb_consist",
    "mb_product_rank",
    "mb_region_rank",
    "supplier",
    "supplier_summary",
    "major_holder_trade",
    "pledge",
    "ev_indicator",
)


class NewDataSourceTests(unittest.TestCase):
    """覆盖新增来源的标准键、时间语义和缓存读取。"""

    def test_all_new_sources_load_from_documented_paths(self) -> None:
        """20 个来源都应按数据字典路径读取并生成对应标准键。"""
        with TemporaryDirectory() as temporary_directory:
            data_root = Path(temporary_directory)

            for source_name in NEW_SOURCE_NAMES:
                with self.subTest(source_name=source_name):
                    self._write_source_file(data_root, source_name)
                    source_data = load_data(
                        data_root=data_root,
                        source_name=source_name,
                        source_config={"fields": ["test_value"]},
                        start_date=pd.Timestamp("2024-01-01"),
                        end_date=pd.Timestamp("2024-12-31"),
                        universe_codes=["000001.SZ"],
                    )

                    self.assertEqual(len(source_data), 1)
                    self.assertEqual(source_data.loc[0, "test_value"], 1.0)
                    source_spec = DATA_SOURCE_SPECS[source_name]
                    if source_spec.kind == "records":
                        self.assertNotIn("date", source_data.columns)
                    else:
                        self.assertIn("date", source_data.columns)

    def test_new_announcement_panels_start_next_trading_day(self) -> None:
        """快报、预告和 TTM 公告不能在公告日当日进入因子面板。"""
        trading_calendar = pd.DatetimeIndex(
            ["2024-02-01", "2024-02-02", "2024-02-05"],
            name="date",
        )
        source_data = pd.DataFrame(
            {
                "date": pd.to_datetime(["2024-02-02"]),
                "asset_code": ["000001.SZ"],
                "report_period": pd.to_datetime(["2023-12-31"]),
                "test_value": [12.0],
                "source_order": [0],
            }
        )

        for source_name in ("financial_ttm", "profit_express", "profit_notice"):
            with self.subTest(source_name=source_name):
                source_panel = build_source_panel(
                    source_name=source_name,
                    source_data=source_data,
                    source_fields=["test_value"],
                    trading_calendar=trading_calendar,
                    asset_codes=["000001.SZ"],
                )
                values = source_panel["test_value"]["000001.SZ"]
                self.assertTrue(pd.isna(values.loc["2024-02-02"]))
                self.assertEqual(values.loc["2024-02-05"], 12.0)

    def test_point_event_panels_do_not_forward_fill(self) -> None:
        """除权除息事件只在实施日有值，企业价值仍保持逐日原始缺失。"""
        trading_calendar = pd.DatetimeIndex(
            ["2024-02-01", "2024-02-02", "2024-02-05"],
            name="date",
        )
        source_data = pd.DataFrame(
            {
                "date": pd.to_datetime(["2024-02-02"]),
                "asset_code": ["000001.SZ"],
                "test_value": [3.0],
                "source_order": [0],
            }
        )

        for source_name in ("exright_dividend", "ev_indicator"):
            with self.subTest(source_name=source_name):
                source_panel = build_source_panel(
                    source_name=source_name,
                    source_data=source_data,
                    source_fields=["test_value"],
                    trading_calendar=trading_calendar,
                    asset_codes=["000001.SZ"],
                )
                values = source_panel["test_value"]["000001.SZ"]
                self.assertEqual(values.loc["2024-02-02"], 3.0)
                self.assertTrue(pd.isna(values.loc["2024-02-05"]))

    def test_market_data_preserves_duplicate_detail_records_and_reuses_cache(
        self,
    ) -> None:
        """明细缓存应保留同股同日多行，并能被下一份配置直接复用。"""
        with TemporaryDirectory() as temporary_directory:
            workspace = Path(temporary_directory)
            data_root = workspace / "raw_data"
            cache_root = workspace / "cache"
            shutil.copytree(SYNTHETIC_DATA_ROOT, data_root)
            trade_directory = data_root / "stock" / "ownership" / "major_holder_trade"
            trade_directory.mkdir(parents=True)
            pd.DataFrame(
                {
                    "stock_code": ["000001.SZ", "000001.SZ"],
                    "ann_dt": [20240202, 20240202],
                    "transact_quantity": [100.0, 200.0],
                }
            ).to_csv(trade_directory / "major_holder_trade_2024.csv", index=False)

            config_path = workspace / "run.yaml"
            config = self._market_config(data_root, cache_root)
            config_path.write_text(
                yaml.safe_dump(config, allow_unicode=True, sort_keys=False),
                encoding="utf-8",
            )
            market_data = MarketData.from_yaml(config_path)

            trade_records = market_data.get_records("major_holder_trade")
            self.assertEqual(trade_records["transact_quantity"].tolist(), [100.0, 200.0])
            self.assertTrue((cache_root / "major_holder_trade.parquet").exists())
            with self.assertRaisesRegex(ValueError, "get_records"):
                market_data.get_panel("major_holder_trade", "transact_quantity")
            with self.assertRaisesRegex(ValueError, "get_panel"):
                market_data.get_records("stock_quote")

            with patch(
                "src.data.market_data.load_data",
                side_effect=AssertionError("完整缓存命中时不应重新读取 CSV"),
            ):
                cached_market_data = MarketData.from_yaml(config_path)
            pd.testing.assert_frame_equal(
                cached_market_data.get_records("major_holder_trade"),
                trade_records,
            )

    @staticmethod
    def _write_source_file(data_root: Path, source_name: str) -> None:
        """按来源定义写入一行使用标准字段名的合成 CSV。"""
        source_spec = DATA_SOURCE_SPECS[source_name]
        source_directory = data_root / source_spec.relative_directory
        source_directory.mkdir(parents=True, exist_ok=True)
        file_name = source_spec.file_pattern.replace("*", "2024")

        source_record: dict[str, object] = {"test_value": 1.0}
        if source_spec.asset_column is not None:
            source_record[source_spec.asset_column] = "000001.SZ"
        if source_spec.date_column is not None:
            source_record[source_spec.date_column] = 20240202
        if source_spec.report_period_column is not None:
            report_period = 20231231
            if source_spec.kind == "records" and source_spec.date_column is None:
                report_period = 20241231
            source_record[source_spec.report_period_column] = report_period
        if source_spec.operation_time_column is not None:
            source_record[source_spec.operation_time_column] = "2024-02-02 18:00:00"
        pd.DataFrame([source_record]).to_csv(source_directory / file_name, index=False)

    @staticmethod
    def _market_config(data_root: Path, cache_root: Path) -> dict:
        """构造包含一个明细来源的最小 MarketData 配置。"""
        return {
            "market_data": {
                "source_root": str(data_root),
                "cache_root": str(cache_root),
                "start_date": "2024-01-02",
                "end_date": "2024-06-28",
                "benchmark_index": "000906.SH",
                "universe_indices": ["000906.SH", "000852.SH"],
                "sources": {
                    "index_price": {
                        "codes": ["000906.SH"],
                        "fields": ["S_DQ_CLOSE"],
                    },
                    "stock_quote": {"fields": ["S_DQ_ADJCLOSE"]},
                    "major_holder_trade": {
                        "fields": ["transact_quantity"],
                    },
                },
            }
        }


if __name__ == "__main__":
    unittest.main()
