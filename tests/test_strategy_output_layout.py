"""验证策略产物直接位于输出根下的策略目录。"""

from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

import pandas as pd

from src.strategy.io import (
    find_strategy_names,
    load_strategy_targets,
    save_strategy_targets,
)


class StrategyOutputLayoutTests(unittest.TestCase):
    """覆盖扁平策略目录的保存、发现和恢复。"""

    def test_strategy_targets_use_one_strategy_directory(self) -> None:
        """策略结果不应再额外嵌套 strategies 目录。"""
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
            target_path = save_strategy_targets(strategy_result, output_root)
            restored = load_strategy_targets("demo", output_root)
            strategy_names = find_strategy_names(output_root)

            self.assertEqual(
                target_path.relative_to(output_root),
                Path("demo/target_weights.parquet"),
            )
            self.assertFalse((output_root / "strategies").exists())
            self.assertEqual(strategy_names, ("demo",))
            pd.testing.assert_frame_equal(
                restored["periods"][1],
                target_weights,
                check_names=False,
            )


if __name__ == "__main__":
    unittest.main()
