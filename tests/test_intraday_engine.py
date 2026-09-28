"""验证信号时序、账户成交和公司行动。"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from src.intraday.config import (
    AccountConfig,
    CostConfig,
    ExecutionConfig,
    MinuteBacktestConfig,
    MinuteDataConfig,
    TargetConfig,
)
from src.intraday.engine import MinuteBacktestEngine


def _config() -> MinuteBacktestConfig:
    return MinuteBacktestConfig(
        path=Path("config.yaml"),
        run_name="test",
        output_root=Path("runs"),
        data=MinuteDataConfig(
            minute_root=Path("data"),
            daily_root=None,
            cache_root=Path("cache"),
            universe_name="test",
            start_date=pd.Timestamp("2025-04-01"),
            end_date=pd.Timestamp("2025-04-02"),
        ),
        targets=TargetConfig(Path("targets.csv"), "09:31:00"),
        account=AccountConfig(initial_capital=100_000, liquidate_at_end=False),
        execution=ExecutionConfig(
            slippage_bps=0,
            max_participation_rate=1,
            lot_size=100,
            execution_delay_bars=1,
            time_in_force="day",
            block_one_price_limit=False,
            enforce_t_plus_one=True,
        ),
        costs=CostConfig(
            commission_rate=0,
            minimum_commission=0,
            transfer_fee_rate=0,
            stamp_duty_rate_before_20230828=0,
            stamp_duty_rate_from_20230828=0,
        ),
        raw={},
    )


def _bars() -> pd.DataFrame:
    timestamps = pd.to_datetime(
        ["2025-04-01 09:31", "2025-04-01 09:32", "2025-04-02 09:31"]
    ).tz_localize("Asia/Shanghai")
    return pd.DataFrame(
        {
            "timestamp": timestamps,
            "code": "600000.SH",
            "open": [10.0, 10.0, 5.0],
            "high": [10.1, 10.1, 5.1],
            "low": [9.9, 9.9, 4.9],
            "close": [10.0, 10.0, 5.0],
            "volume": [100_000, 100_000, 100_000],
            "vwap": [10.0, 10.0, 5.0],
        }
    )


def test_signal_executes_only_on_next_bar() -> None:
    targets = pd.DataFrame(
        {
            "signal_timestamp": [pd.Timestamp("2025-04-01 09:31", tz="Asia/Shanghai")],
            "code": ["600000.SH"],
            "target_weight": [0.5],
        }
    )

    result = MinuteBacktestEngine(_config()).run(_bars(), targets)

    assert len(result.fills) == 1
    assert result.fills.loc[0, "timestamp"] == pd.Timestamp(
        "2025-04-01 09:32", tz="Asia/Shanghai"
    )
    assert result.fills.loc[0, "shares"] == 5_000


def test_share_distribution_preserves_equity_when_price_adjusts() -> None:
    targets = pd.DataFrame(
        {
            "signal_timestamp": [pd.Timestamp("2025-04-01 09:31", tz="Asia/Shanghai")],
            "code": ["600000.SH"],
            "target_weight": [1.0],
        }
    )
    actions = pd.DataFrame(
        {
            "date": [pd.Timestamp("2025-04-02")],
            "code": ["600000.SH"],
            "cash_dividend_per_share": [0.0],
            "share_ratio": [1.0],
        }
    )

    result = MinuteBacktestEngine(_config()).run(_bars(), targets, actions)

    day_one_nav = result.nav.loc[1, "nav"]
    day_two_nav = result.nav.loc[2, "nav"]
    assert day_one_nav == day_two_nav == 100_000
    assert result.positions.iloc[-1]["shares"] == 20_000


def test_unfilled_day_order_is_resubmitted_next_trading_day() -> None:
    bars = _bars()
    bars["volume"] = [100, 100, 100_000]
    targets = pd.DataFrame(
        {
            "signal_timestamp": [pd.Timestamp("2025-04-01 09:31", tz="Asia/Shanghai")],
            "code": ["600000.SH"],
            "target_weight": [1.0],
        }
    )

    result = MinuteBacktestEngine(_config()).run(bars, targets)

    assert result.orders["status"].tolist() == ["cancelled", "filled"]
    assert result.orders["created_at"].dt.date.astype(str).tolist() == [
        "2025-04-01",
        "2025-04-02",
    ]
