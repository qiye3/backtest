"""验证因子时序搜索的算子、PIT 事件和标准输出契约。"""

from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

import numpy as np
import pandas as pd
import yaml

from src.data.market_data import MarketData
from src.factors.io import load_factor_parquet
from src.factors.search import (
    load_factor_search_config,
    run_factor_search,
    search_plan,
)
from src.factors.search_operators import (
    OperatorSpec,
    apply_operator,
    iter_factor_variants,
    operator_specs,
    planned_variant_names,
)


class FactorSearchOperatorTests(unittest.TestCase):
    """覆盖算子数量、交易日聚合和季度公告事件。"""

    def test_core_daily_plan_contains_eight_native_variants(self) -> None:
        """默认核心搜索只生成当前项目采用的八个日频算子。"""
        variant_names = planned_variant_names(
            "demo",
            "daily",
            "core",
            False,
        )

        self.assertEqual(len(variant_names), 8)
        self.assertEqual(variant_names[0], "demo__daily__raw")
        self.assertIn("demo__daily__zchg_K24_K1", variant_names)
        self.assertFalse(any("weekly" in name for name in variant_names))

    def test_all_daily_plan_expands_to_daily_weekly_and_monthly(self) -> None:
        """全量搜索应包含三种目标频率并按开关追加平均增长率。"""
        without_growth = planned_variant_names(
            "demo",
            "daily",
            "all",
            False,
        )
        with_growth = planned_variant_names(
            "demo",
            "daily",
            "all",
            True,
        )

        self.assertEqual(len(without_growth), 258)
        self.assertEqual(len(with_growth), 273)
        self.assertIn("demo__weekly__raw", with_growth)
        self.assertIn("demo__monthly__avg_growth_N5", with_growth)

    def test_all_mode_catalog_contains_every_reference_operator(self) -> None:
        """all 模式必须覆盖参考清单中的三套全部算子 ID。"""
        expected_set1 = {
            "qoq_diff",
            "qoq_pct",
            "yoy_diff",
            "yoy_pct",
        }
        for operator_prefix in (
            "mean",
            "std",
            "zscore",
            "cv",
            "trend_slope",
            "trend_improve",
            "quantile",
        ):
            expected_set1.update(
                f"{operator_prefix}_N{years}" for years in range(1, 6)
            )
        expected_set1.update(
            f"quantile_K{months}" for months in (1, 3, 6, 12)
        )

        expected_set2 = {"raw"}
        expected_set2.update(
            f"qtile_M{months}" for months in (6, 12, 24, 60)
        )
        expected_set2.update(
            f"zscore_K{months}" for months in (6, 12, 24, 36, 60)
        )
        expected_set2.update(
            f"chg_K{months}" for months in (1, 2, 3, 6)
        )
        expected_set2.update(
            f"pctchg_K{months}" for months in (1, 2, 3, 6)
        )
        expected_set2.update(
            f"dev_K{short_months}_K{long_months}"
            for short_months in (1, 2, 3)
            for long_months in (3, 6, 12, 24, 60)
        )
        expected_set2.update(
            f"qtilechg_K{history_months}_K{change_months}"
            for history_months in (6, 12, 24, 60)
            for change_months in (1, 2, 3, 6)
        )
        expected_set2.update(
            f"zchg_K{history_months}_K{change_months}"
            for history_months in (6, 12, 24, 36, 60)
            for change_months in (1, 2, 3)
        )
        expected_set3 = {f"avg_growth_N{years}" for years in range(1, 6)}
        actual_operator_ids = {
            operator.operator_id
            for operator in operator_specs("daily", "all", True)
        }

        self.assertEqual(len(expected_set1), 43)
        self.assertEqual(len(expected_set2), 64)
        self.assertEqual(len(expected_set3), 5)
        self.assertSetEqual(
            actual_operator_ids,
            expected_set1 | expected_set2 | expected_set3,
        )

    def test_every_operator_executes_on_each_supported_frequency(self) -> None:
        """每个适用频率上的全部算子都应返回同形且包含有效值。"""
        frequency_samples = {
            "daily": (1300, "B"),
            "weekly": (280, "W-FRI"),
            "monthly": (72, "MS"),
            "quarterly": (24, "QS"),
            "annual": (12, "YS"),
        }
        for frequency, (period_count, pandas_frequency) in frequency_samples.items():
            factor_values = pd.DataFrame(
                {"000001.SZ": np.arange(1, period_count + 1, dtype="float64")},
                index=pd.date_range(
                    "2010-01-01",
                    periods=period_count,
                    freq=pandas_frequency,
                ),
            )
            for operator in operator_specs(frequency, "all", True):
                with self.subTest(
                    frequency=frequency,
                    operator=operator.operator_id,
                ):
                    transformed = apply_operator(
                        factor_values,
                        frequency,
                        operator,
                    )

                    self.assertEqual(transformed.shape, factor_values.shape)
                    self.assertTrue(
                        np.isfinite(transformed.to_numpy()).any(),
                        msg=f"{frequency}/{operator.operator_id} 没有有效值",
                    )

    def test_monthly_branch_uses_last_real_trading_day(self) -> None:
        """自然月末在周末时，月频结果仍应落在最后一个真实交易日。"""
        calendar = pd.bdate_range("2024-03-01", "2024-04-05")
        values = pd.DataFrame(
            np.arange(len(calendar), dtype="float64"),
            index=calendar,
            columns=["000001.SZ"],
        )

        variants = list(
            iter_factor_variants(
                base_name="demo",
                factor_values=values,
                source_frequency="daily",
                mode="all",
                include_average_growth=False,
                trading_calendar=calendar,
            )
        )
        monthly_raw = next(
            variant
            for variant in variants
            if variant.name == "demo__monthly__raw"
        )

        self.assertTrue(pd.notna(monthly_raw.values.loc["2024-03-29"].iloc[0]))
        self.assertNotIn(pd.Timestamp("2024-03-31"), monthly_raw.values.index)

    def test_average_growth_uses_ols_slope_divided_by_mean(self) -> None:
        """线性序列的平均增长率不得额外除以窗口样本数。"""
        values = pd.DataFrame(
            {"000001.SZ": [1.0, 2.0, 3.0, 4.0]},
            index=pd.date_range("2020-12-31", periods=4, freq="YE"),
        )
        spec = OperatorSpec(
            "avg_growth_N4",
            "avg_growth",
            {"N": 4},
            "set3",
        )

        transformed = apply_operator(values, "annual", spec)

        self.assertAlmostEqual(transformed.iloc[-1, 0], 1.0 / 2.5)

    def test_quarterly_revision_changes_only_after_announcement(self) -> None:
        """历史季度修订只能从修订公告日起改变同比结果。"""
        calendar = pd.bdate_range("2024-04-01", "2025-04-10")
        base_values = pd.DataFrame(
            np.nan,
            index=calendar,
            columns=["000001.SZ"],
        )
        events = pd.DataFrame(
            [
                ("2024-04-02", "000001.SZ", "2024-03-31", 10.0),
                ("2024-07-02", "000001.SZ", "2024-06-30", 20.0),
                ("2024-10-08", "000001.SZ", "2024-09-30", 30.0),
                ("2025-01-03", "000001.SZ", "2024-12-31", 40.0),
                ("2025-04-02", "000001.SZ", "2025-03-31", 15.0),
                ("2025-04-06", "000001.SZ", "2024-03-31", 12.0),
            ],
            columns=["date", "asset_code", "report_period", "value"],
        )
        events["date"] = pd.to_datetime(events["date"])
        events["report_period"] = pd.to_datetime(events["report_period"])

        variants = iter_factor_variants(
            base_name="quarterly_demo",
            factor_values=base_values,
            source_frequency="quarterly",
            mode="core",
            include_average_growth=False,
            trading_calendar=calendar,
            quarterly_events=events,
        )
        yoy_values = next(
            variant.values
            for variant in variants
            if variant.operator.operator_id == "yoy"
        )

        self.assertEqual(yoy_values.loc["2025-04-04", "000001.SZ"], 5.0)
        self.assertEqual(yoy_values.loc["2025-04-08", "000001.SZ"], 3.0)

    def test_quarterly_all_executes_every_operator_on_pit_events(self) -> None:
        """季频 all 应通过公告事件历史执行全部适用算子。"""
        report_periods = pd.date_range(
            "2018-03-31",
            periods=24,
            freq="QE",
        )
        announcement_dates = report_periods + pd.Timedelta(days=45)
        calendar = pd.bdate_range(
            announcement_dates.min(),
            announcement_dates.max() + pd.Timedelta(days=5),
        )
        base_values = pd.DataFrame(
            np.nan,
            index=calendar,
            columns=["000001.SZ"],
        )
        events = pd.DataFrame(
            {
                "date": announcement_dates,
                "asset_code": "000001.SZ",
                "report_period": report_periods,
                "value": np.arange(1, 25, dtype="float64"),
            }
        )

        variants = list(
            iter_factor_variants(
                base_name="quarterly_demo",
                factor_values=base_values,
                source_frequency="quarterly",
                mode="all",
                include_average_growth=True,
                trading_calendar=calendar,
                quarterly_events=events,
            )
        )

        expected_operator_count = len(operator_specs("quarterly", "all", True))
        self.assertEqual(len(variants), expected_operator_count)
        for variant in variants:
            with self.subTest(operator=variant.operator.operator_id):
                self.assertTrue(
                    np.isfinite(variant.values.to_numpy()).any(),
                    msg=f"{variant.operator.operator_id} 没有 PIT 有效值",
                )

    def test_raw_mode_preserves_mid_period_availability(self) -> None:
        """raw 不得把已经按公告日展开的季度状态延迟到季末。"""
        calendar = pd.bdate_range("2024-04-01", "2024-04-12")
        values = pd.DataFrame(
            {"000001.SZ": [np.nan, 10.0, *([10.0] * 8)]},
            index=calendar,
        )

        raw_variant = next(
            iter_factor_variants(
                base_name="quarterly_demo",
                factor_values=values,
                source_frequency="quarterly",
                mode="raw",
                include_average_growth=False,
                trading_calendar=calendar,
            )
        )

        pd.testing.assert_frame_equal(
            raw_variant.values,
            values.astype("float32").rename_axis("date").rename_axis(
                "asset_code",
                axis=1,
            ),
            check_freq=False,
        )


