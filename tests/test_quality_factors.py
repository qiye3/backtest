"""使用 synthetic 数据验证质量因子及公共参数。"""

from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

import numpy as np
import pandas as pd
import yaml

from factors.quality_factors.code.QualityFactor import (
    parse_quality_factor_parameters,
)
from factors.quality_factors.code.utils import (
    QualityBasePanel,
    aligned_financial_ratio,
    apply_quality_operator,
    safe_divide,
)
from src.cli import run
from src.config import load_config
from src.factors.config import load_factors
from src.factors.io import load_factor_panels
from tests.quality_synthetic_data import make_quality_synthetic_data

PROJECT_ROOT = Path(__file__).resolve().parents[1]
QUALITY_ROOT = PROJECT_ROOT / "factors" / "quality_factors"
QUALITY_CONFIG_DIRECTORY = QUALITY_ROOT / "config"
RUN_TEMPLATE_PATH = QUALITY_ROOT / "run_config.example.yaml"


class QualityFactorTests(unittest.TestCase):
    """验证 41 份配置可经正式数据层和 Factor 阶段运行。"""

    @classmethod
    def setUpClass(cls) -> None:
        """一次生成 synthetic 原始目录并运行完整 Factor 链路。"""
        cls.temporary_directory = TemporaryDirectory()
        cls.workspace = Path(cls.temporary_directory.name)
        cls.data_root = cls.workspace / "synthetic_data"
        cls.metadata = make_quality_synthetic_data(cls.data_root)
        cls.run_config_path = cls.workspace / "quality_test.yaml"
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
        config["factors"]["config_directory"] = str(QUALITY_CONFIG_DIRECTORY)
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
        run(load_config(cls.run_config_path))
        cls.factor_panels = load_factor_panels(
            cls.workspace / "outputs" / "factors"
        )

    @classmethod
    def tearDownClass(cls) -> None:
        """清理 synthetic CSV、缓存和结果。"""
        cls.temporary_directory.cleanup()

    def test_all_configs_run_through_framework(self) -> None:
        """正式 raw 模板应生成 41 个唯一 float32 面板。"""
        factors = load_factors(QUALITY_CONFIG_DIRECTORY)
        factor_names = [factor.name for factor in factors]
        self.assertEqual(len(factor_names), 41)
        self.assertEqual(len(set(factor_names)), 41)
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

    def test_cross_statement_ratio_uses_matching_pit_reports(self) -> None:
        """经营现金流与利润比率应在共同实际公告日按同报告期计算。"""
        stock_code = self.metadata.stock_codes[0]
        income_row = self.metadata.income_records.iloc[0]
        event_date = pd.to_datetime(income_row["ACTUAL_ANN_DT"], format="%Y%m%d")
        trading_position = self.metadata.trading_dates.searchsorted(event_date, side="left")
        effective_date = self.metadata.trading_dates[trading_position]
        actual = self.factor_panels["ocf_to_net_profit__raw"].loc[effective_date, stock_code]
        self.assertTrue(np.isfinite(actual))

    def test_inventory_change_uses_prior_natural_quarter(self) -> None:
        """存货变化应按报告季度历史计算，而不是按日频 shift。"""
        stock_code = self.metadata.stock_codes[0]
        q2_rows = self.metadata.income_records[
            (self.metadata.income_records["S_INFO_WINDCODE"] == stock_code)
            & (self.metadata.income_records["REPORT_PERIOD"].astype(str).str.endswith("0630"))
        ]
        q2_row = q2_rows.iloc[0]
        event_date = pd.to_datetime(q2_row["ACTUAL_ANN_DT"], format="%Y%m%d")
        effective_date = self.metadata.trading_dates[
            self.metadata.trading_dates.searchsorted(event_date, side="left")
        ]
        actual = self.factor_panels["inventory_change_to_assets__raw"].loc[
            effective_date,
            stock_code,
        ]
        self.assertTrue(np.isfinite(actual))

    def test_every_yaml_exposes_common_defaults(self) -> None:
        """全部质量配置都显式声明统一的可配置后处理参数。"""
        for config_path in QUALITY_CONFIG_DIRECTORY.glob("*.yaml"):
            params = yaml.safe_load(config_path.read_text(encoding="utf-8"))["params"]
            self.assertEqual(params["rolling_mean_window"], 1)
            self.assertEqual(params["min_periods"], 1)
            self.assertFalse(params["neutralize"])
            self.assertFalse(params["reverse"])
            self.assertEqual(params["winsorize"]["min_quantile"], 0.0)
            self.assertEqual(params["winsorize"]["max_quantile"], 1.0)

    def test_min_periods_validation_matches_growth_factors(self) -> None:
        """min_periods 可配置但不得超过平滑窗口。"""
        params = {
            "base_factor": "roe_level",
            "operator": "raw",
            "rolling_mean_window": 4,
            "min_periods": 2,
        }
        parsed = parse_quality_factor_parameters(params)
        self.assertEqual(parsed.min_periods, 2)
        params["min_periods"] = 5
        with self.assertRaisesRegex(ValueError, "min_periods"):
            parse_quality_factor_parameters(params)


