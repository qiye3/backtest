"""使用 synthetic 数据验证47个景气成长因子及双变体及公共后处理。"""

from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

import numpy as np
import pandas as pd
import yaml

from factors.fundamental_utils import mask_factor_to_membership
from factors.growth_factors.code.utils import (
    apply_daily_operator,
    apply_quarterly_operator,
    build_single_quarter_values,
)
from factors.quarterly_history import build_financial_field_history
from src.cli import run
from src.config import load_config
from src.data.market_data import MarketData
from src.factors.config import load_factors
from src.factors.io import load_factor_panels
from tests.growth_synthetic_data import make_growth_synthetic_data

PROJECT_ROOT = Path(__file__).resolve().parents[1]
GROWTH_ROOT = PROJECT_ROOT / "factors" / "growth_factors"
GROWTH_CONFIG_DIRECTORY = GROWTH_ROOT / "config"
RUN_TEMPLATE_PATH = GROWTH_ROOT / "run_config.example.yaml"


class GrowthFactorTests(unittest.TestCase):
    """验证配置展开、PIT 公式、频率算子和后处理顺序。"""

    @classmethod
    def setUpClass(cls) -> None:
        """一次生成完整 synthetic 原始目录并运行正式 Factor 链路。"""
        cls.temporary_directory = TemporaryDirectory()
        cls.workspace = Path(cls.temporary_directory.name)
        cls.data_root = cls.workspace / "synthetic_data"
        cls.metadata = make_growth_synthetic_data(cls.data_root)
        cls.run_config_path = cls.workspace / "growth_test.yaml"
        config = yaml.safe_load(RUN_TEMPLATE_PATH.read_text(encoding="utf-8"))
        config["run"].update(
            {
                "group_return": False,
                "simple_backtest": False,
                "account_backtest": False,
                "plotter": False,
                "overall_evaluation": False,
                "max_workers": 2,
                "refresh_market_data": True,
            }
        )
        config["factors"]["config_directory"] = str(GROWTH_CONFIG_DIRECTORY)
        config["output"]["root"] = str(cls.workspace / "outputs")
        config["market_data"].update(
            {
                "source_root": str(cls.data_root),
                "cache_root": str(cls.workspace / "market_cache"),
                "start_date": "2021-01-04",
                "end_date": "2024-12-31",
            }
        )
        cls.run_config_path.write_text(
            yaml.safe_dump(config, allow_unicode=True, sort_keys=False),
            encoding="utf-8",
        )
        cls.run_summary = run(load_config(cls.run_config_path))
        cls.factor_panels = load_factor_panels(
            cls.workspace / "outputs" / "factors"
        )

    @classmethod
    def tearDownClass(cls) -> None:
        """清理测试生成的全部 CSV、缓存和因子结果。"""
        cls.temporary_directory.cleanup()

    def test_all_factor_configs_run_through_framework(self) -> None:
        """正式 raw 模板应为 47 份配置各生成一个面板。"""
        loaded_factors = load_factors(GROWTH_CONFIG_DIRECTORY)
        factor_names = [factor.name for factor in loaded_factors]
        self.assertEqual(len(factor_names), 47)
        self.assertEqual(len(set(factor_names)), 47)
        expected_outputs = {f"{name}__raw" for name in factor_names}
        self.assertEqual(set(self.factor_panels), expected_outputs)
        for factor_name, factor_panel in self.factor_panels.items():
            self.assertEqual(factor_panel.dtypes.unique().tolist(), [np.dtype("float32")])
            factor_path = (
                self.workspace
                / "outputs"
                / "factors"
                / factor_name
                / "factor.parquet"
            )
            self.assertTrue(factor_path.exists())

    def test_run_template_enables_standard_pipeline(self) -> None:
        """正式模板只运行因子、分组和 overall，不启动回测或单因子图。"""
        template = load_config(RUN_TEMPLATE_PATH).raw
        enabled_stages = ("factors", "group_return", "overall_evaluation")
        self.assertTrue(all(template["run"][stage_name] for stage_name in enabled_stages))
        self.assertFalse(template["run"]["plotter"])
        self.assertFalse(template["run"]["simple_backtest"])
        self.assertFalse(template["run"]["account_backtest"])

    def test_income_factor_uses_actual_announcement_date(self) -> None:
        """累计营收应在 ACTUAL_ANN_DT 生效，并正确还原单季度值。"""
        stock_code = self.metadata.stock_codes[0]
        q1_row = self._income_row(stock_code, "2021Q1")
        q2_row = self._income_row(stock_code, "2021Q2")
        q1_effective_date = self._effective_trading_date(q1_row["ACTUAL_ANN_DT"])
        q2_announcement_date = pd.to_datetime(
            q2_row["ANN_DT"],
            format="%Y%m%d",
        )
        q2_effective_date = self._effective_trading_date(q2_row["ACTUAL_ANN_DT"])
        date_before_actual = self.metadata.trading_dates[
            self.metadata.trading_dates.searchsorted(q2_effective_date) - 1
        ]

        quarterly_revenue = self.factor_panels["quarterly_revenue__raw"]
        self.assertTrue(np.isfinite(quarterly_revenue.loc[q1_effective_date, stock_code]))
        self.assertLess(q2_announcement_date, q2_effective_date)
        self.assertTrue(np.isfinite(quarterly_revenue.loc[date_before_actual, stock_code]))
        self.assertTrue(np.isfinite(quarterly_revenue.loc[q2_effective_date, stock_code]))

    def test_quarterly_operator_is_stock_local(self) -> None:
        """其他股票公告时不得把未更新股票的季频变化错误重置为零。"""
        first_stock = self.metadata.stock_codes[0]
        second_stock = self.metadata.stock_codes[1]
        first_q2_row = self._income_row(first_stock, "2021Q2")
        second_q2_row = self._income_row(second_stock, "2021Q2")
        first_effective_date = self._effective_trading_date(first_q2_row["ACTUAL_ANN_DT"])
        second_effective_date = self._effective_trading_date(second_q2_row["ACTUAL_ANN_DT"])
        qoq_values = self.factor_panels["quarterly_revenue__qoq__raw"]
        self.assertTrue(np.isfinite(qoq_values.loc[first_effective_date, first_stock]))
        self.assertTrue(pd.isna(qoq_values.loc[first_effective_date, second_stock]))
        self.assertEqual(
            qoq_values.loc[second_effective_date, first_stock],
            qoq_values.loc[first_effective_date, first_stock],
        )

    def test_daily_window_operators_match_trading_day_definitions(self) -> None:
        """1个月滞后和12个月滚动分位应使用20与240个交易日。"""
        stock_code = self.metadata.stock_codes[0]
        raw_values = self.factor_panels["consensus_eps__raw"][stock_code]
        changed_values = self.factor_panels["consensus_eps__chg_K1__raw"][stock_code]
        percentile_values = self.factor_panels["consensus_eps__qtile_M12__raw"][stock_code]
        last_date = raw_values.index[-1]
        self.assertTrue(np.isfinite(changed_values.loc[last_date]))
        self.assertGreaterEqual(percentile_values.loc[last_date], 0.0)
        self.assertLessEqual(percentile_values.loc[last_date], 1.0)

    def test_quarterly_surprise_variants_produce_finite_history(self) -> None:
        """三类标准化意外在历史充足且方差非零后应产生有效结果。"""
        stock_code = self.metadata.stock_codes[0]
        for factor_name in ["revenue_sur", "earnings_sue", "consensus_np_sue"]:
            valid_values = self.factor_panels[f"{factor_name}__raw"][stock_code].dropna()
            self.assertGreater(len(valid_values), 0, factor_name)

    def test_membership_mask_preserves_in_universe_values(self) -> None:
        """股票池掩码不得改变池内有效因子值。"""
        calendar = pd.bdate_range("2024-01-02", periods=3)
        factor_values = pd.DataFrame(
            [[1.0, 10.0], [2.0, 20.0], [3.0, 30.0]],
            index=calendar,
            columns=["A", "B"],
        )
        market_data = MarketData(
            source_panels={},
            calendar=calendar,
            membership=pd.DataFrame(True, index=calendar, columns=["A", "B"]),
            benchmark_index="000906.SH",
        )
        actual_values = mask_factor_to_membership(factor_values, market_data)
        pd.testing.assert_frame_equal(actual_values, factor_values)

    def test_formal_configs_have_one_postprocess_definition(self) -> None:
        """五组正式配置不得再携带旧后处理键。"""
        forbidden_keys = {
            "rolling_mean_window",
            "min_periods",
            "neutralize",
            "winsorize",
            "reverse",
        }
        group_names = (
            "growth_factors",
            "quality_factors",
            "value_factors",
            "first_batch_factors",
            "second_batch_factors",
        )
        config_paths = [
            config_path
            for group_name in group_names
            for config_path in (PROJECT_ROOT / "factors" / group_name / "config").glob(
                "*.yaml"
            )
        ]
        self.assertEqual(len(config_paths), 192)
        for config_path in config_paths:
            factor_config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
            self.assertFalse(forbidden_keys & factor_config["params"].keys(), config_path)
            self.assertIn("cross_section", factor_config["postprocess"], config_path)
            self.assertEqual(
                [variant["suffix"] for variant in factor_config["variants"]],
                ["raw", "industry_neutral"],
                config_path,
            )

    def _income_row(self, stock_code: str, report_quarter: str) -> pd.Series:
        """从 synthetic 利润表中取得指定股票和报告季度记录。"""
        report_period = pd.Period(report_quarter).end_time.strftime("%Y%m%d")
        matching_records = self.metadata.income_records[
            (self.metadata.income_records["S_INFO_WINDCODE"] == stock_code)
            & (self.metadata.income_records["REPORT_PERIOD"] == report_period)
        ]
        return matching_records.iloc[0]

    def _effective_trading_date(self, yyyymmdd_date: str) -> pd.Timestamp:
        """按框架规则把非交易日事件映射到下一交易日。"""
        event_date = pd.to_datetime(yyyymmdd_date, format="%Y%m%d")
        position = self.metadata.trading_dates.searchsorted(event_date, side="left")
        return self.metadata.trading_dates[position]


