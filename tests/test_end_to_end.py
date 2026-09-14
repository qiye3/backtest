"""使用仓库 synthetic 数据验证主 CLI 的完整运行和缓存恢复。"""

from __future__ import annotations

import unittest
from copy import deepcopy
from pathlib import Path
from tempfile import TemporaryDirectory

import matplotlib
import pandas as pd
import yaml

from src.backtest.io import load_backtest_results
from src.cli import run
from src.config import load_config

matplotlib.use("Agg")

PROJECT_ROOT = Path(__file__).resolve().parents[1]
BASE_CONFIG_PATH = PROJECT_ROOT / "configs" / "base_config.yaml"
FACTOR_NAMES = ["return_10d", "return_20d"]
RESULT_FILES = {
    "factor.parquet",
    "group_return.parquet",
    "simple_backtest.parquet",
    "account_backtest.parquet",
}
FIGURE_FILES = {
    "00_factor_distribution.png",
    "01_evaluation.png",
    "02_simple_backtest.png",
    "03_account_backtest.png",
}


class EndToEndTests(unittest.TestCase):
    """验证全阶段、日度调仓、市场缓存和 plotter-only 恢复。"""

    def test_full_run_cache_reuse_and_plotter_restore(self) -> None:
        """运行完整链路，并在断开原始数据后复用两类缓存。"""
        with TemporaryDirectory() as temporary_directory:
            workspace = Path(temporary_directory)
            config_path = workspace / "synthetic_test.yaml"
            output_root = workspace / "output"
            config_data = self._test_config(output_root)
            config_data["market_data"]["cache_root"] = str(
                workspace / "market_cache"
            )
            self._write_config(config_path, config_data)
            full_results = run(load_config(config_path))
            self.assertEqual(
                list(full_results),
                [
                    "factors",
                    "group_return",
                    "simple_backtest",
                    "account_backtest",
                    "plotter",
                ],
            )
            self._assert_outputs(output_root)

            cache_directory = Path(
                config_data["market_data"]["cache_root"]
            ) / config_path.stem
            cache_times = {
                path.name: path.stat().st_mtime_ns
                for path in cache_directory.glob("*.parquet")
            }
            self.assertEqual(
                set(cache_times),
                {
                    "index_price.parquet",
                    "index_membership.parquet",
                    "stock_quote.parquet",
                },
            )

            self._run_factor_from_cache(config_path, config_data)
            self.assertEqual(
                cache_times,
                {
                    path.name: path.stat().st_mtime_ns
                    for path in cache_directory.glob("*.parquet")
                },
            )
            self._run_plotter_from_results(config_path, config_data)

    def test_daily_rebalance_and_result_restore(self) -> None:
        """按每个和每五个交易日回测，并校验年化频率与缓存恢复。"""
        with TemporaryDirectory() as temporary_directory:
            workspace = Path(temporary_directory)
            config_path = workspace / "daily_test.yaml"
            output_root = workspace / "output"
            config_data = self._test_config(output_root)
            config_data["market_data"]["cache_root"] = str(
                workspace / "market_cache"
            )
            config_data["run"].update(
                {
                    "group_return": False,
                    "plotter": False,
                }
            )
            for section_name in ["simple_backtest", "account_backtest"]:
                config_data[section_name]["rebalance"] = {
                    "frequency": "daily",
                    "intervals": [1, 5],
                }
            config_data["metrics"]["return_frequency"] = "rebalance"
            self._write_config(config_path, config_data)

            stage_results = run(load_config(config_path))
            factor_panel = stage_results["factors"]["return_10d"]
            backtest_results = {
                mode: stage_results[f"{mode}_backtest"]["return_10d"]
                for mode in ["simple", "account"]
            }
            for backtest_result in backtest_results.values():
                self.assertEqual(backtest_result["rebalance_frequency"], "daily")
                self.assertEqual(list(backtest_result["periods"]), [1, 5])

            backtest_result = backtest_results["simple"]
            daily_actions = backtest_result["periods"][1]["actions"]
            actual_dates = pd.DatetimeIndex(daily_actions["date"].unique())
            expected_dates = factor_panel.index[
                factor_panel.index.to_series().between(
                    config_data["simple_backtest"]["start"],
                    config_data["simple_backtest"]["end"],
                )
            ]
            self.assertTrue(actual_dates.equals(expected_dates))

            annualization = (
                backtest_result["metrics"]
                .groupby("rebalance_interval")["risk_periods_per_year"]
                .first()
                .to_dict()
            )
            self.assertEqual(annualization, {1: 252.0, 5: 50.4})
            for mode in ["simple", "account"]:
                restored = load_backtest_results(
                    ["return_10d"],
                    output_root,
                    mode,
                )["return_10d"]
                self.assertEqual(restored["rebalance_frequency"], "daily")
                self.assertEqual(list(restored["periods"]), [1, 5])

    @staticmethod
    def _test_config(output_root: Path) -> dict:
        """基于可运行基础配置构造隔离输出的测试配置。"""
        config_data = yaml.safe_load(BASE_CONFIG_PATH.read_text(encoding="utf-8"))
        config_data["factors"]["config_directory"] = str(
            PROJECT_ROOT / "examples" / "config" / "base_factors"
        )
        config_data["output"]["root"] = str(output_root)
        config_data["market_data"]["source_root"] = str(
            PROJECT_ROOT / "examples" / "data"
        )
        config_data["plots"]["formats"] = ["png"]
        config_data["plots"]["dpi"] = 60
        return config_data

    @staticmethod
    def _write_config(config_path: Path, config_data: dict) -> None:
        """覆盖测试主配置，同时保持固定文件名以复用同一缓存。"""
        config_path.write_text(
            yaml.safe_dump(config_data, allow_unicode=True, sort_keys=False),
            encoding="utf-8",
        )

    def _run_factor_from_cache(
        self,
        config_path: Path,
        source_config: dict,
    ) -> None:
        """断开原始数据路径后只运行 Factor，确认市场缓存可复用。"""
        config_data = deepcopy(source_config)
        config_data["market_data"]["source_root"] = str(
            config_path.parent / "missing_raw_data"
        )
        config_data["run"].update(
            {
                "factors": True,
                "group_return": False,
                "simple_backtest": False,
                "account_backtest": False,
                "plotter": False,
                "refresh_market_data": False,
            }
        )
        self._write_config(config_path, config_data)
        self.assertEqual(list(run(load_config(config_path))), ["factors"])

    def _run_plotter_from_results(
        self,
        config_path: Path,
        source_config: dict,
    ) -> None:
        """只读四个结果文件重新生成图像。"""
        config_data = deepcopy(source_config)
        config_data["run"].update(
            {
                "factors": False,
                "group_return": False,
                "simple_backtest": False,
                "account_backtest": False,
                "plotter": True,
                "refresh_market_data": False,
            }
        )
        self._write_config(config_path, config_data)
        self.assertEqual(list(run(load_config(config_path))), ["plotter"])

    def _assert_outputs(self, output_root: Path) -> None:
        """检查结果文件、图像和核心表均实际包含记录。"""
        for factor_name in FACTOR_NAMES:
            factor_directory = output_root / factor_name
            self.assertEqual(
                {path.name for path in factor_directory.glob("*.parquet")},
                RESULT_FILES,
            )
            self.assertEqual(
                {
                    path.name
                    for path in (factor_directory / "figures").glob("*.png")
                },
                FIGURE_FILES,
            )
            factor_panel = pd.read_parquet(
                factor_directory / "factor.parquet"
            )
            self.assertEqual(factor_panel.shape, (129, 40))
            for result_file in RESULT_FILES - {"factor.parquet"}:
                self.assertFalse(
                    pd.read_parquet(factor_directory / result_file).empty
                )


if __name__ == "__main__":
    unittest.main()
