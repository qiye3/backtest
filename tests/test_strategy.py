"""验证 Factor 信号到目标权重、增强回测和策略图的公共链路。"""

from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

import numpy as np
import pandas as pd
import yaml

from src.backtest import engine as backtest_engine
from src.backtest import iter_weight_backtests, run_weight_backtests
from src.backtest.targets import rebalance_dates
from src.data.market_data import MarketData
from src.plotter.strategy import plot_strategy_backtest, plot_weight_deviation
from src.strategy.config import load_strategy
from src.strategy.evaluation import calculate_weight_deviation
from src.strategy.io import load_strategy_targets, save_strategy_targets
from strategies.yfd_growth100_factors.portfolio import CniGrowth100Portfolio


class StrategyTests(unittest.TestCase):
    """覆盖季度调仓、组合规则、持久化、回测和图像输出。"""

    def test_quarterly_rebalance_uses_sixth_trading_day(self) -> None:
        calendar = pd.bdate_range("2024-01-01", "2024-11-30", name="date")
        dates = rebalance_dates(
            calendar=calendar,
            start="2024-01-01",
            end="2024-11-30",
            rebalance={
                "frequency": "quarterly",
                "intervals": [1],
                "months": [2, 5, 8, 11],
                "trading_day": 6,
            },
            interval=1,
            initial_entry="first_rebalance",
        )
        expected = pd.DatetimeIndex(
            [
                "2024-02-08",
                "2024-05-08",
                "2024-08-08",
                "2024-11-08",
            ],
            name="date",
        )
        pd.testing.assert_index_equal(dates, expected)

    def test_strategy_yaml_dynamically_loads_portfolio_rule(self) -> None:
        """Strategy YAML 应通过 dotted module 和 class 加载外部组合规则。"""
        strategy_config = {
            "name": "growth100",
            "factor_name": "growth_score",
            "benchmark_index": "000906.SH",
            "implementation": {
                "module": "strategies.yfd_growth100_factors.portfolio",
                "class": "CniGrowth100Portfolio",
            },
            "params": {
                "top_n": 100,
                "max_replacements": 50,
                "tilt_strength": 1.0,
                "max_weight": 0.1,
            },
        }
        with TemporaryDirectory() as temporary_directory:
            config_path = Path(temporary_directory) / "strategy.yaml"
            config_path.write_text(
                yaml.safe_dump(strategy_config, sort_keys=False),
                encoding="utf-8",
            )
            strategy = load_strategy(config_path)
        self.assertIsInstance(strategy, CniGrowth100Portfolio)

    def test_growth100_portfolio_limits_replacements_and_caps_weights(
        self,
    ) -> None:
        stock_codes = pd.Index(
            [f"{stock_number:06d}.SZ" for stock_number in range(200)],
            name="asset_code",
        )
        dates = pd.DatetimeIndex(
            ["2024-02-08", "2024-05-08", "2024-08-08"],
            name="date",
        )
        first_signal = np.arange(200, 0, -1, dtype=float)
        second_signal = np.concatenate(
            [np.arange(100, 0, -1, dtype=float), np.arange(200, 100, -1)]
        )
        third_signal = np.arange(200, 0, -1, dtype=float)
        third_signal[:50] = np.nan
        third_signal[100:120] = np.nan
        signals = pd.DataFrame(
            [first_signal, second_signal, third_signal],
            index=dates,
            columns=stock_codes,
        )
        market_data = _portfolio_market_data(dates, stock_codes)
        strategy = CniGrowth100Portfolio(
            {
                "name": "growth100",
                "factor_name": "growth_score",
                "benchmark_index": "000906.SH",
                "params": {
                    "top_n": 100,
                    "max_replacements": 50,
                    "tilt_strength": 1.0,
                    "max_weight": 0.10,
                },
            }
        )

        targets = strategy.build_target_weights(signals, market_data, dates)

        first_members = targets.iloc[0].loc[lambda values: values > 0].index
        second_members = targets.iloc[1].loc[lambda values: values > 0].index
        third_members = targets.iloc[2].loc[lambda values: values > 0].index
        self.assertEqual(len(first_members), 100)
        self.assertEqual(len(second_members), 100)
        self.assertEqual(len(third_members), 100)
        self.assertEqual(len(second_members.difference(first_members)), 50)
        self.assertTrue(third_members.isin(signals.iloc[2].dropna().index).all())
        np.testing.assert_allclose(targets.sum(axis=1), 1.0)
        self.assertLessEqual(targets.to_numpy().max(), 0.10 + 1e-12)

    def test_strategy_target_io_and_weight_deviation(self) -> None:
        dates = pd.DatetimeIndex(["2024-02-08", "2024-05-08"], name="date")
        target_weights = pd.DataFrame(
            [[0.6, 0.4], [0.5, 0.5]],
            index=dates,
            columns=["000001.SZ", "000002.SZ"],
        )
        result = {
            "strategy_name": "demo",
            "factor_name": "signal",
            "benchmark_index": "000906.SH",
            "rebalance_frequency": "quarterly",
            "periods": {1: target_weights},
        }
        with TemporaryDirectory() as temporary_directory:
            save_strategy_targets(result, temporary_directory)
            restored = load_strategy_targets("demo", temporary_directory)
        pd.testing.assert_frame_equal(
            restored["periods"][1],
            target_weights,
            check_names=False,
        )

        benchmark_weights = pd.DataFrame(
            [[0.5, 0.5], [0.4, 0.6]],
            index=dates,
            columns=target_weights.columns,
        )
        deviation = calculate_weight_deviation(
            target_weights,
            benchmark_weights,
        )
        np.testing.assert_allclose(deviation["active_share"], [0.1, 0.1])
        np.testing.assert_allclose(deviation["max_overweight"], [0.1, 0.1])
        np.testing.assert_allclose(deviation["max_underweight"], [-0.1, -0.1])

    def test_weight_backtests_and_strategy_figures(self) -> None:
        market_data = _backtest_market_data()
        rebalance_index = pd.DatetimeIndex(
            ["2024-01-05", "2024-02-02", "2024-03-01"],
            name="date",
        )
        target_weights = pd.DataFrame(
            [[0.7, 0.3], [0.4, 0.6], [0.8, 0.2]],
            index=rebalance_index,
            columns=market_data.membership.columns,
        )
        settings = _backtest_settings()
        metrics_settings = _metrics_settings()

        simple_result = run_weight_backtests(
            {1: target_weights},
            market_data,
            settings,
            metrics_settings,
            mode="simple",
            rebalance_frequency="quarterly",
            max_workers=1,
        )
        account_result = run_weight_backtests(
            {1: target_weights},
            market_data,
            {**settings, "initial_capital": 1_000_000},
            metrics_settings,
            mode="account",
            rebalance_frequency="quarterly",
            max_workers=1,
        )
        zero_cost_settings = {**settings, "transaction_cost_rate": 0.0}
        gross_simple_result = run_weight_backtests(
            {1: target_weights},
            market_data,
            zero_cost_settings,
            metrics_settings,
            mode="simple",
            rebalance_frequency="quarterly",
            max_workers=1,
        )
        gross_account_result = run_weight_backtests(
            {1: target_weights},
            market_data,
            {**zero_cost_settings, "initial_capital": 1_000_000},
            metrics_settings,
            mode="account",
            rebalance_frequency="quarterly",
            max_workers=1,
        )
        lean_account_result = run_weight_backtests(
            {1: target_weights},
            market_data,
            {**settings, "initial_capital": 1_000_000},
            metrics_settings,
            mode="account",
            rebalance_frequency="quarterly",
            max_workers=1,
            collect_details=False,
        )

        self.assertEqual(simple_result["metrics"].iloc[0]["group_id"], "strategy")
        self.assertEqual(account_result["metrics"].iloc[0]["group_id"], "strategy")
        self.assertIn("daily", simple_result["periods"][1]["groups"]["strategy"]["curves"])
        simple_group = simple_result["periods"][1]["groups"]["strategy"]
        gross_simple_group = gross_simple_result["periods"][1]["groups"]["strategy"]
        account_group = account_result["periods"][1]["groups"]["strategy"]
        gross_account_group = gross_account_result["periods"][1]["groups"]["strategy"]
        np.testing.assert_allclose(
            simple_group["curves"]["all"]["gross_cumulative_return"],
            gross_simple_group["curves"]["all"]["cumulative_return"],
        )
        np.testing.assert_allclose(
            account_group["curves"]["all"]["gross_nav"],
            gross_account_group["curves"]["all"]["nav"],
        )
        lean_account_group = lean_account_result["periods"][1]["groups"][
            "strategy"
        ]
        self.assertTrue(lean_account_group["trades"].empty)
        self.assertTrue(lean_account_group["holdings"].empty)
        pd.testing.assert_frame_equal(
            lean_account_result["metrics"],
            account_result["metrics"],
        )

        benchmark_weights = pd.DataFrame(
            0.5,
            index=rebalance_index,
            columns=target_weights.columns,
        )
        with TemporaryDirectory() as temporary_directory:
            output_root = Path(temporary_directory)
            plot_settings = _plot_settings()
            strategy_paths = plot_strategy_backtest(
                strategy_name="demo",
                backtest_result=simple_result,
                mode="simple",
                interval=1,
                settings=plot_settings,
                output_stem=output_root / "strategy",
                backtest_settings=settings,
                benchmark_index="000906.SH",
            )
            deviation_paths = plot_weight_deviation(
                strategy_name="demo",
                target_weights=target_weights,
                benchmark_weights=benchmark_weights,
                settings=plot_settings,
                output_stem=output_root / "deviation",
                rebalance_label="quarterly-1",
            )
            self.assertTrue(all(path.exists() for path in strategy_paths))
            self.assertTrue(all(path.exists() for path in deviation_paths))

    def test_weight_backtest_batch_prepares_price_context_once(self) -> None:
        """多策略批量回测应共享同一价格上下文。"""
        market_data = _backtest_market_data()
        rebalance_index = pd.DatetimeIndex(
            ["2024-01-05", "2024-02-02", "2024-03-01"],
            name="date",
        )
        target_weights = pd.DataFrame(
            [[0.7, 0.3], [0.4, 0.6], [0.8, 0.2]],
            index=rebalance_index,
            columns=market_data.membership.columns,
        )
        strategy_items = [
            ("strategy_a", {1: target_weights}, "quarterly"),
            ("strategy_b", {1: target_weights}, "quarterly"),
        ]

        with patch(
            "src.backtest.engine.prepare_price_context",
            wraps=backtest_engine.prepare_price_context,
        ) as prepare_price_context:
            results = dict(
                iter_weight_backtests(
                    strategy_items=strategy_items,
                    market_data=market_data,
                    settings=_backtest_settings(),
                    metrics_settings=_metrics_settings(),
                    mode="simple",
                    max_workers=2,
                )
            )

        self.assertEqual(set(results), {"strategy_a", "strategy_b"})
        self.assertEqual(prepare_price_context.call_count, 1)