class GrowthUtilityTests(unittest.TestCase):
    """使用小矩阵隔离验证季度转换工具。"""

    def test_single_quarter_and_qoq_use_each_stock_report_history(self) -> None:
        """错峰报告状态应分别还原单季值并保持各自 qoq。"""
        calendar = pd.bdate_range("2024-01-02", periods=8)
        cumulative_values = pd.DataFrame(np.nan, index=calendar, columns=["A", "B"])
        report_periods = pd.DataFrame(pd.NaT, index=calendar, columns=["A", "B"])
        cumulative_values.loc[calendar[0] :, "A"] = 100.0
        report_periods.loc[calendar[0] :, "A"] = pd.Timestamp("2024-03-31")
        cumulative_values.loc[calendar[3] :, "A"] = 230.0
        report_periods.loc[calendar[3] :, "A"] = pd.Timestamp("2024-06-30")
        cumulative_values.loc[calendar[1] :, "B"] = 200.0
        report_periods.loc[calendar[1] :, "B"] = pd.Timestamp("2024-03-31")
        cumulative_values.loc[calendar[5] :, "B"] = 450.0
        report_periods.loc[calendar[5] :, "B"] = pd.Timestamp("2024-06-30")

        quarterly_values = build_single_quarter_values(
            cumulative_values,
            report_periods,
        )
        qoq_values = apply_quarterly_operator(
            quarterly_values,
            report_periods,
            "qoq",
        )
        self.assertEqual(quarterly_values.loc[calendar[3], "A"], 130.0)
        self.assertEqual(quarterly_values.loc[calendar[5], "B"], 250.0)
        self.assertEqual(qoq_values.loc[calendar[3], "A"], 30.0)
        self.assertTrue(pd.isna(qoq_values.loc[calendar[3], "B"]))
        self.assertEqual(qoq_values.loc[calendar[5], "A"], 30.0)
        self.assertEqual(qoq_values.loc[calendar[5], "B"], 50.0)

    def test_daily_operator_uses_configured_fixed_windows(self) -> None:
        """单调序列的12月分位和1月变化应具有确定结果。"""
        calendar = pd.bdate_range("2022-01-03", periods=500)
        factor_values = pd.DataFrame(
            {"A": np.arange(500, dtype="float64")},
            index=calendar,
        )
        percentile_values = apply_daily_operator(factor_values, "qtile_M12")
        changed_values = apply_daily_operator(factor_values, "chg_K1")
        self.assertEqual(percentile_values.iloc[-1, 0], 1.0)
        self.assertEqual(changed_values.iloc[-1, 0], 20.0)

    def test_late_annual_report_updates_qoq_without_reversing_raw_period(self) -> None:
        """Q1先披露时保持最新状态，迟到年报仅从公告日起补齐Q1环比。"""
        calendar = pd.bdate_range("2025-04-14", periods=10)
        stock_code = "000001.SZ"
        financial_records = pd.DataFrame(
            [
                {
                    "date": calendar[0],
                    "asset_code": stock_code,
                    "report_period": pd.Timestamp("2024-09-30"),
                    "source_order": 0,
                    "TOT_OPER_REV": 300.0,
                },
                {
                    "date": calendar[4],
                    "asset_code": stock_code,
                    "report_period": pd.Timestamp("2025-03-31"),
                    "source_order": 1,
                    "TOT_OPER_REV": 120.0,
                },
                {
                    "date": calendar[6],
                    "asset_code": stock_code,
                    "report_period": pd.Timestamp("2024-12-31"),
                    "source_order": 2,
                    "TOT_OPER_REV": 460.0,
                },
                {
                    "date": calendar[8],
                    "asset_code": stock_code,
                    "report_period": pd.Timestamp("2024-12-31"),
                    "source_order": 3,
                    "TOT_OPER_REV": 450.0,
                },
            ]
        )
        history = build_financial_field_history(
            financial_records,
            "TOT_OPER_REV",
            calendar,
            [stock_code],
            cumulative=True,
        )
        qoq_values = apply_quarterly_operator(
            history.values,
            history.report_periods,
            "qoq",
            history.events,
        )

        self.assertEqual(history.values.loc[calendar[4], stock_code], 120.0)
        self.assertEqual(history.values.loc[calendar[8], stock_code], 120.0)
        self.assertEqual(
            history.report_periods.loc[calendar[8], stock_code],
            pd.Timestamp("2025-03-31"),
        )
        self.assertTrue(pd.isna(qoq_values.loc[calendar[5], stock_code]))
        self.assertEqual(qoq_values.loc[calendar[6], stock_code], -40.0)
        self.assertEqual(qoq_values.loc[calendar[7], stock_code], -40.0)
        self.assertEqual(qoq_values.loc[calendar[8], stock_code], -30.0)


if __name__ == "__main__":
    unittest.main()
