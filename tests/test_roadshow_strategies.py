"""验证路演指数策略的配置、调样日期和权重约束。"""

from __future__ import annotations

import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import numpy as np
import pandas as pd

from src.backtest.targets import rebalance_dates
from src.config import load_config
from src.factors.config import load_factors
from src.strategy.config import load_strategies
from strategies.roadshow_indices.portfolio import (
    MarketValuePortfolio,
    _cap_and_redistribute,
)


class RoadshowIndexStrategyTests(unittest.TestCase):
    """覆盖五套策略共享的框架接入和指数约束。"""

    def test_all_methodology_configs_load(self) -> None:
        config = load_config(Path("strategies/roadshow_indices/run.yaml"))

        factor_names = {factor.name for factor in load_factors(config.factor_config_directory)}
        strategy_names = {
            strategy.name for strategy in load_strategies(config.strategy_config_directory)
        }

        self.assertEqual(len(factor_names), 6)
        self.assertEqual(len(strategy_names), 6)
        self.assertEqual(
            strategy_names,
            {
                "cni_growth100",
                "csi500_quality_growth",
                "csi_technology_top",
                "csi_dividend_low_volatility100",
                "cni_value100",
                "cni_free_cashflow",
            },
        )
        weight_source = config.raw["market_data"]["sources"]["index_weights_monthly"]
        self.assertEqual(weight_source["codes"], ["000906.SH"])
        self.assertEqual(weight_source["fields"], ["I_WEIGHT"])

    def test_insufficient_candidates_use_all_and_record_diagnostics(self) -> None:
        """候选股不足时应按配置降级，并保留实际选样口径。"""
        rebalance_date = pd.Timestamp("2024-03-11")
        stock_codes = pd.Index(["000001.SZ", "000002.SZ", "000003.SZ"])
        signals = pd.DataFrame(
            [[3.0, 2.0, 1.0]],
            index=pd.DatetimeIndex([rebalance_date], name="date"),
            columns=stock_codes,
        )
        market_values = pd.DataFrame(
            [[3.0, 2.0, 1.0]],
            index=signals.index,
            columns=stock_codes,
        )
        market_data = SimpleNamespace(
            membership=pd.DataFrame(True, index=signals.index, columns=stock_codes),
            get_panel=lambda *_args, **_kwargs: market_values,
        )
        strategy = MarketValuePortfolio(
            {
                "name": "small_universe",
                "factor_name": "score",
                "benchmark_index": "000906.SH",
                "params": {
                    "top_n": 5,
                    "insufficient_candidates_policy": "warn_and_use_all",
                },
            }
        )

        with patch("warnings.warn") as warn:
            targets = strategy.build_target_weights(
                signals,
                market_data,
                signals.index,
            )

        self.assertEqual(targets.ne(0).sum(axis=1).iloc[0], 3)
        self.assertEqual(
            strategy.selection_diagnostics.iloc[0].to_dict(),
            {
                "date": rebalance_date,
                "candidate_count": 3,
                "requested_top_n": 5,
                "selected_count": 3,
                "status": "warn_and_use_all",
            },
        )
        warn.assert_called_once()

    def test_second_friday_rule_uses_next_trading_day(self) -> None:
        calendar = pd.bdate_range("2024-03-01", "2024-12-31", name="date")

        dates = rebalance_dates(
            calendar=calendar,
            start="2024-03-01",
            end="2024-12-31",
            rebalance={
                "frequency": "quarterly",
                "intervals": [1],
                "months": [3, 6, 9, 12],
                "date_rule": "second_friday_next_trading_day",
            },
            interval=1,
            initial_entry="first_rebalance",
        )

        expected = pd.DatetimeIndex(
            ["2024-03-11", "2024-06-17", "2024-09-16", "2024-12-16"],
            name="date",
        )
        pd.testing.assert_index_equal(dates, expected)

    def test_stock_and_industry_caps_are_applied_together(self) -> None:
        stock_codes = pd.Index([f"S{number:02d}" for number in range(20)])
        raw_weights = pd.Series(np.arange(20, 0, -1, dtype=float), index=stock_codes)
        industries = pd.Series(
            np.repeat(["A", "B", "C", "D", "E"], 4),
            index=stock_codes,
        )

        weights = _cap_and_redistribute(
            raw_weights,
            max_weight=0.10,
            industries=industries,
            max_industry_weight=0.25,
        )

        self.assertAlmostEqual(weights.sum(), 1.0)
        self.assertLessEqual(weights.max(), 0.10 + 1e-12)
        self.assertLessEqual(weights.groupby(industries).sum().max(), 0.25 + 1e-12)


if __name__ == "__main__":
    unittest.main()
