"""使用仓库 synthetic 数据验证主 CLI 的完整运行和缓存恢复。"""

from __future__ import annotations

import unittest
from contextlib import redirect_stderr
from copy import deepcopy
from io import StringIO
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

import matplotlib
import numpy as np
import pandas as pd
import yaml
from matplotlib.figure import Figure

from src.backtest import engine as backtest_engine
from src.backtest.io import load_backtest_results, save_backtest_results
from src.cli import run
from src.config import load_config
from src.data.market_data import MarketData
from src.factors.io import load_factor_panels
from src.group_return.evaluator import _prepare_return_horizons, evaluate
from src.group_return.grouping import build_group_definitions, core_group_ids
from src.group_return.io import load_evaluation_results
from src.plotter.evaluation import _monthly_rank_ic, _plot_monthly_rank_ic

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
OVERALL_FIGURE_FILES = {
    "factor_correlation_heatmap.png",
    "factor_ic_distribution.png",
    "factor_return_distribution.png",
}


class EndToEndTests(unittest.TestCase):
    """验证全阶段、日度调仓、市场缓存和 plotter-only 恢复。"""

    def test_default_grouping_keeps_deciles_and_adds_extreme_tails(self) -> None:
        """默认十二组应保留 G1/G10，并增加两个重叠的极端百分位组。"""
        grouping = load_config(BASE_CONFIG_PATH).raw["group_return"]["grouping"]
        definitions = build_group_definitions(
            grouping["quantile_edges"],
            grouping["group_aliases"],
        )

        self.assertEqual(
            list(
                definitions[
                    ["group_id", "quantile_lower", "quantile_upper"]
                ].itertuples(index=False, name=None)
            ),
            [
                ("G0.1", 0.0, 0.01),
                ("G1", 0.0, 0.1),
                ("G2", 0.1, 0.2),
                ("G3", 0.2, 0.3),
                ("G4", 0.3, 0.4),
                ("G5", 0.4, 0.5),
                ("G6", 0.5, 0.6),
                ("G7", 0.6, 0.7),
                ("G8", 0.7, 0.8),
                ("G9", 0.8, 0.9),
                ("G10", 0.9, 1.0),
                ("G9.9", 0.99, 1.0),
            ],
        )
        self.assertEqual(
            core_group_ids(definitions),
            [f"G{position}" for position in range(1, 11)],
        )

    def test_group_return_accepts_week_horizons_without_day_horizons(self) -> None:
        """仅配置自然周周期时，主配置应可直接加载。"""
        with TemporaryDirectory() as temporary_directory:
            workspace = Path(temporary_directory)
            config_data = self._test_config(workspace / "output")
            config_data["group_return"].pop("future_return_days", None)
            config_data["group_return"]["future_return_weeks"] = [1]
            config_path = workspace / "weekly_only.yaml"
            self._write_config(config_path, config_data)

            config = load_config(config_path)

            self.assertNotIn("future_return_days", config.raw["group_return"])
            self.assertEqual(config.raw["group_return"]["future_return_weeks"], [1])

    def test_group_aliases_can_be_configured(self) -> None:
        """自定义分位区间应使用 YAML 中一一对应的组名。"""
        with TemporaryDirectory() as temporary_directory:
            workspace = Path(temporary_directory)
            config_data = self._test_config(workspace / "output")
            config_data["group_return"]["grouping"] = {
                "quantile_edges": [[0.0, 0.2], [0.8, 1.0]],
                "group_aliases": ["Low20", "High20"],
            }
            config_path = workspace / "custom_group_aliases.yaml"
            self._write_config(config_path, config_data)

            grouping = load_config(config_path).raw["group_return"]["grouping"]
            definitions = build_group_definitions(
                grouping["quantile_edges"],
                grouping["group_aliases"],
            )

            self.assertEqual(
                definitions["group_id"].tolist(),
                ["Low20", "High20"],
            )

    def test_failed_run_keeps_checkpoint_and_previous_results(self) -> None:
        """中间阶段失败时保留 checkpoint，且不覆盖上次成功结果。"""
        with TemporaryDirectory() as temporary_directory:
            workspace = Path(temporary_directory)
            output_root = workspace / "output"
            config_path = workspace / "failure_test.yaml"
            config_data = self._test_config(output_root)
            config_data["market_data"]["cache_root"] = str(
                workspace / "market_cache"
            )
            config_data["run"].update(
                {
                    "group_return": False,
                    "account_backtest": False,
                    "plotter": False,
                    "overall_evaluation": False,
                }
            )
            previous_factor_path = output_root / "return_10d" / "factor.parquet"
            previous_factor_path.parent.mkdir(parents=True)
            previous_factor_path.write_bytes(b"previous successful result")
            self._write_config(config_path, config_data)

            with patch(
                "src.cli.iter_backtests",
                side_effect=RuntimeError("injected backtest failure"),
            ):
                with self.assertRaisesRegex(RuntimeError, "injected"):
                    run(load_config(config_path))

            checkpoint_root = output_root / ".pipeline_cache"
            self.assertTrue(
                (checkpoint_root / "return_10d" / "factor.parquet").is_file()
            )
            self.assertEqual(
                previous_factor_path.read_bytes(),
                b"previous successful result",
            )

            config_data["run"]["simple_backtest"] = False
            self._write_config(config_path, config_data)
            summary = run(load_config(config_path))

            self.assertEqual(summary.stage_counts, {"factors": 2})
            self.assertFalse(checkpoint_root.exists())
            self.assertTrue(pd.read_parquet(previous_factor_path).shape[0] > 0)

    def test_group_return_outputs_survive_later_stage_failure(self) -> None:
        """评价阶段成功后应立即发布汇总和图，不受后续回测失败影响。"""
        with TemporaryDirectory() as temporary_directory:
            workspace = Path(temporary_directory)
            output_root = workspace / "output"
            config_path = workspace / "stage_publish_test.yaml"
            config_data = self._test_config(output_root)
            config_data["market_data"]["cache_root"] = str(
                workspace / "market_cache"
            )
            config_data["run"].update(
                {
                    "account_backtest": False,
                    "overall_evaluation": False,
                }
            )
            self._write_config(config_path, config_data)

            with patch(
                "src.cli.iter_backtests",
                side_effect=RuntimeError("injected backtest failure"),
            ):
                with self.assertRaisesRegex(RuntimeError, "injected"):
                    run(load_config(config_path))

            self.assertTrue((output_root / "config_snapshot.yaml").is_file())
            self.assertTrue((output_root / "factor_summary_daily.csv").is_file())
            self.assertTrue((output_root / "factor_summary_weekly.csv").is_file())
            for factor_name in FACTOR_NAMES:
                figure_directory = output_root / factor_name / "figures"
                self.assertTrue(
                    (figure_directory / "00_factor_distribution.png").is_file()
                )
                self.assertTrue(
                    (figure_directory / "01_evaluation.png").is_file()
                )
                self.assertFalse(
                    (figure_directory / "02_simple_backtest.png").exists()
                )
            self.assertTrue((output_root / ".pipeline_cache").is_dir())

    def test_factor_and_group_return_create_screening_summary(self) -> None:
        """第一阶段应独立生成筛选汇总，不依赖任何回测阶段。"""
        with TemporaryDirectory() as temporary_directory:
            workspace = Path(temporary_directory)
            output_root = workspace / "output"
            config_path = workspace / "screening_test.yaml"
            config_data = self._test_config(output_root)
            config_data["market_data"]["cache_root"] = str(
                workspace / "market_cache"
            )
            config_data["run"].update(
                {
                    "simple_backtest": False,
                    "account_backtest": False,
                    "plotter": False,
                    "overall_evaluation": False,
                }
            )
            self._write_config(config_path, config_data)

            run_summary = run(load_config(config_path))
            daily_summary_path = output_root / "factor_summary_daily.csv"
            weekly_summary_path = output_root / "factor_summary_weekly.csv"
            daily_summary = pd.read_csv(daily_summary_path)
            weekly_summary = pd.read_csv(weekly_summary_path)

            self.assertEqual(
                run_summary.stage_counts,
                {"factors": 2, "group_return": 2},
            )
            self.assertEqual(len(daily_summary), len(FACTOR_NAMES))
            self.assertEqual(len(weekly_summary), len(FACTOR_NAMES))
            self.assertIn("rank_ic_mean_1d", daily_summary.columns)
            self.assertEqual(
                {
                    "rank_ic_mean_1w",
                    "rank_ic_mean_2w",
                    "rank_ic_mean_4w",
                    "q10_return_1w",
                }
                - set(weekly_summary.columns),
                set(),
            )
            self.assertIn(
                daily_summary_path.resolve(),
                run_summary.output_paths["factor_summary"],
            )
            self.assertFalse((output_root / "metrics_summary.csv").exists())
            self.assertFalse(
                (output_root / "factor_screening_summary.csv").exists()
            )
            self.assertFalse((output_root / ".pipeline_cache").exists())

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

        horizon_values, horizon_units, _ = _prepare_return_horizons(
            calendar=calendar,
            sample_dates=sample_dates,
            sample_positions=sample_positions,
            settings={
                "future_return_weeks": [1],
                "sampling": {
                    "weekday": "FRI",
                    "holiday_policy": "previous_trading_day",
                },
            },
        )
        self.assertEqual(horizon_values.tolist(), [1])
        self.assertEqual(horizon_units.tolist(), ["weeks"])

    def test_monthly_rank_ic_uses_calendar_month_mean(self) -> None:
        """右图月度柱应是当月全部采样日 RankIC 的算术平均。"""
        monthly_rank_ic = _monthly_rank_ic(
            pd.DataFrame(
                {
                    "date": pd.to_datetime(
                        ["2024-01-05", "2024-01-12", "2024-02-02"]
                    ),
                    "rank_ic": [0.1, 0.3, -0.2],
                }
            )
        )
        self.assertEqual(monthly_rank_ic.index.astype(str).tolist(), ["2024-01", "2024-02"])
        np.testing.assert_allclose(monthly_rank_ic.to_numpy(), [0.2, -0.2])

        figure = Figure()
        axis = figure.subplots()
        horizon_ic = pd.DataFrame(
            {
                "date": pd.to_datetime(["2024-01-05", "2024-02-02"]),
                "rank_ic": [0.2, -0.2],
            }
        )
        _plot_monthly_rank_ic(axis, horizon_ic, "1 week")
        cumulative_axis = figure.axes[1]
        zero_lines = [
            line
            for line in cumulative_axis.lines
            if line.get_linestyle() == "--"
        ]
        self.assertEqual(len(zero_lines), 1)
        np.testing.assert_allclose(zero_lines[0].get_ydata(), [0.0, 0.0])

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
                config.raw["plots"]["evaluation"]["group_colors"][-1],
                "#006837",
            )
            self.assertEqual(
                config.raw["plots"]["simple"]["group_colors"][-1],
                "#A50026",
            )
            self.assertEqual(
                config.raw["plots"]["evaluation"]["rank_ic_view"],
                "monthly",
            )
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
            progress_output = StringIO()
            with (
                redirect_stderr(progress_output),
                patch(
                    "src.backtest.engine.prepare_price_context",
                    wraps=backtest_engine.prepare_price_context,
                ) as prepare_price_context,
                patch(
                    "src.backtest.engine.prepare_target_context",
                    wraps=backtest_engine.prepare_target_context,
                ) as prepare_target_context,
            ):
                full_results = run(config, show_progress=True)
            self.assertEqual(prepare_price_context.call_count, 2)
            self.assertEqual(prepare_target_context.call_count, 2)
            self.assertIn("100%", progress_output.getvalue())
            self.assertIn("overall_evaluation", progress_output.getvalue())
            daily_summary = pd.read_csv(
                output_root / "factor_summary_daily.csv"
            )
            weekly_summary = pd.read_csv(
                output_root / "factor_summary_weekly.csv"
            )
            self.assertEqual(len(daily_summary), len(FACTOR_NAMES))
            self.assertEqual(len(weekly_summary), len(FACTOR_NAMES))
            self.assertEqual(
                set(weekly_summary["factor_name"]),
                set(FACTOR_NAMES),
            )
            self.assertTrue(
                weekly_summary[
                    [
                        "factor_coverage_rate",
                        "rank_ic_mean_1w",
                        "rank_icir_1w",
                        "oriented_long_short_return_1w",
                        "group_monotonicity_1w",
                    ]
                ].notna().all().all()
            )
            self.assertTrue(
                weekly_summary[
                    [
                        "total_return_1w",
                        "annual_return_1w",
                        "sharpe_1w",
                        "turnover_1w",
                        "benchmark_total_return_1w",
                        "excess_total_return_1w",
                    ]
                ].notna().all().all()
            )
            self.assertNotIn("mode", weekly_summary.columns)
            self.assertFalse((output_root / "metrics_summary.csv").exists())
            self.assertFalse(
                (output_root / "factor_screening_summary.csv").exists()
            )
            self.assertTrue((output_root / "config_snapshot.yaml").is_file())
            evaluation = load_evaluation_results(
                ["return_10d"],
                output_root,
            )["return_10d"]
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
                list(full_results.stage_counts),
                [
                    "factors",
                    "group_return",
                    "overall_evaluation",
                    "simple_backtest",
                    "account_backtest",
                    "plotter",
                ],
            )
            self.assertEqual(
                {
                    path.name
                    for path in (output_root / "00_overall").glob("*.png")
                },
                OVERALL_FIGURE_FILES,
            )
            self.assertEqual(
                full_results.stage_counts["overall_evaluation"],
                len(FACTOR_NAMES),
            )
            self.assertFalse((output_root / ".pipeline_cache").exists())
            self._assert_outputs(output_root)

            cache_directory = Path(config_data["market_data"]["cache_root"])
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
            self.assertEqual(
                {
                    path.name
                    for path in cache_directory.glob("*.meta.json")
                },
                {
                    "index_price.meta.json",
                    "index_membership.meta.json",
                    "stock_quote.meta.json",
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

    def test_external_returns_drive_evaluation_and_simple(self) -> None:
        """外部日收益应同时替代 evaluation 标签和 simple 持仓收益。"""
        with TemporaryDirectory() as temporary_directory:
            workspace = Path(temporary_directory)
            config_path = workspace / "external_returns.yaml"
            config_data = self._test_config(workspace / "price_output")
            config_data["market_data"]["cache_root"] = str(
                workspace / "market_cache"
            )
            config_data["run"].update(
                {
                    "account_backtest": False,
                    "plotter": False,
                    "overall_evaluation": False,
                }
            )
            config_data["output"]["save_backtest_details"] = True
            config_data["output"]["save_parquet"].update(
                {
                    "group_return": True,
                    "simple_backtest": True,
                }
            )
            self._write_config(config_path, config_data)
            run(load_config(config_path))
            price_output = Path(config_data["output"]["root"])

            market_data = MarketData.from_yaml(config_path)
            close_prices = market_data.get_panel(
                "stock_quote",
                "S_DQ_ADJCLOSE",
            )
            external_returns = close_prices.pct_change(fill_method=None)
            external_return_path = workspace / "daily_returns.parquet"
            external_returns.to_parquet(external_return_path)

            config_data["output"]["root"] = str(workspace / "return_output")
            config_data["external_returns"] = {
                "path": str(external_return_path),
            }
            config_data["simple_backtest"]["benchmark"]["source"] = "zero"
            self._write_config(config_path, config_data)
            run(load_config(config_path))
            external_output = Path(config_data["output"]["root"])

            price_evaluation = load_evaluation_results(
                ["return_10d"],
                price_output,
            )["return_10d"]
            external_evaluation = load_evaluation_results(
                ["return_10d"],
                external_output,
            )["return_10d"]
            self.assertNotIn("members", external_evaluation)
            self.assertNotIn("labels", external_evaluation)
            np.testing.assert_allclose(
                price_evaluation["detail"]["group_return"],
                external_evaluation["detail"]["group_return"],
                equal_nan=True,
            )
            np.testing.assert_allclose(
                price_evaluation["ic"][["ic", "rank_ic"]],
                external_evaluation["ic"][["ic", "rank_ic"]],
                equal_nan=True,
            )

            price_curve = load_backtest_results(
                ["return_10d"],
                price_output,
                "simple",
            )["return_10d"]["periods"][1]["groups"]["G10"]["curves"][
                "daily"
            ]
            external_curve = load_backtest_results(
                ["return_10d"],
                external_output,
                "simple",
            )["return_10d"]["periods"][1]["groups"]["G10"]["curves"][
                "daily"
            ]
            np.testing.assert_allclose(
                price_curve["cumulative_return"],
                external_curve["cumulative_return"],
                rtol=1e-10,
                atol=1e-12,
            )
            np.testing.assert_allclose(
                external_curve["benchmark_cumulative_return"],
                0.0,
            )

            factor_panel = load_factor_panels(external_output)["return_10d"]
            excess_settings = deepcopy(load_config(config_path).raw["group_return"])
            excess_settings["target"] = {
                "type": "benchmark_excess_return",
                "benchmark_source": "index_price",
            }
            excess_evaluation = evaluate(
                factor_panel=factor_panel,
                market_data=market_data,
                settings=excess_settings,
                return_panel=external_returns,
            )
            np.testing.assert_allclose(
                external_evaluation["ic"][["ic", "rank_ic"]],
                excess_evaluation["ic"][["ic", "rank_ic"]],
                equal_nan=True,
            )
            self.assertFalse(
                np.allclose(
                    external_evaluation["detail"]["group_return"],
                    excess_evaluation["detail"]["group_return"],
                    equal_nan=True,
                )
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
                    "overall_evaluation": False,
                }
            )
            for section_name in ["simple_backtest", "account_backtest"]:
                config_data[section_name]["rebalance"] = {
                    "frequency": "daily",
                    "intervals": [1, 5],
                }
            config_data["metrics"]["return_frequency"] = "rebalance"
            self._write_config(config_path, config_data)

            summary = run(load_config(config_path))
            self.assertEqual(summary.stage_counts["factors"], 2)
            daily_summary = pd.read_csv(
                output_root / "factor_summary_daily.csv"
            )
            self.assertEqual(len(daily_summary), len(FACTOR_NAMES))
            self.assertIn("sharpe_1d", daily_summary.columns)
            self.assertIn("sharpe_5d", daily_summary.columns)
            self.assertNotIn("mode", daily_summary.columns)
            factor_panel = load_factor_panels(output_root)["return_10d"]
            backtest_results = {
                mode: load_backtest_results(
                    ["return_10d"],
                    output_root,
                    mode,
                )["return_10d"]
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
            self.assertEqual(len(restored_summary["metrics"]), 24)

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
                "target": {"type": "stock_return"},
                "future_return_days": [1],
                "future_return_weeks": [1, 2, 4],
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
        """禁止读取原始数据后只运行 Factor，确认市场缓存可复用。"""
        config_data = deepcopy(source_config)
        config_data["run"].update(
            {
                "factors": True,
                "group_return": False,
                "simple_backtest": False,
                "account_backtest": False,
                "plotter": False,
                "overall_evaluation": False,
                "refresh_market_data": False,
            }
        )
        self._write_config(config_path, config_data)
        with (
            patch(
                "src.data.market_data.load_data",
                side_effect=AssertionError("缓存命中时不应读取原始来源"),
            ),
            patch(
                "src.data.market_data.load_index_members",
                side_effect=AssertionError("缓存命中时不应读取指数成员"),
            ),
        ):
            self.assertEqual(
                list(run(load_config(config_path)).stage_counts),
                ["factors"],
            )

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
                "overall_evaluation": False,
                "refresh_market_data": False,
            }
        )
        self._write_config(config_path, config_data)
        self.assertEqual(
            list(run(load_config(config_path)).stage_counts),
            ["plotter"],
        )

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
                "overall_evaluation": False,
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
            list(run(load_config(config_path)).stage_counts),
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
