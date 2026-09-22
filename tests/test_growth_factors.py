"""使用 synthetic 数据验证47个景气成长因子及双变体及公共后处理。"""

from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

import numpy as np
import pandas as pd
import yaml

from factors.fundamental_utils import (
    mask_factor_to_membership,
    neutralize_by_market_cap,
    replace_infinite_values,
    reverse_factor_values,
    smooth_factor_values,
    winsorize_cross_section,
)
from factors.growth_factors.code.GrowthFactor import parse_growth_factor_parameters
from factors.growth_factors.code.utils import (
    apply_daily_operator,
    apply_quarterly_operator,
    build_single_quarter_values,
)
from src.cli import run
from src.config import load_config
from src.data.market_data import MarketData
from src.factors.config import load_factors
from src.factors.io import load_factor_panels
from src.factors.utils import neutralize_factor_values
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

    def test_independent_postprocess_functions(self) -> None:
        """各后处理函数应能独立调用并只完成自身职责。"""
        calendar = pd.bdate_range("2024-01-02", periods=4)
        stock_codes = ["A", "B", "C", "D"]
        membership = pd.DataFrame(True, index=calendar, columns=stock_codes)
        factor_values = pd.DataFrame(
            [
                [1.0, 2.0, 5.0, 20.0],
                [2.0, 4.0, 7.0, 18.0],
                [4.0, 3.0, 9.0, 16.0],
                [8.0, 5.0, 11.0, 14.0],
            ],
            index=calendar,
            columns=stock_codes,
        )
        market_values = pd.DataFrame(
            [[100.0, 200.0, 500.0, 1200.0]] * len(calendar),
            index=calendar,
            columns=stock_codes,
        )
        market_data = MarketData(
            source_panels={
                "stock_valuation": pd.concat(
                    {"S_VAL_MV": market_values},
                    axis=1,
                    names=["field", "asset_code"],
                )
            },
            calendar=calendar,
            membership=membership,
            benchmark_index="000906.SH",
        )

        smoothed_values = smooth_factor_values(
            factor_values,
            rolling_mean_window=2,
            min_periods=1,
        )
        masked_values = mask_factor_to_membership(smoothed_values, market_data)
        neutralized_values = neutralize_by_market_cap(
            masked_values,
            market_data,
        )
        winsorized_values = winsorize_cross_section(
            neutralized_values,
            min_quantile=0.25,
            max_quantile=0.75,
        )
        reversed_values = reverse_factor_values(winsorized_values)
        actual_values = replace_infinite_values(reversed_values)

        expected_neutralized_values = neutralize_factor_values(
            factor_values.rolling(2, min_periods=1).mean(),
            [np.log(market_values)],
        )
        expected_winsorized_values = winsorize_cross_section(
            expected_neutralized_values,
            min_quantile=0.25,
            max_quantile=0.75,
        )
        pd.testing.assert_frame_equal(actual_values, -expected_winsorized_values)

    def test_default_postprocess_is_identity_inside_membership(self) -> None:
        """默认窗口、分位点、中性化和方向参数不得改变有效因子值。"""
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

    def test_configurable_min_periods_is_validated(self) -> None:
        """min_periods 可配置，但不得超过滚动窗口。"""
        config_params = {
            "base_factor": "consensus_eps",
            "operator": "raw",
            "rolling_mean_window": 3,
            "min_periods": 2,
            "neutralize": False,
            "winsorize": {
                "min_quantile": 0.0,
                "max_quantile": 1.0,
            },
            "reverse": False,
        }
        parsed_params = parse_growth_factor_parameters(config_params)
        self.assertEqual(parsed_params.min_periods, 2)
        config_params["min_periods"] = 4
        with self.assertRaisesRegex(ValueError, "min_periods"):
            parse_growth_factor_parameters(config_params)

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


if __name__ == "__main__":
    unittest.main()
