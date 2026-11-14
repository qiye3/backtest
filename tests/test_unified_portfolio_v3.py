"""V3正式策略入口、可选分层与A股合法委托数量专项测试。"""

from dataclasses import replace
from pathlib import Path

import pandas as pd
import pytest

from src.backtest import run_portfolio
from src.intraday.config import (
    AccountConfig, CostConfig, ExecutionConfig, MinuteBacktestConfig,
    MinuteDataConfig, TargetConfig,
)
from src.intraday.engine import MinuteBacktestEngine
from src.intraday.execution import ExecutionModel, Order, Position
from src.intraday.layers import build_factor_layer_targets
from src.intraday.market_rules import (
    is_legal_order, planned_order_shares, share_rules, split_legal_orders,
)


def config(capital=10_000):
    return MinuteBacktestConfig(
        path=Path("test.yml"), run_name="one", output_root=Path("out"),
        data=MinuteDataConfig(Path("data"), None, Path("cache"), "CSI1000",
                              pd.Timestamp("2025-04-01"), pd.Timestamp("2025-04-15")),
        targets=TargetConfig(path=None, date_only_signal_time="15:00:00"),
        account=AccountConfig(initial_capital=capital),
        execution=ExecutionConfig(
            slippage_bps=0, max_participation_rate=1,
            block_one_price_limit=False, enforce_t_plus_one=True,
            order_time="10:00:00",
            window_start="10:01:00", window_end="10:05:00",
        ),
        costs=CostConfig(0, 0, 0, 0, 0), raw={},
    )


def bars(date, price, code="000001.SZ", volume=100_000):
    return pd.DataFrame([
        {"timestamp": pd.Timestamp(f"{date} {time}", tz="Asia/Shanghai"),
         "code": code, "open": price, "high": price + 0.1,
         "low": price - 0.1, "close": price, "vwap": price, "volume": volume}
        for time in ["09:59", "10:00", "10:01", "15:00"]
    ])


def target(date, code, weight):
    return pd.DataFrame({
        "signal_timestamp": [pd.Timestamp(f"{date} 15:00", tz="Asia/Shanghai")],
        "code": [code], "target_weight": [weight],
    })


def test_mainboard_and_chinext_submitted_quantities_are_100_multiples():
    for code in ("000001.SZ", "300123.SZ", "600000.SH"):
        assert share_rules(code).buy_step == 100
        assert is_legal_order(code, "buy", 100)
        assert is_legal_order(code, "buy", 200)
        assert not is_legal_order(code, "buy", 101)
        assert planned_order_shares(code, "buy", 199) == 100
        assert planned_order_shares(code, "buy", 99) == 0
        assert planned_order_shares(code, "sell", 250, held=250) == 250
        assert is_legal_order(code, "sell", 250, sellable_at_submit=250)
        assert not is_legal_order(code, "sell", 50, sellable_at_submit=250)
        assert is_legal_order(code, "sell", 50, sellable_at_submit=50)


def test_star_board_submission_minimum_200_then_one_share_steps():
    code = "688001.SH"
    assert share_rules(code).board == "star"
    assert not is_legal_order(code, "buy", 199)
    assert is_legal_order(code, "buy", 200)
    assert is_legal_order(code, "buy", 201)
    assert planned_order_shares(code, "buy", 201) == 201
    assert planned_order_shares(code, "buy", 199) == 0
    assert not is_legal_order(code, "sell", 199, sellable_at_submit=300)
    assert is_legal_order(code, "sell", 199, sellable_at_submit=199)
    assert is_legal_order(code, "sell", 201, sellable_at_submit=300)


def test_broker_order_limit_is_split_not_lost():
    assert split_legal_orders("600000.SH", "buy", 2_100_000) == [
        (1_000_000, None), (1_000_000, None), (100_000, None),
    ]
    assert split_legal_orders("688001.SH", "buy", 100_001) == [
        (99_801, None), (200, None),
    ]
    assert split_legal_orders("300123.SZ", "buy", 300_100) == [
        (300_000, None), (100, None),
    ]
    assert split_legal_orders("600000.SH", "sell", 1_000_050, sellable=1_000_050) == [
        (999_900, 1_000_050), (150, 150),
    ]


def test_legally_submitted_100_share_buy_can_fill_7_shares():
    cfg = config()
    model = ExecutionModel(cfg.execution, cfg.costs)
    bar = bars("2025-04-02", 10).iloc[2]
    bar["volume"] = 7
    order = Order(1, bar["timestamp"], "600000.SH", "buy", 100, 100)
    fill = model.match(order, bar, 1000, 0)
    assert fill is not None and fill.shares == 7
    assert order.remaining_shares == 93
    from src.intraday.market_rules import split_legal_orders
    with pytest.raises(ValueError, match="合规委托"):
        split_legal_orders("600000.SH", "buy", 7)


