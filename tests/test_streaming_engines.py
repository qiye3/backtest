"""验证批量引擎的流式接口保持原有计算口径。"""

from __future__ import annotations

import unittest

import numpy as np
import pandas as pd

from src.data.market_data import MarketData
from src.factors import Factor, calc_factors, iter_factor_panels


class _ScaledPanelFactor(Factor):
    """返回固定倍数面板的最小测试因子。"""

    def calc(self, market_data: MarketData) -> pd.DataFrame:
        values = np.arange(
            len(market_data.calendar) * len(market_data.membership.columns),
            dtype=float,
        ).reshape(market_data.membership.shape)
        return pd.DataFrame(
            values * self.config["scale"],
            index=market_data.calendar,
            columns=market_data.membership.columns,
        )


class StreamingEngineTests(unittest.TestCase):
    """覆盖流式因子结果与原批量字典接口的一致性。"""

    def test_factor_iterator_matches_batch_result(self) -> None:
        """并行 iterator 的每个面板应与保留的批量接口完全一致。"""
        calendar = pd.bdate_range("2024-01-02", periods=6, name="date")
        stock_codes = pd.Index(["000001.SZ", "000002.SZ"], name="asset_code")
        membership = pd.DataFrame(
            True,
            index=calendar,
            columns=stock_codes,
        )
        membership.iloc[-1, -1] = False
        market_data = MarketData(
            source_panels={},
            calendar=calendar,
            membership=membership,
            benchmark_index="000906.SH",
        )
        factors = [
            _ScaledPanelFactor({"name": "factor_a", "scale": 1.0}),
            _ScaledPanelFactor({"name": "factor_b", "scale": -2.0}),
        ]

        expected = calc_factors(factors, market_data, max_workers=1)
        streamed = dict(
            iter_factor_panels(factors, market_data, max_workers=2)
        )

        self.assertEqual(set(streamed), set(expected))
        for factor_name, expected_panel in expected.items():
            pd.testing.assert_frame_equal(
                streamed[factor_name],
                expected_panel,
            )


if __name__ == "__main__":
    unittest.main()
