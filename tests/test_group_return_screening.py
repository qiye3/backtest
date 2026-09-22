"""验证第一阶段因子筛选汇总的方向和稳定性口径。"""

from __future__ import annotations

import unittest

import pandas as pd

from src.backtest.io import build_metrics_summary
from src.group_return.screening import (
    build_factor_screening_summary,
    build_frequency_summaries,
)


class FactorScreeningSummaryTests(unittest.TestCase):
    """验证负向因子不会因原始 RankIC 和多空符号被错误淘汰。"""

    def test_negative_factor_is_oriented_for_screening(self) -> None:
        """负向因子的 Q1-Q10 和同号比例应转换为正向筛选指标。"""
        evaluation_results = {
            "negative_factor": {
                "definitions": pd.DataFrame(
                    {
                        "group_id": ["G1", "G10"],
                        "quantile_lower": [0.0, 0.9],
                        "quantile_upper": [0.1, 1.0],
                    }
                ),
                "factor_quality": pd.DataFrame(
                    {
                        "factor_coverage_rate": [0.9],
                        "factor_zero_rate": [0.1],
                    }
                ),
                "ic_summary": pd.DataFrame(
                    {
                        "horizon_value": [1],
                        "horizon_unit": ["weeks"],
                        "start": ["2024-01-01"],
                        "end": ["2024-01-31"],
                        "n_dates": [3],
                        "n_complete_dates": [2],
                        "ic_mean": [-0.08],
                        "ic_std": [0.04],
                        "icir": [-2.0],
                        "ic_n_dates": [3],
                        "rank_ic_mean": [-0.10],
                        "rank_ic_std": [0.05],
                        "rank_icir": [-2.0],
                        "rank_ic_n_dates": [3],
                    }
                ),
                "ic": pd.DataFrame(
                    {
                        "horizon_value": [1, 1, 1],
                        "horizon_unit": ["weeks"] * 3,
                        "n_stocks": [100, 90, 80],
                        "rank_ic": [-0.2, -0.15, 0.05],
                    }
                ),
                "summary": pd.DataFrame(
                    {
                        "horizon_value": [1, 1],
                        "horizon_unit": ["weeks", "weeks"],
                        "group_id": ["G1", "G10"],
                        "group_return": [0.03, 0.01],
                    }
                ),
                "detail": pd.DataFrame(
                    {
                        "date": pd.to_datetime(
                            ["2024-01-05"] * 2 + ["2024-01-12"] * 2
                        ),
                        "horizon_value": [1] * 4,
                        "horizon_unit": ["weeks"] * 4,
                        "group_id": ["G1", "G10", "G1", "G10"],
                        "group_return": [0.03, 0.01, 0.00, 0.01],
                    }
                ),
            }
        }

        summary = build_factor_screening_summary(
            evaluation_results,
            {"target": {"type": "benchmark_excess_return"}},
        ).iloc[0]

        self.assertEqual(summary["factor_direction"], "negative")
        self.assertAlmostEqual(summary["valid_date_ratio"], 2 / 3)
        self.assertAlmostEqual(summary["factor_coverage_rate"], 0.9)
        self.assertAlmostEqual(summary["rank_ic_positive_rate"], 1 / 3)
        self.assertAlmostEqual(summary["rank_ic_consistent_rate"], 2 / 3)
        self.assertAlmostEqual(summary["high_minus_low_return"], -0.02)
        self.assertAlmostEqual(summary["oriented_long_short_return"], 0.02)
        self.assertAlmostEqual(summary["group_monotonicity"], -1.0)
        self.assertAlmostEqual(summary["long_short_consistent_rate"], 0.5)
        self.assertEqual(summary["mean_stock_count"], 90.0)
        self.assertEqual(summary["min_stock_count"], 80)

    def test_frequency_summary_has_one_row_per_factor(self) -> None:
        """不同周期应横向展开，simple 汇总只写入 G10 且没有 mode。"""
        screening_summary = pd.DataFrame(
            {
                "factor_name": ["factor_a", "factor_a"],
                "base_factor_name": ["factor_a", "factor_a"],
                "variant": ["raw", "raw"],
                "domain": ["full_universe", "full_universe"],
                "target_type": ["stock_return", "stock_return"],
                "horizon_value": [1, 2],
                "horizon_unit": ["weeks", "weeks"],
                "factor_coverage_rate": [0.9, 0.9],
                "factor_zero_rate": [0.1, 0.1],
                **{
                    column: [1.0, 2.0]
                    for column in [
                        "start",
                        "end",
                        "n_dates",
                        "n_complete_dates",
                        "valid_date_ratio",
                        "mean_stock_count",
                        "min_stock_count",
                        "ic_mean",
                        "ic_std",
                        "icir",
                        "ic_n_dates",
                        "rank_ic_mean",
                        "rank_ic_std",
                        "rank_icir",
                        "rank_ic_n_dates",
                        "rank_ic_positive_rate",
                        "factor_direction",
                        "rank_ic_consistent_rate",
                        "q1_return",
                        "q10_return",
                        "high_minus_low_return",
                        "oriented_long_short_return",
                        "group_monotonicity",
                        "long_short_consistent_rate",
                    ]
                },
            }
        )
        metrics = pd.DataFrame(
            {
                "group_id": ["G1", "G10"],
                "quantile_lower": [0.0, 0.9],
                "quantile_upper": [0.1, 1.0],
                "rebalance_frequency": ["weekly", "weekly"],
                "rebalance_interval": [1, 1],
                "mode": ["simple", "simple"],
                "total_return": [0.1, 0.2],
                "annual_return": [0.2, 0.3],
                "sharpe": [1.0, 2.0],
                "mean_turnover": [0.3, 0.4],
                "annual_turnover": [3.0, 4.0],
                "benchmark_total_return": [0.05, 0.05],
                "excess_total_return": [0.05, 0.15],
            }
        )

        backtest_summary = build_metrics_summary(
            {"factor_a": {"metrics": metrics}}
        )
        weekly_summary = build_frequency_summaries(
            screening_summary,
            backtest_summary,
        )["weekly"]

        self.assertEqual(len(weekly_summary), 1)
        self.assertEqual(weekly_summary.at[0, "rank_ic_mean_1w"], 1.0)
        self.assertEqual(weekly_summary.at[0, "rank_ic_mean_2w"], 2.0)
        self.assertEqual(weekly_summary.at[0, "total_return_1w"], 0.2)
        self.assertEqual(weekly_summary.at[0, "mean_turnover_1w"], 0.4)
        self.assertNotIn("mode", weekly_summary.columns)


if __name__ == "__main__":
    unittest.main()