def _portfolio_market_data(
    dates: pd.DatetimeIndex,
    stock_codes: pd.Index,
) -> MarketData:
    """构造只包含成长100权重规则所需字段的市场数据。"""
    free_shares = pd.DataFrame(1.0, index=dates, columns=stock_codes)
    close_prices = pd.DataFrame(10.0, index=dates, columns=stock_codes)
    source_panels = {
        "free_float": _source_panel({"S_SHARE_FREESHARES": free_shares}),
        "stock_quote": _source_panel({"S_DQ_CLOSE": close_prices}),
    }
    membership = pd.DataFrame(True, index=dates, columns=stock_codes)
    return MarketData(
        source_panels=source_panels,
        calendar=dates,
        membership=membership,
        benchmark_index="000906.SH",
    )


def _backtest_market_data() -> MarketData:
    """构造可同时运行 simple 和 account 的小型价格面板。"""
    calendar = pd.bdate_range("2024-01-02", "2024-03-29", name="date")
    stock_codes = pd.Index(["000001.SZ", "000002.SZ"], name="asset_code")
    stock_prices = pd.DataFrame(
        {
            "000001.SZ": np.linspace(10.0, 12.0, len(calendar)),
            "000002.SZ": np.linspace(10.0, 9.5, len(calendar)),
        },
        index=calendar,
    )
    benchmark_prices = pd.DataFrame(
        {"000906.SH": np.linspace(100.0, 103.0, len(calendar))},
        index=calendar,
    )
    membership = pd.DataFrame(True, index=calendar, columns=stock_codes)
    return MarketData(
        source_panels={
            "stock_quote": _source_panel({"S_DQ_ADJCLOSE": stock_prices}),
            "index_price": _source_panel({"S_DQ_CLOSE": benchmark_prices}),
        },
        calendar=calendar,
        membership=membership,
        benchmark_index="000906.SH",
    )


