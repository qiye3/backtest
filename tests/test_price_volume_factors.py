"""验证参数化价量因子的核心公式和配置批次数量。"""

from __future__ import annotations

import unittest
from pathlib import Path

import numpy as np
import pandas as pd

from src.config import load_config
from src.data.market_data import MarketData
from src.factors.config import load_factors
from src.factors.PriceVolumeFactor import PriceVolumeFactor

PROJECT_ROOT = Path(__file__).resolve().parents[1]
CONFIG_DIRECTORY = PROJECT_ROOT / "factors" / "price_volume_factors" / "config"
RUN_CONFIG_PATH = PROJECT_ROOT / "configs" / "price_volume_30.yaml"


class PriceVolumeFactorTests(unittest.TestCase):
    """校验代表性价格、成交量和流动性公式。"""

    def setUp(self) -> None:
        """构造两个股票、八个交易日的确定性价量面板。"""
        calendar = pd.bdate_range("2024-01-02", periods=8, name="date")
        asset_codes = pd.Index(["000001.SZ", "000002.SZ"], name="asset_code")
        close = pd.DataFrame(
            {
                "000001.SZ": [10, 11, 12, 13, 14, 15, 16, 17],
                "000002.SZ": [20, 19, 21, 20, 22, 21, 23, 22],
            },
            index=calendar,
        )
        volume = pd.DataFrame(
            {
                "000001.SZ": [100, 110, 120, 130, 140, 150, 160, 170],
                "000002.SZ": [200, 180, 220, 190, 230, 200, 240, 210],
            },
            index=calendar,
        )
        amount = close * volume
        stock_quote = pd.concat(
            {
                "S_DQ_ADJCLOSE": close,
                "S_DQ_VOLUME": volume,
                "S_DQ_AMOUNT": amount,
            },
            axis=1,
            names=["field", "asset_code"],
        )
        membership = pd.DataFrame(True, index=calendar, columns=asset_codes)
        self.market_data = MarketData(
            source_panels={"stock_quote": stock_quote},
            calendar=calendar,
            membership=membership,
            benchmark_index="000906.SH",
        )

    def test_batch_defines_exactly_thirty_unique_factors(self) -> None:
        """价量批次应显式定义三十个不重名因子。"""
        factors = load_factors(CONFIG_DIRECTORY)
        self.assertEqual(len(factors), 30)
        self.assertEqual(len({factor.name for factor in factors}), 30)

    def test_momentum_matches_period_return(self) -> None:
        """动量应等于当前价相对窗口起点价的收益。"""
        factor = self._factor("momentum", window=3)
        values = factor.calc(self.market_data)
        self.assertAlmostEqual(values.iloc[-1, 0], 17 / 14 - 1)

    def test_volume_ratio_uses_short_and_long_averages(self) -> None:
        """量比应比较短长窗口的平均成交量。"""
        factor = self._factor("volume_ratio", short_window=2, long_window=4)
        values = factor.calc(self.market_data)
        expected = np.mean([160, 170]) / np.mean([140, 150, 160, 170]) - 1
        self.assertAlmostEqual(values.iloc[-1, 0], expected)

    def test_amihud_uses_absolute_return_and_amount(self) -> None:
        """Amihud 非流动性应取绝对收益成交额比的窗口均值。"""
        factor = self._factor("amihud_illiquidity", window=3)
        values = factor.calc(self.market_data)
        close = np.array([14, 15, 16, 17], dtype=float)
        volume = np.array([150, 160, 170], dtype=float)
        daily_returns = np.diff(close) / close[:-1]
        amounts = close[1:] * volume
        expected = np.mean(np.abs(daily_returns) / amounts * 100_000_000)
        self.assertAlmostEqual(values.iloc[-1, 0], expected)

    def test_histogram_bins_are_explicitly_configurable(self) -> None:
        """单因子和总体直方图应分别读取独立的柱数配置。"""
        config = load_config(RUN_CONFIG_PATH)
        distribution_settings = config.raw["plots"]["distribution"]
        self.assertEqual(distribution_settings["bins"], 300)
        self.assertEqual(distribution_settings["overall_bins"], 50)

    def _factor(self, formula: str, **params: int) -> PriceVolumeFactor:
        """构造一个只用于公式断言的价量因子。"""
        return PriceVolumeFactor(
            {
                "name": f"test_{formula}",
                "params": {"formula": formula, **params},
            }
        )


if __name__ == "__main__":
    unittest.main()
