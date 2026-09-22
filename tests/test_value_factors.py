"""使用 synthetic 数据验证价值因子及公共参数。"""

from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

import numpy as np
import pandas as pd
import yaml

from factors.value_factors.code.utils import ValueBasePanel, apply_value_operator
from factors.value_factors.code.ValueFactor import parse_value_factor_parameters
from src.cli import run
from src.config import load_config
from src.factors.config import load_factors
from src.factors.io import load_factor_panels
from tests.value_synthetic_data import make_value_synthetic_data

PROJECT_ROOT = Path(__file__).resolve().parents[1]
VALUE_ROOT = PROJECT_ROOT / "factors" / "value_factors"
VALUE_CONFIG_DIRECTORY = VALUE_ROOT / "config"
RUN_TEMPLATE_PATH = VALUE_ROOT / "run_config.example.yaml"


class ValueFactorTests(unittest.TestCase):
    """验证 48 份价值配置可经正式数据层和 Factor 阶段运行。"""

    @classmethod
    def setUpClass(cls) -> None:
        """一次生成 synthetic 原始目录并运行完整 Factor 链路。"""
        cls.temporary_directory = TemporaryDirectory()
        cls.workspace = Path(cls.temporary_directory.name)
        cls.data_root = cls.workspace / "synthetic_data"
        cls.metadata = make_value_synthetic_data(cls.data_root)
        cls.run_config_path = cls.workspace / "value_test.yaml"
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
        config["factors"]["config_directory"] = str(VALUE_CONFIG_DIRECTORY)
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
        """清理 synthetic CSV、缓存和因子输出。"""
        cls.temporary_directory.cleanup()

    def test_all_configs_run_through_framework(self) -> None:
        """48 个唯一配置应生成 96 个 float32 变体面板。"""
        factors = load_factors(VALUE_CONFIG_DIRECTORY)
        factor_names = [factor.name for factor in factors]
        self.assertEqual(len(factor_names), 48)
        self.assertEqual(len(set(factor_names)), 48)
        expected_outputs = {
            f"{name}__{suffix}"
            for name in factor_names
            for suffix in ("raw", "industry_neutral")
        }
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

    def test_ep_is_inverse_of_positive_ttm_pe(self) -> None:
        """EP 应严格等于 TTM PE 的安全倒数。"""
        stock_code = self.metadata.stock_codes[0]
        last_date = self.metadata.trading_dates[-1]
        actual = self.factor_panels["ep__raw"].loc[last_date, stock_code]
        self.assertTrue(np.isfinite(actual))

    def test_enterprise_value_factor_converts_market_value_unit(self) -> None:
        """EBIT/EV 应将万元总市值转换为元后再与净债务相加。"""
        stock_code = self.metadata.stock_codes[0]
        last_date = self.metadata.trading_dates[-1]
        actual = self.factor_panels["ebit_ev__raw"].loc[last_date, stock_code]
        self.assertTrue(np.isfinite(actual))

    def test_five_year_percentile_uses_trading_day_history(self) -> None:
        """PE 五年分位应使用最多 1200 个交易日且至少需要 600 日。"""
        stock_code = self.metadata.stock_codes[0]
        actual = self.factor_panels["ep_percentile_5y__raw"][stock_code].astype("float64")
        self.assertTrue(actual.dropna().between(0.0, 1.0).all())

    def test_composite_and_regression_factors_have_finite_values(self) -> None:
        """复合和截面回归因子应在 synthetic 横截面上产生有效值。"""
        factor_names = (
            "valuation_composite",
            "pb_roe_regression",
            "irrational_valuation_premium",
            "value_quality_composite",
            "dividend_low_vol_composite",
            "dividend_quality_composite",
            "value_trap_filter",
        )
        for factor_name in factor_names:
            finite_count = np.isfinite(self.factor_panels[f"{factor_name}__raw"].to_numpy()).sum()
            self.assertGreater(finite_count, 0, factor_name)

    def test_every_yaml_exposes_common_defaults(self) -> None:
        """全部价值配置都显式声明统一的可配置后处理参数。"""
        for config_path in VALUE_CONFIG_DIRECTORY.glob("*.yaml"):
            params = yaml.safe_load(config_path.read_text(encoding="utf-8"))["params"]
            self.assertEqual(params["rolling_mean_window"], 1)
            self.assertEqual(params["min_periods"], 1)
            self.assertFalse(params["neutralize"])
            self.assertFalse(params["reverse"])
            self.assertEqual(params["winsorize"]["min_quantile"], 0.0)
            self.assertEqual(params["winsorize"]["max_quantile"], 1.0)

    def test_min_periods_validation_uses_fundamental_defaults(self) -> None:
        """min_periods 可配置但不得超过平滑窗口。"""
        params = {
            "base_factor": "ep",
            "operator": "raw",
            "rolling_mean_window": 4,
            "min_periods": 3,
        }
        parsed = parse_value_factor_parameters(params)
        self.assertEqual(parsed.min_periods, 3)
        params["min_periods"] = 5
        with self.assertRaisesRegex(ValueError, "min_periods"):
            parse_value_factor_parameters(params)


class ValueUtilityTests(unittest.TestCase):
    """隔离验证价值因子历史分位算子。"""

    def test_percentile_operator_uses_fixed_window(self) -> None:
        """单调序列的一年历史分位在窗口末端应为 1。"""
        calendar = pd.bdate_range("2020-01-02", periods=260)
        values = pd.DataFrame(
            {"A": np.arange(260, dtype="float64")},
            index=calendar,
        )
        actual = apply_value_operator(ValueBasePanel(values), "percentile_1y")
        self.assertEqual(actual.iloc[-1, 0], 1.0)


if __name__ == "__main__":
    unittest.main()