def _source_panel(fields: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """把测试字段拼成 MarketData 使用的来源级列结构。"""
    return pd.concat(fields, axis=1, names=["field", "asset_code"])


def _backtest_settings() -> dict:
    """返回目标权重回测需要的最小有效设置。"""
    return {
        "start": "2024-01-02",
        "end": "2024-03-29",
        "trade_price": "close",
        "benchmark": {"source": "index_price"},
        "initial_capital": 1.0,
        "transaction_cost_rate": 0.001,
        "charge_initial_cost": True,
        "liquidate_at_end": False,
        "missing_price_policy": "previous_close",
        "max_stale_days": None,
        "curve_frequency": "both",
        "execution": {"policy": "ideal"},
    }


def _metrics_settings() -> dict:
    """返回测试回测的风险和年化指标口径。"""
    return {
        "risk_free_rate": 0.0,
        "return_frequency": "daily",
        "annual_trading_days": 252,
        "annual_weeks": 52,
        "include_initial_turnover": True,
        "simple_annual_return": "linear",
        "account_annual_return": "compound",
    }


def _plot_settings() -> dict:
    """返回策略图保存需要的最小绘图设置。"""
    return {
        "formats": ["png"],
        "dpi": 80,
        "width": 10.0,
        "row_height": 3.0,
        "font_family": "DejaVu Sans",
        "curve_frequency": "daily",
        "note": "",
    }


if __name__ == "__main__":
    unittest.main()
