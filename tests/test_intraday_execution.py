"""验证成交容量、滑点、费用、T+1 和现金约束。"""

from __future__ import annotations

import pandas as pd
import pytest

from src.intraday.config import CostConfig, ExecutionConfig
from src.intraday.execution import ExecutionModel, Order, Position


def _execution_config() -> ExecutionConfig:
    return ExecutionConfig(
        slippage_bps=5,
        max_participation_rate=0.1,
        block_one_price_limit=False,
        enforce_t_plus_one=True,
    )


def _cost_config() -> CostConfig:
    return CostConfig(
        commission_rate=0.0003,
        minimum_commission=5,
        transfer_fee_rate=0.00001,
        stamp_duty_rate_before_20230828=0.001,
        stamp_duty_rate_from_20230828=0.0005,
    )


def _bar(timestamp: str, volume: int = 10_000) -> pd.Series:
    return pd.Series(
        {
            "timestamp": pd.Timestamp(timestamp, tz="Asia/Shanghai"),
            "open": 10.0,
            "high": 10.1,
            "low": 9.9,
            "close": 10.0,
            "vwap": 10.0,
            "volume": volume,
        }
    )


def test_participation_slippage_and_partial_fill_across_bars() -> None:
    model = ExecutionModel(_execution_config(), _cost_config())
    order = Order(1, pd.Timestamp("2025-04-01 09:30", tz="Asia/Shanghai"), "600000.SH", "buy", 1500, 1500)

    first = model.match(order, _bar("2025-04-01 09:31"), 1_000_000, 0)
    second = model.match(order, _bar("2025-04-01 09:32"), 1_000_000, 0)

    assert first is not None and first.shares == 1000
    assert first.price == pytest.approx(10.01)  # A股最小报价单位0.01元
    assert first.commission == 5
    assert second is not None and second.shares == 500
    assert second.commission == 0
    assert order.status == "filled"


def test_sell_stamp_duty_boundary() -> None:
    model = ExecutionModel(_execution_config(), _cost_config())
    before = Order(1, pd.Timestamp("2023-08-25", tz="Asia/Shanghai"), "600000.SH", "sell", 1000, 1000)
    after = Order(2, pd.Timestamp("2023-08-28", tz="Asia/Shanghai"), "600000.SH", "sell", 1000, 1000)

    old_fill = model.match(before, _bar("2023-08-25 09:31"), 0, 1000)
    new_fill = model.match(after, _bar("2023-08-28 09:31"), 0, 1000)

    assert old_fill is not None and new_fill is not None
    assert old_fill.stamp_duty == old_fill.notional * 0.001
    assert new_fill.stamp_duty == new_fill.notional * 0.0005


def test_cash_constraint_allows_odd_partial_fill_from_legal_order() -> None:
    model = ExecutionModel(_execution_config(), _cost_config())
    order = Order(1, pd.Timestamp("2025-04-01", tz="Asia/Shanghai"), "600000.SH", "buy", 1000, 1000)

    fill = model.match(order, _bar("2025-04-01 09:31"), 2_020, 0)

    assert fill is not None and fill.shares == 201
    assert fill.notional + fill.total_cost <= 2_020


def test_position_enforces_t_plus_one() -> None:
    position = Position()
    position.buy(pd.Timestamp("2025-04-01"), 1000)

    assert position.sellable_shares(pd.Timestamp("2025-04-01"), True) == 0
    assert position.sellable_shares(pd.Timestamp("2025-04-02"), True) == 1000