def test_buy_price_is_valid_tick_and_cash_never_negative():
    cfg = config()
    model = ExecutionModel(replace(cfg.execution, slippage_bps=5), cfg.costs)
    bar = bars("2025-04-02", 10).iloc[2]
    order = Order(1, bar["timestamp"], "600000.SH", "buy", 100, 100)
    fill = model.match(order, bar, 1010, 0)
    assert fill.price == 10.01
    assert fill.price * 100 <= 1010
    assert fill.shares == 100


def test_strict_limit_price_gate_blocks_missing_status():
    cfg = config()
    model = ExecutionModel(replace(cfg.execution, require_daily_limit_data=True), cfg.costs)
    bar = bars("2025-04-02", 10).iloc[2]
    order = Order(1, bar["timestamp"], "600000.SH", "buy", 100, 100)
    assert model.match(order, bar, 5000, 0) is None
    assert order.last_block_reason == "missing_daily_limit_data"


def test_continuous_account_nav_compounds_and_has_valid_lot_orders():
    cfg = config(capital=10_000)
    date_prices = [("2025-04-01", 10.0), ("2025-04-02", 10.0),
                   ("2025-04-03", 11.0), ("2025-04-07", 9.9)]
    result = run_portfolio(
        cfg, [bars(day, price) for day, price in date_prices],
        target("2025-04-01", "000001.SZ", 1.0),
    )
    assert len(result.nav) == 4   # 每天一条净值，不按调仓段相加
    assert result.orders.iloc[0]["requested_shares"] % 100 == 0
    assert result.nav.iloc[2]["nav"] == pytest.approx(11_000)
    assert result.nav.iloc[3]["nav"] == pytest.approx(9_900)
    assert result.metrics["final_unit_nav"] == pytest.approx(0.99)
    assert result.metrics["total_return"] == pytest.approx(-0.01)


def test_main_board_odd_lot_from_partial_fill_can_be_liquidated_next_day():
    cfg = config(capital=10_000)
    order = Order(1, pd.Timestamp("2025-04-02 10:00", tz="Asia/Shanghai"),
                  "000001.SZ", "buy", 500, 500)
    model = ExecutionModel(cfg.execution, cfg.costs)
    bar = bars("2025-04-02", 10).iloc[2]
    bar["volume"] = 157
    fill = model.match(order, bar, cash=10_000, sellable_shares=0)
    assert fill.shares == 157
    position = Position()
    position.buy(pd.Timestamp("2025-04-02"), fill.shares)
    assert position.sellable_shares(pd.Timestamp("2025-04-02"), True) == 0
    assert position.sellable_shares(pd.Timestamp("2025-04-03"), True) == 157
    sell = Order(2, pd.Timestamp("2025-04-03 10:00", tz="Asia/Shanghai"),
                 "000001.SZ", "sell", 157, 157,
                 sellable_at_submit=157)
    next_bar = bars("2025-04-03", 10).iloc[2]
    fill2 = model.match(sell, next_bar, 0, 157)
    assert fill2.shares == 157


def test_optional_factor_layers_can_use_long_csv(tmp_path):
    path = tmp_path / "factor.csv"
    pd.DataFrame([
        {"date": "2025-04-01", "code": code, "factor_value": i}
        for i, code in enumerate(("000001.SZ", "000002.SZ", "000003.SZ", "000004.SZ"))
    ]).to_csv(path, index=False)
    group = build_factor_layer_targets(path, layer_count=2)
    assert set(group) == {"G01", "G02"}
    assert group["G01"]["code"].tolist() == ["000001.SZ", "000002.SZ"]
    assert group["G02"]["code"].tolist() == ["000003.SZ", "000004.SZ"]
    assert (group["G01"]["target_weight"] == 0.5).all()


def test_factor_layers_do_not_change_single_strategy_account(tmp_path):
    path = tmp_path / "factor.csv"
    pd.DataFrame([
        {"date": "2025-04-01", "code": code, "factor_value": i}
        for i, code in enumerate(("000001.SZ", "000002.SZ"))
    ]).to_csv(path, index=False)
    layers = build_factor_layer_targets(path, layer_count=2)
    cfg = config()
    dates = [bars("2025-04-01", 10, code).assign(code=code)
             for code in ("000001.SZ", "000002.SZ")]
    day0 = pd.concat(dates, ignore_index=True)
    day1 = pd.concat([
        bars("2025-04-02", 10, code) for code in ("000001.SZ", "000002.SZ")
    ], ignore_index=True)
    unit_nets = []
    for group in layers.values():
        run = run_portfolio(cfg, [day0, day1], group)
        assert run.orders.iloc[0]["requested_shares"] % 100 == 0
        unit_nets.append(run.metrics["final_unit_nav"])
    assert unit_nets == pytest.approx([1, 1])
