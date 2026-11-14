"""正式日频策略的固定分钟成交窗口与跨日未成交目标处理。"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pandas as pd
import pytest

from src.intraday.config import (
    AccountConfig,
    CostConfig,
    ExecutionConfig,
    MinuteBacktestConfig,
    MinuteDataConfig,
    TargetConfig,
    load_minute_config,
)
from src.intraday.engine import MinuteBacktestEngine
from src.intraday.execution import ExecutionModel, Order, Position


def _config(*, capital: float = 100_000.0, participation: float = 1.0,
            retry_days: int = 5) -> MinuteBacktestConfig:
    return MinuteBacktestConfig(
        path=Path("unused.yaml"), run_name="fixed", output_root=Path("runs"),
        data=MinuteDataConfig(
            minute_root=Path("data"), daily_root=None, cache_root=Path("cache"),
            universe_name="000852.SH", start_date=pd.Timestamp("2025-04-01"),
            end_date=pd.Timestamp("2025-04-09"),
        ),
        targets=TargetConfig(path=None, date_only_signal_time="15:00:00"),
        account=AccountConfig(initial_capital=capital),
        execution=ExecutionConfig(
            slippage_bps=0.0, max_participation_rate=participation,
            block_one_price_limit=True, enforce_t_plus_one=True,
            order_time="10:00:00", window_start="10:01:00",
            window_end="10:05:00", retry_unfilled_days=retry_days,
        ),
        costs=CostConfig(
            commission_rate=0, minimum_commission=0, transfer_fee_rate=0,
            stamp_duty_rate_before_20230828=0, stamp_duty_rate_from_20230828=0,
        ),
        raw={},
    )


def _bar(day: str, clock: str, code: str = "600000.SH", *, price: float = 10.0,
         volume: float = 100_000, limit_up: float | None = None,
         limit_down: float | None = None) -> dict:
    return {
        "timestamp": pd.Timestamp(f"{day} {clock}", tz="Asia/Shanghai"),
        "code": code, "open": price, "high": price + 0.2,
        "low": price - 0.2, "close": price,
        "vwap": price, "volume": volume,
        "limit_up": limit_up, "limit_down": limit_down,
    }


def _targets(*items: tuple[str, str, float]) -> pd.DataFrame:
    return pd.DataFrame(
        [(pd.Timestamp(when, tz="Asia/Shanghai"), code, weight)
         for when, code, weight in items],
        columns=["signal_timestamp", "code", "target_weight"],
    )


def test_previous_bar_reference_and_prior_day_signal_only() -> None:
    market = pd.DataFrame([
        _bar("2025-04-01", "15:00", price=10),
        _bar("2025-04-02", "09:59", price=20),
        _bar("2025-04-02", "10:00", price=10),
        _bar("2025-04-02", "10:01", price=30),
    ])
    targets = _targets(("2025-04-01 15:00", "600000.SH", 0.5))
    result = MinuteBacktestEngine(_config()).run(market, targets)

    # 10:00 下单只能读取 09:59 已完成的价格20元，10:00及10:01价格不能提前用于下单。
    assert len(result.fills) == 1
    assert result.fills.iloc[0]["shares"] == 2500
    assert result.orders.iloc[0]["created_at"] == pd.Timestamp(
        "2025-04-02 10:00", tz="Asia/Shanghai"
    )
    assert result.fills.iloc[0]["timestamp"] == pd.Timestamp(
        "2025-04-02 10:01", tz="Asia/Shanghai"
    )


def test_signal_generated_on_same_day_cannot_trade_earlier_that_day() -> None:
    market = pd.DataFrame([
        _bar("2025-04-01", "09:59"),
        _bar("2025-04-01", "10:00"),
        _bar("2025-04-01", "10:01"),
        _bar("2025-04-01", "15:00"),
        _bar("2025-04-02", "09:59"),
        _bar("2025-04-02", "10:00"),
        _bar("2025-04-02", "10:01"),
    ])
    target = _targets(("2025-04-01 09:00", "600000.SH", 1.0))
    result = MinuteBacktestEngine(_config()).run(market, target)
    assert result.orders["created_at"].dt.date.astype(str).tolist() == ["2025-04-02"]


def test_stale_previous_day_price_does_not_enable_order() -> None:
    market = pd.DataFrame([
        _bar("2025-04-01", "15:00"),
        _bar("2025-04-02", "10:00"),
        _bar("2025-04-02", "10:01"),
    ])
    result = MinuteBacktestEngine(_config()).run(
        market, _targets(("2025-04-01 15:00", "600000.SH", 0.5))
    )
    assert result.orders.empty and result.fills.empty


def test_order_time_is_scheduled_even_if_1000_bar_missing() -> None:
    market = pd.DataFrame([
        _bar("2025-04-01", "15:00"),
        _bar("2025-04-02", "09:59"),
        _bar("2025-04-02", "10:01"),
    ])
    result = MinuteBacktestEngine(_config()).run(
        market, _targets(("2025-04-01 15:00", "600000.SH", 0.5))
    )
    assert result.orders.iloc[0]["created_at"] == pd.Timestamp(
        "2025-04-02 10:00", tz="Asia/Shanghai"
    )
    assert result.fills.iloc[0]["timestamp"] == pd.Timestamp(
        "2025-04-02 10:01", tz="Asia/Shanghai"
    )


def test_window_expires_remaining_order_without_using_late_bar() -> None:
    market = pd.DataFrame([
        _bar("2025-04-01", "15:00"),
        _bar("2025-04-02", "09:59"),
        _bar("2025-04-02", "10:00"),
        _bar("2025-04-02", "10:01", volume=1_000),
        _bar("2025-04-02", "10:05", volume=0),
        _bar("2025-04-02", "10:06", volume=500_000),
    ])
    result = MinuteBacktestEngine(_config(participation=0.1)).run(
        market, _targets(("2025-04-01 15:00", "600000.SH", 0.5))
    )

    assert result.fills["shares"].tolist() == [100]
    assert result.orders.iloc[0]["remaining_shares"] == 4_900
    assert result.orders.iloc[0]["status"] == "cancelled"
    assert result.orders.iloc[0]["reject_reason"] == "window_expired"


def test_limit_direction_blocks_non_one_price_close() -> None:
    model = ExecutionModel(_config().execution, _config().costs)
    bar = pd.Series(_bar("2025-04-02", "10:01", price=11, limit_up=11, limit_down=9))
    bar["low"] = 10.4  # 盘中曾开板，但分钟末尾封涨停。
    buy = Order(1, bar["timestamp"], "600000.SH", "buy", 100, 100)
    sell = Order(2, bar["timestamp"], "600000.SH", "sell", 100, 100)
    assert model.match(buy, bar, cash=10_000, sellable_shares=0) is None
    assert buy.last_block_reason == "buy_at_limit_up"
    assert model.match(sell, bar, cash=0, sellable_shares=100) is not None

    bar["close"] = 9
    bar["vwap"] = 9
    bar["high"] = 9.6
    bar["low"] = 8.9
    new_sell = Order(3, bar["timestamp"], "600000.SH", "sell", 100, 100)
    new_buy = Order(4, bar["timestamp"], "600000.SH", "buy", 100, 100)
    assert model.match(new_sell, bar, cash=0, sellable_shares=100) is None
    assert new_sell.last_block_reason == "sell_at_limit_down"
    assert model.match(new_buy, bar, cash=10_000, sellable_shares=0) is not None


def test_one_price_without_known_limit_blocks_that_direction() -> None:
    model = ExecutionModel(_config().execution, _config().costs)
    bar = pd.Series(_bar("2025-04-02", "10:01", price=10))
    bar["high"] = bar["low"] = 10
    buy = Order(1, bar["timestamp"], "600000.SH", "buy", 100, 100)
    assert model.match(buy, bar, cash=10_000, sellable_shares=0) is None
    assert buy.last_block_reason == "one_price_without_limit_data"
    # 已知当天涨停价时，一字普通成交价可根据真实涨停方向判断。
    bar["limit_up"] = 11
    other_buy = Order(2, bar["timestamp"], "600000.SH", "buy", 100, 100)
    assert model.match(other_buy, bar, cash=10_000, sellable_shares=0) is not None


def test_slippage_is_not_clipped_to_bar_high_but_respects_daily_limit() -> None:
    config = _config()
    model = ExecutionModel(replace(config.execution, slippage_bps=10.0), config.costs)
    bar = pd.Series(_bar("2025-04-02", "10:01", price=10))
    bar["high"] = 10.002
    bar["limit_up"] = 10.005
    order = Order(1, bar["timestamp"], "600000.SH", "buy", 100, 100)
    fill = model.match(order, bar, cash=10_000, sellable_shares=0)
    assert fill is not None and fill.price == pytest.approx(10.0)  # 10.005不是合法报价；边界内下取整


def test_sell_odd_lot_remainder_can_clear_position() -> None:
    model = ExecutionModel(_config().execution, _config().costs)
    position = Position()
    position.buy(pd.Timestamp("2025-04-01"), 250)
    order = Order(
        1, pd.Timestamp("2025-04-02 10:00", tz="Asia/Shanghai"),
        "600000.SH", "sell", 250, 250,
    )
    bar1 = pd.Series(_bar("2025-04-02", "10:01", volume=200))
    fill1 = model.match(order, bar1, cash=0, sellable_shares=250)
    assert fill1 is not None and fill1.shares == 200
    position.sell(pd.Timestamp("2025-04-02"), fill1.shares, True)
    bar2 = pd.Series(_bar("2025-04-02", "10:02", volume=50))
    fill2 = model.match(order, bar2, cash=0, sellable_shares=50)
    assert fill2 is not None and fill2.shares == 50
    position.sell(pd.Timestamp("2025-04-02"), fill2.shares, True)
    assert position.shares == 0 and order.status == "filled"


def test_sale_cash_is_only_available_from_following_bar() -> None:
    code_a, code_b = "000001.SZ", "600000.SH"
    rows = []
    for day in ["2025-04-01", "2025-04-02", "2025-04-03"]:
        clocks = ["15:00"] if day == "2025-04-01" else ["09:59", "10:00", "10:01", "10:02", "15:00"]
        for clock in clocks:
            rows += [_bar(day, clock, code_a), _bar(day, clock, code_b)]
    targets = _targets(
        ("2025-04-01 15:00", code_a, 1.0),
        ("2025-04-02 15:00", code_a, 0.0),
        ("2025-04-02 15:00", code_b, 1.0),
    )
    result = MinuteBacktestEngine(_config(capital=10_000)).run(pd.DataFrame(rows), targets)
    day3 = result.fills[result.fills["timestamp"].dt.day == 3]
    assert list(zip(day3["side"], day3["timestamp"].dt.strftime("%H:%M"))) == [
        ("sell", "10:01"), ("buy", "10:02"),
    ]


def test_cash_is_allocated_by_demand_not_stock_code_order() -> None:
    a, b = "000001.SZ", "600000.SH"
    market = pd.DataFrame([
        _bar("2025-04-01", "15:00", a), _bar("2025-04-01", "15:00", b),
        _bar("2025-04-02", "09:59", a), _bar("2025-04-02", "09:59", b),
        _bar("2025-04-02", "10:00", a), _bar("2025-04-02", "10:00", b),
        _bar("2025-04-02", "10:01", a, price=20),
        _bar("2025-04-02", "10:01", b, price=20),
    ])
    result = MinuteBacktestEngine(_config(capital=10_000)).run(
        market, _targets(("2025-04-01 15:00", a, 0.3),
                         ("2025-04-01 15:00", b, 0.7))
    )
    by_code = result.fills.groupby("code")["shares"].sum().to_dict()
    assert by_code[b] > by_code[a] >= 100
    assert result.nav.iloc[-1]["cash"] >= -1e-9


def test_only_unfilled_target_retries_next_day_and_stops_after_limit() -> None:
    market = pd.DataFrame([
        _bar("2025-04-01", "15:00"),
        _bar("2025-04-02", "09:59"),
        _bar("2025-04-02", "10:00"),
        _bar("2025-04-02", "10:01", price=11, limit_up=11),
        _bar("2025-04-02", "15:00", price=11),
        _bar("2025-04-03", "09:59", price=11),
        _bar("2025-04-03", "10:00", price=11),
        _bar("2025-04-03", "10:01", price=11, limit_up=12),
        _bar("2025-04-03", "15:00", price=11),
        _bar("2025-04-04", "09:59", price=11),
        _bar("2025-04-04", "10:00", price=11),
        _bar("2025-04-04", "10:01", price=11),
    ])
    target = _targets(("2025-04-01 15:00", "600000.SH", 0.5))
    result = MinuteBacktestEngine(_config(retry_days=1)).run(market, target)
    assert result.orders["created_at"].dt.date.astype(str).tolist() == [
        "2025-04-02", "2025-04-03",
    ]
    assert result.orders["status"].tolist() == ["cancelled", "filled"]
    assert result.fills["timestamp"].dt.date.astype(str).tolist() == ["2025-04-03"]

    without_retry = MinuteBacktestEngine(_config(retry_days=0)).run(market, target)
    assert len(without_retry.orders) == 1
    assert without_retry.fills.empty


def test_new_signal_replaces_old_unfilled_target() -> None:
    a, b = "000001.SZ", "600000.SH"
    market = pd.DataFrame([
        _bar("2025-04-01", "15:00", a), _bar("2025-04-01", "15:00", b),
        _bar("2025-04-02", "09:59", a), _bar("2025-04-02", "09:59", b),
        _bar("2025-04-02", "10:00", a), _bar("2025-04-02", "10:00", b),
        _bar("2025-04-02", "10:01", a, price=11, limit_up=11),
        _bar("2025-04-02", "10:01", b),
        _bar("2025-04-02", "15:00", a), _bar("2025-04-02", "15:00", b),
        _bar("2025-04-03", "09:59", a), _bar("2025-04-03", "09:59", b),
        _bar("2025-04-03", "10:00", a), _bar("2025-04-03", "10:00", b),
        _bar("2025-04-03", "10:01", a), _bar("2025-04-03", "10:01", b),
    ])
    targets = _targets(
        ("2025-04-01 15:00", a, 1),
        ("2025-04-02 15:00", b, 1),
    )
    result = MinuteBacktestEngine(_config()).run(market, targets)
    assert result.orders["code"].tolist() == [a, b]
    assert result.fills["code"].tolist() == [b]


def test_fixed_window_batch_and_daily_stream_match() -> None:
    market = pd.DataFrame([
        _bar("2025-04-01", "15:00"),
        _bar("2025-04-02", "09:59"),
        _bar("2025-04-02", "10:00"),
        _bar("2025-04-02", "10:01"),
        _bar("2025-04-02", "15:00"),
        _bar("2025-04-03", "09:59"),
        _bar("2025-04-03", "10:00"),
        _bar("2025-04-03", "10:01"),
    ])
    targets = _targets(("2025-04-01 15:00", "600000.SH", 0.5))
    batch = MinuteBacktestEngine(_config()).run(market, targets)
    chunks = [v for _, v in market.groupby(market["timestamp"].dt.date)]
    stream = MinuteBacktestEngine(_config()).run_stream(chunks, targets)
    pd.testing.assert_frame_equal(batch.orders, stream.orders)
    pd.testing.assert_frame_equal(batch.fills, stream.fills)
    pd.testing.assert_frame_equal(batch.nav, stream.nav)


def test_fixed_mode_config_parses_and_rejects_invalid_window(tmp_path: Path) -> None:
    minute = tmp_path / "minute"
    minute.mkdir()
    targets = tmp_path / "targets.csv"
    targets.write_text(
        "signal_timestamp,code,target_weight\n2025-04-01,600000.SH,0.5\n", encoding="utf-8"
    )
    text = f"""
run_name: fixed
output_root: runs
data:
  minute_root: {minute}
  daily_root: null
  cache_root: cache
  universe_name: 000852.SH
  start_date: 2025-04-01
  end_date: 2025-04-02
targets:
  path: {targets}
  date_only_signal_time: "15:00:00"
account:
  initial_capital: 100000
execution:
  slippage_bps: 5
  max_participation_rate: 0.05
  block_one_price_limit: true
  enforce_t_plus_one: true
  order_time: "10:00:00"
  window_bars: 5
  retry_unfilled_days: 2
costs:
  commission_rate: 0.0003
  minimum_commission: 5
  transfer_fee_rate: 0.00001
  stamp_duty_rate_before_20230828: 0.001
  stamp_duty_rate_from_20230828: 0.0005
"""
    path = tmp_path / "config.yaml"
    path.write_text(text, encoding="utf-8")
    loaded = load_minute_config(path)
    assert loaded.execution.window_start == "10:01:00"
    assert loaded.execution.window_end == "10:05:00"
    assert loaded.execution.retry_unfilled_days == 2
    path.write_text(text.replace('window_bars: 5', 'window_bars: 500'), encoding='utf-8')
    with pytest.raises(ValueError, match='window_bars'):
        load_minute_config(path)
