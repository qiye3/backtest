"""验证不同 YAML 复用同一套来源级 MarketData 缓存。"""

from __future__ import annotations

import json
import shutil
import unittest
from copy import deepcopy
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

import pandas as pd
import yaml

from src.data import market_data as market_data_module
from src.data.market_data import MarketData
from src.data.style_exposure import load_or_build_style_exposures

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SYNTHETIC_DATA_ROOT = PROJECT_ROOT / "examples" / "data"


class MarketDataCacheTests(unittest.TestCase):
    """验证共享、扩容、切片和来源口径冲突。"""

    def test_style_exposure_cache_reuses_and_refreshes_fixed_file(self) -> None:
        """风格暴露命中固定文件直接复用，refresh 时覆盖重建。"""
        dates = pd.DatetimeIndex(["2024-01-02"], name="date")
        stock_codes = pd.Index(["000001.SZ"], name="asset_code")
        membership = pd.DataFrame(True, index=dates, columns=stock_codes)
        style_columns = pd.MultiIndex.from_product(
            [["Size"], stock_codes],
            names=["style_name", "asset_code"],
        )
        first_exposures = pd.DataFrame(
            [[1.0]],
            index=dates,
            columns=style_columns,
        )
        refreshed_exposures = pd.DataFrame(
            [[2.0]],
            index=dates,
            columns=style_columns,
        )
        with TemporaryDirectory() as temporary_directory:
            market_data = MarketData(
                source_panels={},
                calendar=dates,
                membership=membership,
                benchmark_index="000906.SH",
                cache_directory=Path(temporary_directory),
            )
            with patch(
                "src.data.style_exposure.build_style_exposures",
                return_value=first_exposures,
            ) as build_exposures:
                first_result = load_or_build_style_exposures(market_data)
                cached_result = load_or_build_style_exposures(market_data)
            self.assertEqual(build_exposures.call_count, 1)
            pd.testing.assert_frame_equal(first_result, cached_result)

            with patch(
                "src.data.style_exposure.build_style_exposures",
                return_value=refreshed_exposures,
            ) as refresh_exposures:
                refreshed_result = load_or_build_style_exposures(
                    market_data,
                    refresh=True,
                )
            refresh_exposures.assert_called_once_with(market_data)
            pd.testing.assert_frame_equal(refreshed_result, refreshed_exposures)

    def test_static_fields_and_forecast_horizons_share_cache(self) -> None:
        """证券主数据应广播到日频，多期限预期缓存可按请求切片。"""
        with TemporaryDirectory() as temporary_directory:
            workspace = Path(temporary_directory)
            data_root = workspace / "raw_data"
            cache_root = workspace / "market_cache"
            shutil.copytree(SYNTHETIC_DATA_ROOT, data_root)
            self._add_static_and_consensus_data(data_root)

            config_data = self._market_config(data_root, cache_root)
            config_data["market_data"]["sources"].update(
                {
                    "stock_basic": {"fields": ["LISTDATE"]},
                    "consensus_suntime": {
                        "forecast_year_offsets": [0, 1],
                        "fields": ["con_roe"],
                    },
                }
            )
            config_path = workspace / "growth.yaml"
            self._write_config(config_path, config_data)
            market_data = MarketData.from_yaml(config_path)

            listing_dates = market_data.get_panel("stock_basic", "LISTDATE")
            self.assertEqual(
                listing_dates.loc[pd.Timestamp("2024-01-02"), "000001.SZ"],
                pd.Timestamp("2020-01-02"),
            )
            current_roe = market_data.get_panel(
                "consensus_suntime",
                "con_roe",
                forecast_year_offset=0,
            )
            next_roe = market_data.get_panel(
                "consensus_suntime",
                "con_roe",
                forecast_year_offset=1,
            )
            self.assertEqual(current_roe.loc["2024-02-01", "000001.SZ"], 10.0)
            self.assertEqual(next_roe.loc["2024-02-01", "000001.SZ"], 12.0)

            metadata = json.loads(
                (cache_root / "consensus_suntime.meta.json").read_text(
                    encoding="utf-8"
                )
            )
            self.assertEqual(metadata["forecast_year_offsets"], [0, 1])

            subset_config = deepcopy(config_data)
            subset_config["market_data"]["sources"]["consensus_suntime"][
                "forecast_year_offsets"
            ] = [0]
            self._write_config(config_path, subset_config)
            with patch(
                "src.data.market_data.load_data",
                side_effect=AssertionError("期限子集请求不应重建缓存"),
            ):
                subset_data = MarketData.from_yaml(config_path)
            subset_roe = subset_data.get_panel(
                "consensus_suntime",
                "con_roe",
                forecast_year_offset=0,
            )
            pd.testing.assert_frame_equal(
                subset_roe,
                current_roe,
                check_column_type=False,
            )

            legacy_config = deepcopy(subset_config)
            consensus_config = legacy_config["market_data"]["sources"][
                "consensus_suntime"
            ]
            consensus_config.pop("forecast_year_offsets")
            consensus_config["forecast_year_offset"] = 0
            self._write_config(config_path, legacy_config)
            with patch(
                "src.data.market_data.load_data",
                side_effect=AssertionError("单期限兼容请求不应重建缓存"),
            ):
                legacy_data = MarketData.from_yaml(config_path)
            legacy_roe = legacy_data.get_panel("consensus_suntime", "con_roe")
            pd.testing.assert_frame_equal(
                legacy_roe,
                current_roe,
                check_column_type=False,
            )

    def test_different_yaml_files_share_and_expand_source_cache(self) -> None:
        """不同 YAML 应复用同一路径，并只为新增字段重建对应来源。"""
        with TemporaryDirectory() as temporary_directory:
            workspace = Path(temporary_directory)
            data_root = workspace / "raw_data"
            cache_root = workspace / "market_cache"
            shutil.copytree(SYNTHETIC_DATA_ROOT, data_root)
            self._add_quote_volume(data_root)

            base_config = self._market_config(data_root, cache_root)
            initial_config = deepcopy(base_config)
            initial_config["market_data"].update(
                {
                    "start_date": "2024-02-01",
                    "end_date": "2024-05-31",
                }
            )
            first_path = workspace / "growth.yaml"
            second_path = workspace / "value.yaml"
            self._write_config(first_path, initial_config)
            first_market_data = MarketData.from_yaml(first_path)

            self.assertEqual(
                first_market_data.calendar[[0, -1]].tolist(),
                [pd.Timestamp("2024-02-01"), pd.Timestamp("2024-05-31")],
            )
            self.assertFalse((cache_root / "growth").exists())
            initial_times = self._cache_times(cache_root)

            self._write_config(second_path, initial_config)
            with (
                patch(
                    "src.data.market_data.load_data",
                    side_effect=AssertionError("完整命中时不应读取原始来源"),
                ),
                patch(
                    "src.data.market_data.load_index_members",
                    side_effect=AssertionError("完整命中时不应读取指数成员"),
                ),
            ):
                MarketData.from_yaml(second_path)
            self.assertEqual(initial_times, self._cache_times(cache_root))

            self._write_config(second_path, base_config)
            original_load_data = market_data_module.load_data
            with patch(
                "src.data.market_data.load_data",
                wraps=original_load_data,
            ) as load_data_mock:
                expanded_range_data = MarketData.from_yaml(second_path)
            self.assertEqual(
                [
                    call.kwargs["source_name"]
                    for call in load_data_mock.call_args_list
                ],
                ["index_price", "stock_quote"],
            )
            self.assertEqual(
                expanded_range_data.calendar[[0, -1]].tolist(),
                [pd.Timestamp("2024-01-02"), pd.Timestamp("2024-06-28")],
            )
            expanded_range_times = self._cache_times(cache_root)

            expanded_config = deepcopy(base_config)
            expanded_config["market_data"]["sources"]["stock_quote"][
                "fields"
            ].append("S_DQ_VOLUME")
            self._write_config(second_path, expanded_config)
            with patch(
                "src.data.market_data.load_data",
                wraps=original_load_data,
            ) as load_data_mock:
                expanded_market_data = MarketData.from_yaml(second_path)

            rebuilt_sources = [
                call.kwargs["source_name"]
                for call in load_data_mock.call_args_list
            ]
            self.assertEqual(rebuilt_sources, ["stock_quote"])
            self.assertEqual(
                expanded_market_data.get_panel(
                    "stock_quote",
                    "S_DQ_VOLUME",
                ).shape,
                expanded_market_data.membership.shape,
            )
            self.assertEqual(
                expanded_range_times["index_price.parquet"],
                (cache_root / "index_price.parquet").stat().st_mtime_ns,
            )
            self.assertEqual(
                expanded_range_times["index_membership.parquet"],
                (cache_root / "index_membership.parquet").stat().st_mtime_ns,
            )
            stock_metadata = json.loads(
                (cache_root / "stock_quote.meta.json").read_text(
                    encoding="utf-8"
                )
            )
            self.assertEqual(
                stock_metadata["fields"],
                ["S_DQ_ADJCLOSE", "S_DQ_VOLUME"],
            )

            shorter_config = deepcopy(base_config)
            shorter_config["market_data"].update(
                {
                    "start_date": "2024-03-01",
                    "end_date": "2024-04-30",
                }
            )
            self._write_config(first_path, shorter_config)
            with patch(
                "src.data.market_data.load_data",
                side_effect=AssertionError("子集请求不应重建缓存"),
            ):
                shorter_market_data = MarketData.from_yaml(first_path)
            self.assertEqual(
                shorter_market_data.calendar[[0, -1]].tolist(),
                [pd.Timestamp("2024-03-01"), pd.Timestamp("2024-04-30")],
            )
            with self.assertRaises(KeyError):
                shorter_market_data.get_panel("stock_quote", "S_DQ_VOLUME")

            original_load_data = market_data_module.load_data
            with patch(
                "src.data.market_data.load_data",
                wraps=original_load_data,
            ) as load_data_mock:
                refreshed_market_data = MarketData.from_yaml(
                    first_path,
                    refresh=True,
                )
            self.assertEqual(
                [
                    call.kwargs["source_name"]
                    for call in load_data_mock.call_args_list
                ],
                ["index_price", "stock_quote"],
            )
            self.assertTrue(
                refreshed_market_data.calendar.equals(
                    shorter_market_data.calendar
                )
            )
            refreshed_metadata = json.loads(
                (cache_root / "stock_quote.meta.json").read_text(
                    encoding="utf-8"
                )
            )
            self.assertEqual(
                refreshed_metadata["fields"],
                ["S_DQ_ADJCLOSE", "S_DQ_VOLUME"],
            )

    def test_shared_cache_rejects_semantic_conflicts(self) -> None:
        """原始数据根和筛选口径变化不能静默复用已有来源。"""
        with TemporaryDirectory() as temporary_directory:
            workspace = Path(temporary_directory)
            data_root = workspace / "raw_data"
            cache_root = workspace / "market_cache"
            shutil.copytree(SYNTHETIC_DATA_ROOT, data_root)
            config_path = workspace / "base.yaml"
            config_data = self._market_config(data_root, cache_root)
            self._write_config(config_path, config_data)
            MarketData.from_yaml(config_path)

            different_root_config = deepcopy(config_data)
            different_root_config["market_data"]["source_root"] = str(
                workspace / "other_data"
            )
            self._write_config(config_path, different_root_config)
            with self.assertRaisesRegex(ValueError, "source_root"):
                MarketData.from_yaml(config_path)

            filtered_config = deepcopy(config_data)
            filtered_config["market_data"]["sources"]["stock_quote"][
                "filters"
            ] = {"S_DQ_ADJCLOSE": 1}
            self._write_config(config_path, filtered_config)
            with self.assertRaisesRegex(ValueError, "filters"):
                MarketData.from_yaml(config_path)

    def test_daily_source_refresh_rebuilds_only_requested_tail(self) -> None:
        """日频来源变化时应保留早期前缀，不重读其他来源。"""
        with TemporaryDirectory() as temporary_directory:
            workspace = Path(temporary_directory)
            data_root = workspace / "raw_data"
            cache_root = workspace / "market_cache"
            shutil.copytree(SYNTHETIC_DATA_ROOT, data_root)
            config_path = workspace / "base.yaml"
            config_data = self._market_config(data_root, cache_root)
            self._write_config(config_path, config_data)
            original_market_data = MarketData.from_yaml(config_path)
            original_prices = original_market_data.get_panel(
                "stock_quote",
                "S_DQ_ADJCLOSE",
            )

            original_load_data = market_data_module.load_data
            with patch(
                "src.data.market_data.load_data",
                wraps=original_load_data,
            ) as load_data_mock:
                refreshed_market_data = MarketData.from_yaml(
                    config_path,
                    refresh_sources=["stock_quote"],
                    incremental_from=pd.Timestamp("2024-05-01"),
                )

            self.assertEqual(len(load_data_mock.call_args_list), 1)
            refresh_call = load_data_mock.call_args_list[0]
            self.assertEqual(refresh_call.kwargs["source_name"], "stock_quote")
            self.assertEqual(
                refresh_call.kwargs["start_date"],
                pd.Timestamp("2024-05-01"),
            )
            refreshed_prices = refreshed_market_data.get_panel(
                "stock_quote",
                "S_DQ_ADJCLOSE",
            )
            pd.testing.assert_frame_equal(
                refreshed_prices.loc[refreshed_prices.index < "2024-05-01"],
                original_prices.loc[original_prices.index < "2024-05-01"],
            )

    def test_financial_event_records_are_cached_and_reused(self) -> None:
        """财务面板缓存应伴随保存完整公告事件，并在命中时一并复用。"""
        with TemporaryDirectory() as temporary_directory:
            workspace = Path(temporary_directory)
            data_root = workspace / "raw_data"
            cache_root = workspace / "market_cache"
            shutil.copytree(SYNTHETIC_DATA_ROOT, data_root)
            self._add_financial_income_data(data_root)

            config_data = self._market_config(data_root, cache_root)
            config_data["market_data"]["sources"]["financial_income"] = {
                "fields": ["TOT_OPER_REV"]
            }
            config_path = workspace / "growth.yaml"
            self._write_config(config_path, config_data)
            first_market_data = MarketData.from_yaml(config_path)

            records_path = cache_root / "financial_income.records.parquet"
            self.assertTrue(records_path.exists())
            first_records = first_market_data.get_financial_records(
                "financial_income"
            )
            self.assertEqual(len(first_records), 2)
            self.assertEqual(
                first_records.loc[1, "date"],
                pd.Timestamp("2024-04-25"),
            )
            self.assertEqual(
                first_records.loc[1, "report_period"],
                pd.Timestamp("2023-12-31"),
            )

            with patch(
                "src.data.market_data.load_data",
                side_effect=AssertionError("完整命中时不应读取原始来源"),
            ):
                cached_market_data = MarketData.from_yaml(config_path)
            pd.testing.assert_frame_equal(
                cached_market_data.get_financial_records("financial_income"),
                first_records,
            )

    @staticmethod
    def _market_config(data_root: Path, cache_root: Path) -> dict:
        """构造只包含 MarketData 的测试配置。"""
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
                    "stock_quote": {
                        "fields": ["S_DQ_ADJCLOSE"],
                    },
                },
            }
        }

    @staticmethod
    def _add_quote_volume(data_root: Path) -> None:
        """给 synthetic 行情增加真实服务器同名成交量字段。"""
        quote_path = data_root / "stock" / "daily_quote" / "quote_2024.csv"
        quote_data = pd.read_csv(quote_path)
        quote_data["S_DQ_VOLUME"] = 1000.0
        quote_data.to_csv(quote_path, index=False)

    @staticmethod
    def _add_static_and_consensus_data(data_root: Path) -> None:
        """补充成长100所需的上市日和当年、次年一致预期测试数据。"""
        member_paths = [
            data_root / "index" / "members" / "000906.SH.csv",
            data_root / "index" / "members" / "000852.SH.csv",
        ]
        stock_codes = sorted(
            {
                stock_code
                for member_path in member_paths
                for stock_code in pd.read_csv(member_path)[
                    "s_con_windcode"
                ].tolist()
            }
        )
        basic_directory = data_root / "stock" / "meta"
        basic_directory.mkdir(parents=True)
        pd.DataFrame(
            {
                "stock_code": stock_codes,
                "LISTDATE": 20200102,
            }
        ).to_csv(basic_directory / "basic_desc.csv", index=False)

        consensus_records = []
        for stock_code in stock_codes:
            consensus_records.extend(
                [
                    {
                        "con_date": 20240201,
                        "stock_code": stock_code,
                        "con_year": 2024,
                        "con_roe": 10.0,
                    },
                    {
                        "con_date": 20240201,
                        "stock_code": stock_code,
                        "con_year": 2025,
                        "con_roe": 12.0,
                    },
                ]
            )
        consensus_directory = data_root / "stock" / "consensus" / "suntime"
        consensus_directory.mkdir(parents=True)
        pd.DataFrame(consensus_records).to_csv(
            consensus_directory / "suntime_2024.csv",
            index=False,
        )

    @staticmethod
    def _add_financial_income_data(data_root: Path) -> None:
        """补充先披露一季报、后披露上年年报的财务测试数据。"""
        income_directory = data_root / "stock" / "financial" / "income"
        income_directory.mkdir(parents=True)
        pd.DataFrame(
            [
                {
                    "ANN_DT": 20240420,
                    "ACTUAL_ANN_DT": 20240420,
                    "S_INFO_WINDCODE": "000001.SZ",
                    "REPORT_PERIOD": 20240331,
                    "TOT_OPER_REV": 120.0,
                    "OPDATE": "2024-04-20 18:00:00",
                },
                {
                    "ANN_DT": 20240422,
                    "ACTUAL_ANN_DT": 20240425,
                    "S_INFO_WINDCODE": "000001.SZ",
                    "REPORT_PERIOD": 20231231,
                    "TOT_OPER_REV": 460.0,
                    "OPDATE": "2024-04-25 18:00:00",
                },
            ]
        ).to_csv(income_directory / "income_2024.csv", index=False)

    @staticmethod
    def _cache_times(cache_root: Path) -> dict[str, int]:
        """记录来源 Parquet 的修改时间。"""
        return {
            path.name: path.stat().st_mtime_ns
            for path in cache_root.glob("*.parquet")
        }

    @staticmethod
    def _write_config(config_path: Path, config_data: dict) -> None:
        """写入测试 YAML。"""
        config_path.write_text(
            yaml.safe_dump(config_data, allow_unicode=True, sort_keys=False),
            encoding="utf-8",
        )


if __name__ == "__main__":
    unittest.main()
