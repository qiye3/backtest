"""v4：对交易正确性与运行范围精简的回归测试。"""

from dataclasses import replace

import pandas as pd
import pytest

from src.intraday.engine import MinuteBacktestEngine
from src.intraday.execution import ExecutionModel, Order, Position
from src.intraday.free_minute import missing_execution_minutes
from scripts.run_minute_backtest import _execution_codes_for_day
from tests.test_intraday_fixed_window import _config, _bar, _targets
from tests.test_paper_csi1000_v2 import _member_source
from src.intraday.universe import HistoricalIndexUniverse


def test_0931_order_uses_previous_day_close_only():
    config = _config()
    execution = replace(config.execution, order_time="09:31:00", window_start="09:32:00", window_end="09:36:00")
    config = replace(config, execution=execution)
    bars = pd.DataFrame([
        _bar("2025-04-01", "15:00", price=10),
        _bar("2025-04-02", "09:31", price=20),
        _bar("2025-04-02", "09:32", price=20),
    ])
    target = _targets(("2025-04-01 15:00", "600000.SH", 0.5))
    result = MinuteBacktestEngine(config).run(bars, target)
    assert result.orders.iloc[0]["requested_shares"] == 5000
    assert result.orders.iloc[0]["created_at"].strftime("%H:%M") == "09:31"


def test_0931_without_prior_close_fails_explicitly():
    config = _config()
    config = replace(config, execution=replace(
        config.execution, order_time="09:31:00", window_start="09:32:00", window_end="09:36:00",
    ))
    bars = pd.DataFrame([_bar("2025-04-02", "09:31"), _bar("2025-04-02", "09:32")])
    target = _targets(("2025-04-01 15:00", "600000.SH", 0.5))
    with pytest.raises(ValueError, match="前日已知收盘价"):
        MinuteBacktestEngine(config).run(bars, target)


def test_unpriced_position_is_not_silently_valued_at_zero():
    engine = MinuteBacktestEngine(_config())
    engine.positions["600000.SH"] = Position(
        shares=100, lots_by_date={pd.Timestamp("2025-04-01"): 100},
    )
    with pytest.raises(ValueError, match="缺少可用估值价格"):
        engine._portfolio_value()


def test_exchange_order_legality_while_fills_may_be_odd_lot():
    config = _config()
    matcher = ExecutionModel(config.execution, config.costs)
    bar = pd.Series(_bar("2025-04-02", "10:01", volume=120))
    illegal = Order(
        order_id=1, created_at=bar["timestamp"], code="600000.SH", side="buy",
        requested_shares=101, remaining_shares=101,
    )
    with pytest.raises(ValueError, match="非法 A 股委托"):
        matcher.match(illegal, bar, cash=10000, sellable_shares=0)
    legal = Order(
        order_id=2, created_at=bar["timestamp"], code="600000.SH", side="buy",
        requested_shares=100, remaining_shares=100,
    )
    result = matcher.match(legal, bar, cash=10000, sellable_shares=0)
    assert result is not None and result.shares == 100
    assert isinstance(result.shares, int)


def test_required_window_detects_partially_missing_minutes():
    bars = pd.DataFrame([_bar("2025-04-02", f"10:0{m}") for m in (1,2,4,5)])
    missing = missing_execution_minutes(
        bars, "2025-04-02", ["600000.SH"], ("10:01:00", "10:05:00"),
    )
    assert missing == {"600000.SH": 1}
    complete = pd.concat([bars, pd.DataFrame([_bar("2025-04-02", "10:03")])])
    assert not missing_execution_minutes(
        complete, "2025-04-02", ["600000.SH"], ("10:01:00", "10:05:00"),
    )


def test_daily_load_does_not_include_every_old_target(tmp_path):
    universe = HistoricalIndexUniverse(_member_source(tmp_path))
    engine = MinuteBacktestEngine(_config())
    engine.active_target_weights = {"600000.SH": 1.0}
    target = _targets(("2025-01-02 15:00", "000001.SZ", 0.5))
    engine._last_applied_signal_timestamp = pd.Timestamp("2025-01-02 15:00", tz="Asia/Shanghai")
    codes = _execution_codes_for_day(universe, engine, pd.Timestamp("2025-01-06"), target)
    assert "000002.SZ" in codes
    assert "600000.SH" not in codes