class FactorSearchWorkflowTests(unittest.TestCase):
    """覆盖配置解析、dry-run 和标准 Parquet 发布。"""

    def test_quarterly_parquet_rejects_non_raw_search(self) -> None:
        """日频化季度 Parquet 不得被猜测性恢复为报告事件。"""
        with TemporaryDirectory() as temporary_directory:
            workspace = Path(temporary_directory)
            parquet_path = workspace / "quarterly.parquet"
            self._factor_panel().to_parquet(parquet_path)
            config_path = self._write_search_config(
                workspace,
                parquet_path,
                frequency="quarterly",
                mode="core",
            )

            with self.assertRaisesRegex(ValueError, "季度 Parquet 只支持 raw"):
                load_factor_search_config(config_path)

    def test_dry_run_plans_without_creating_output(self) -> None:
        """预演只校验配置和列出变体，不创建正式目录。"""
        with TemporaryDirectory() as temporary_directory:
            workspace = Path(temporary_directory)
            parquet_path = workspace / "daily.parquet"
            self._factor_panel().to_parquet(parquet_path)
            config_path = self._write_search_config(workspace, parquet_path)

            config = load_factor_search_config(config_path)
            report = search_plan(config)

            self.assertEqual(report["total_variants"], 8)
            self.assertFalse(config.output_root.exists())

    def test_all_mode_enables_average_growth_by_default(self) -> None:
        """all 未显式配置第三套时，应默认覆盖全部五个平均增长率算子。"""
        with TemporaryDirectory() as temporary_directory:
            workspace = Path(temporary_directory)
            parquet_path = workspace / "daily.parquet"
            self._factor_panel().to_parquet(parquet_path)
            config_path = self._write_search_config(
                workspace,
                parquet_path,
                mode="all",
            )

            config = load_factor_search_config(config_path)
            report = search_plan(config)

            self.assertTrue(config.include_average_growth)
            self.assertEqual(report["total_variants"], 273)

    def test_parquet_search_writes_framework_native_outputs(self) -> None:
        """正式搜索输出应能被原框架 Parquet 读取器直接加载。"""
        with TemporaryDirectory() as temporary_directory:
            workspace = Path(temporary_directory)
            panel = self._factor_panel()
            parquet_path = workspace / "daily.parquet"
            panel.to_parquet(parquet_path)
            config_path = self._write_search_config(workspace, parquet_path)
            market_data = MarketData(
                source_panels={},
                calendar=panel.index,
                membership=panel.notna(),
                benchmark_index="000906.SH",
            )

            config = load_factor_search_config(config_path)
            with patch(
                "src.factors.search.MarketData.from_yaml",
                return_value=market_data,
            ):
                report = run_factor_search(config)

            self.assertEqual(report["generated"], 8)
            raw_path = (
                config.output_root
                / "factors"
                / "demo__daily__raw"
                / "factor.parquet"
            )
            loaded = load_factor_parquet(raw_path)
            pd.testing.assert_frame_equal(
                loaded,
                panel.astype("float32"),
                check_freq=False,
            )
            self.assertTrue(
                (config.output_root / "factor_search_manifest.csv").is_file()
            )
            self.assertFalse(
                (config.output_root / ".pipeline_cache").exists()
            )

    @staticmethod
    def _factor_panel() -> pd.DataFrame:
        return pd.DataFrame(
            {
                "000001.SZ": np.arange(520, dtype="float64"),
                "000002.SZ": np.arange(520, dtype="float64") + 1.0,
            },
            index=pd.bdate_range("2022-01-03", periods=520, name="date"),
        ).rename_axis("asset_code", axis=1)

    @staticmethod
    def _write_search_config(
        workspace: Path,
        parquet_path: Path,
        frequency: str = "daily",
        mode: str = "core",
    ) -> Path:
        market_config = workspace / "market.yaml"
        market_config.write_text("market_data: {}\n", encoding="utf-8")
        config_data = {
            "market_config": str(market_config),
            "inputs": [
                {
                    "name": "demo",
                    "parquet": str(parquet_path),
                    "frequency": frequency,
                }
            ],
            "operators": {"mode": mode},
            "output_root": str(workspace / "search_output"),
        }
        config_path = workspace / "search.yaml"
        config_path.write_text(
            yaml.safe_dump(config_data, sort_keys=False),
            encoding="utf-8",
        )
        return config_path


if __name__ == "__main__":
    unittest.main()
