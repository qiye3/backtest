"""验证正式输出命名空间及其底层读写接口。"""

from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace

import pandas as pd

from src.cli import _publish_successful_run
from src.factors.io import load_factor_panel, save_factor_panels
from src.output_layout import factor_output_root, strategy_output_root
from src.strategy.io import (
    find_strategy_names,
    load_strategy_targets,
    save_strategy_targets,
)


class StrategyOutputLayoutTests(unittest.TestCase):
    """覆盖同名因子和策略隔离后的保存、发现和恢复。"""

    def test_same_factor_and_strategy_name_use_separate_namespaces(self) -> None:
        """同名因子和策略应分别位于 factors 与 strategies。"""
        target_weights = pd.DataFrame(
            [[0.6, 0.4], [0.5, 0.5]],
            index=pd.DatetimeIndex(
                ["2024-02-08", "2024-05-08"],
                name="date",
            ),
            columns=["000001.SZ", "000002.SZ"],
        )
        strategy_result = {
            "strategy_name": "demo",
            "factor_name": "signal",
            "benchmark_index": "000906.SH",
            "rebalance_frequency": "quarterly",
            "periods": {1: target_weights},
        }

        with TemporaryDirectory() as temporary_directory:
            output_root = Path(temporary_directory)
            factor_root = factor_output_root(output_root)
            strategy_root = strategy_output_root(output_root)
            factor_values = target_weights.rename_axis(columns="asset_code")
            factor_path = save_factor_panels(
                {"demo": factor_values},
                factor_root,
            )["demo"]
            target_path = save_strategy_targets(strategy_result, strategy_root)
            restored_factor = load_factor_panel("demo", factor_root)
            restored_strategy = load_strategy_targets("demo", strategy_root)
            strategy_names = find_strategy_names(strategy_root)

            self.assertEqual(
                target_path.relative_to(output_root),
                Path("strategies/demo/target_weights.parquet"),
            )
            self.assertEqual(
                factor_path.relative_to(output_root),
                Path("factors/demo/factor.parquet"),
            )
            self.assertEqual(strategy_names, ("demo",))
            pd.testing.assert_frame_equal(
                restored_factor,
                factor_values,
            )
            pd.testing.assert_frame_equal(
                restored_strategy["periods"][1],
                target_weights,
                check_names=False,
            )

    def test_pipeline_publishes_same_name_without_artifact_collision(self) -> None:
        """正式发布时，同名因子与策略的文件和图不能混入对方目录。"""
        with TemporaryDirectory() as temporary_directory:
            workspace = Path(temporary_directory)
            output_root = workspace / "output"
            cache_root = output_root / ".pipeline_cache"
            retained_root = cache_root / ".retained"
            factor_cache = factor_output_root(cache_root) / "demo"
            strategy_cache = strategy_output_root(cache_root) / "demo"
            summary_cache = cache_root / "summaries"
            factor_cache.mkdir(parents=True)
            strategy_cache.mkdir(parents=True)
            summary_cache.mkdir(parents=True)

            (cache_root / "config_snapshot.yaml").write_text("run: {}\n")
            (factor_cache / "factor.parquet").write_bytes(b"factor")
            (strategy_cache / "target_weights.parquet").write_bytes(b"strategy")
            (summary_cache / "strategy_summary_quarterly_1q.csv").write_text(
                "strategy_name\ndemo\n"
            )
            factor_figure = factor_cache / "figures" / "00_factor_distribution.png"
            strategy_figure = strategy_cache / "figures" / "simple_quarterly_1q.png"
            factor_figure.parent.mkdir()
            strategy_figure.parent.mkdir()
            factor_figure.write_bytes(b"factor figure")
            strategy_figure.write_bytes(b"strategy figure")

            config = SimpleNamespace(
                output_root=output_root,
                factor_domains=None,
                raw={
                    "run": {
                        "factors": True,
                        "group_return": False,
                        "simple_backtest": False,
                        "account_backtest": False,
                        "strategies": True,
                        "strategy_simple_backtest": False,
                        "strategy_account_backtest": False,
                        "plotter": True,
                        "overall_evaluation": False,
                    },
                    "output": {
                        "save_parquet": {
                            "factor": True,
                            "strategy_weights": True,
                        }
                    },
                    "strategy_analysis": {"enabled": False},
                    "plots": {
                        "distribution": {"enabled": True},
                        "evaluation": {"enabled": False},
                        "simple": {"enabled": False},
                        "account": {"enabled": False},
                    },
                },
            )

            _publish_successful_run(
                config,
                factor_names=["demo"],
                strategy_names=["demo"],
                cache_root=cache_root,
                retained_root=retained_root,
            )

            self.assertTrue((output_root / "factors/demo/factor.parquet").is_file())
            self.assertTrue((output_root / "strategies/demo/target_weights.parquet").is_file())
            self.assertTrue(
                (output_root / "factors/demo/figures/00_factor_distribution.png").is_file()
            )
            self.assertTrue(
                (output_root / "strategies/demo/figures/simple_quarterly_1q.png").is_file()
            )
            self.assertFalse(
                (output_root / "factors/demo/figures/simple_quarterly_1q.png").exists()
            )


if __name__ == "__main__":
    unittest.main()
