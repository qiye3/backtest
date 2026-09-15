"""使用仓库 synthetic 数据验证主 CLI 的完整运行和缓存恢复。"""

from __future__ import annotations

import unittest
from copy import deepcopy
from pathlib import Path
from tempfile import TemporaryDirectory

import matplotlib
import pandas as pd
import yaml

from src.backtest.io import load_backtest_results, save_backtest_results
from src.cli import run
from src.config import load_config
from src.group_return.evaluator import _prepare_return_horizons

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

    def test_week_horizon_uses_calendar_week(self) -> None:
        """周周期按目标自然周回退，不等同于五个交易日。"""
        calendar = pd.bdate_range("2024-02-01", "2024-02-16").difference(
            pd.DatetimeIndex(["2024-02-09"])
        )
        sample_dates = pd.DatetimeIndex(["2024-02-02"])
        sample_positions = calendar.get_indexer(sample_dates)
        horizon_values, horizon_units, end_positions = _prepare_return_horizons(
            calendar=calendar,
            sample_dates=sample_dates,
            sample_positions=sample_positions,
            settings={
                "future_return_days": [5],
                "future_return_weeks": [1],
                "sampling": {
                    "weekday": "FRI",
                    "holiday_policy": "previous_trading_day",
                },
            },
        )

        self.assertEqual(horizon_values.tolist(), [5, 1])
        self.assertEqual(horizon_units.tolist(), ["trading_days", "weeks"])
        self.assertEqual(
            calendar[end_positions[:, 0]].tolist(),
            [pd.Timestamp("2024-02-12"), pd.Timestamp("2024-02-08")],
        )

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
            config_data["output"]["save_backtest_details"] = True
            config_data["output"]["save_parquet"] = {
                "factor": True,
                "group_return": True,
                "simple_backtest": True,
                "account_backtest": True,
            }
            self._write_config(config_path, config_data)
            config = load_config(config_path)
            self.assertEqual(
                [
                    config.raw[section_name]["factor_lag_days"]
                    for section_name in [
                        "group_return",
                        "simple_backtest",
                        "account_backtest",
                    ]
                ],
                [0, 0, 0],
            )
            full_results = run(config)
            metrics_summary = pd.read_csv(
                output_root / "metrics_summary.csv"
            )
            self.assertEqual(len(metrics_summary), 12)
            self.assertEqual(
                list(metrics_summary.columns),
                [
                    "factor_name",
                    "rebalance_frequency",
                    "rebalance_interval",
                    "mode",
                    "total_return",
                    "annual_return",
                    "sharpe",
                    "turnover",
                    "benchmark_total_return",
                    "excess_total_return",
                    "mean_ic",
                    "icir",
                ],
            )
            self.assertEqual(
                set(metrics_summary["factor_name"]),
                set(FACTOR_NAMES),
            )
            self.assertEqual(
                set(metrics_summary["mode"]),
                {"simple", "account"},
            )
            self.assertTrue(
                metrics_summary[["mean_ic", "icir"]].notna().all().all()
            )
            self.assertTrue((output_root / "config_snapshot.yaml").is_file())
            evaluation = full_results["group_return"]["return_10d"]
            self.assertEqual(
                list(
                    evaluation["summary"][["horizon_value", "horizon_unit"]]
                    .drop_duplicates()
                    .itertuples(index=False, name=None)
                ),
                [
                    (1, "trading_days"),
                    (1, "weeks"),
                    (2, "weeks"),
                    (4, "weeks"),
                ],
            )
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
            self._run_without_derived_parquets(config_path, config_data)
            for factor_name in FACTOR_NAMES:
                factor_directory = output_root / factor_name
                self.assertEqual(
                    {path.name for path in factor_directory.glob("*.parquet")},
                    {"factor.parquet"},
                )

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
            config_data["output"]["save_backtest_details"] = True
            config_data["output"]["save_parquet"].update(
                {
                    "simple_backtest": True,
                    "account_backtest": True,
                }
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

            summary_root = workspace / "summary_only"
            save_backtest_results(
                {"return_10d": backtest_results["simple"]},
                summary_root,
                "simple",
            )
            stored_summary = pd.read_parquet(
                summary_root / "return_10d" / "simple_backtest.parquet"
            )
            self.assertEqual(
                set(stored_summary["__record_type"]),
                {"definitions", "metrics"},
            )
            restored_summary = load_backtest_results(
                ["return_10d"],
                summary_root,
                "simple",
            )["return_10d"]
            self.assertEqual(restored_summary["periods"], {})
            self.assertEqual(len(restored_summary["metrics"]), 20)

    @staticmethod
    def _test_config(output_root: Path) -> dict:
        """把 Wind 默认配置替换为可重复的 synthetic 测试数据。"""
        config_data = yaml.safe_load(BASE_CONFIG_PATH.read_text(encoding="utf-8"))
        config_data["factors"]["config_directory"] = str(
            PROJECT_ROOT / "examples" / "config" / "base_factors"
        )
        config_data["output"]["root"] = str(output_root)
        config_data["market_data"]["source_root"] = str(
            PROJECT_ROOT / "examples" / "data"
        )
        config_data["market_data"].update(
            {
                "start_date": "2024-01-02",
                "end_date": "2024-06-28",
            }
        )
        config_data["group_return"].update(
            {
                "start": "2024-02-02",
                "end": "2024-06-07",
            }
        )
        for section_name in ["simple_backtest", "account_backtest"]:
            config_data[section_name].update(
                {
                    "start": "2024-02-02",
                    "end": "2024-06-21",
                    "transaction_cost_rate": 0.0,
                    "missing_price_policy": "error",
                }
            )
        config_data["plots"] = {
            "formats": ["png"],
            "dpi": 60,
        }
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

    def _run_without_derived_parquets(
        self,
        config_path: Path,
        source_config: dict,
    ) -> None:
        """运行三个下游阶段并确认关闭开关时清理已有 Parquet。"""
        config_data = deepcopy(source_config)
        config_data["run"].update(
            {
                "factors": False,
                "group_return": True,
                "simple_backtest": True,
                "account_backtest": True,
                "plotter": False,
            }
        )
        config_data["output"]["save_parquet"].update(
            {
                "group_return": False,
                "simple_backtest": False,
                "account_backtest": False,
            }
        )
        self._write_config(config_path, config_data)
        self.assertEqual(
            list(run(load_config(config_path))),
            ["group_return", "simple_backtest", "account_backtest"],
        )

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
            self.assertFalse(
                (factor_directory / "figures" / "plot_config.json").exists()
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