class QualityUtilityTests(unittest.TestCase):
    """隔离验证安全除法和基于报告期的季度算子。"""

    def test_safe_divide_removes_zero_and_infinite_denominators(self) -> None:
        """零分母和无穷结果必须转为缺失。"""
        numerator = pd.DataFrame([[1.0, 2.0, 3.0]])
        denominator = pd.DataFrame([[2.0, 0.0, np.inf]])
        actual = safe_divide(numerator, denominator)
        self.assertEqual(actual.iloc[0, 0], 0.5)
        self.assertTrue(pd.isna(actual.iloc[0, 1]))
        self.assertTrue(pd.isna(actual.iloc[0, 2]))

    def test_stability_and_yoy_use_report_events(self) -> None:
        """日频延续状态不得被重复计入季度窗口。"""
        calendar = pd.bdate_range("2021-01-04", periods=15)
        values = pd.DataFrame(np.nan, index=calendar, columns=["A"])
        periods = pd.DataFrame(pd.NaT, index=calendar, columns=["A"])
        for position, value in zip((0, 3, 6, 9, 12), (1.0, 2.0, 3.0, 5.0, 8.0)):
            values.loc[calendar[position] :, "A"] = value
            report_period = pd.Period("2020Q4") + position // 3
            periods.loc[calendar[position] :, "A"] = report_period.end_time.normalize()
        panel = QualityBasePanel(values, "quarterly", periods)
        yoy = apply_quality_operator(panel, "yoy")
        self.assertEqual(yoy.iloc[-1, 0], 7.0)

    def test_cross_statement_ratio_rejects_mismatched_periods(self) -> None:
        """不同报告期的财务字段不得被拼成一个比率。"""
        index = pd.bdate_range("2024-01-02", periods=2)
        numerator = pd.DataFrame({"A": [10.0, 12.0]}, index=index)
        denominator = pd.DataFrame({"A": [2.0, 3.0]}, index=index)
        numerator_periods = pd.DataFrame(
            {"A": [pd.Timestamp("2024-03-31"), pd.Timestamp("2024-06-30")]},
            index=index,
        )
        denominator_periods = pd.DataFrame(
            {"A": [pd.Timestamp("2024-03-31"), pd.Timestamp("2024-03-31")]},
            index=index,
        )
        ratio, periods = aligned_financial_ratio(
            numerator,
            numerator_periods,
            denominator,
            denominator_periods,
        )
        self.assertEqual(ratio.iloc[0, 0], 5.0)
        self.assertTrue(pd.isna(ratio.iloc[1, 0]))
        self.assertTrue(pd.isna(periods.iloc[1, 0]))


if __name__ == "__main__":
    unittest.main()
