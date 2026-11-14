from __future__ import annotations

import json
import os
import zipfile
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
from src.intraday.data import MinuteArchiveReader, load_daily_trade_status
from src.intraday.engine import MinuteBacktestEngine
from src.intraday.execution import ExecutionModel, Order
from src.intraday.strategy import DailyMinuteContext, generate_daily_strategy_targets
from src.intraday.targets import normalize_target_weights


def _config(tmp_path: Path, *, initial_capital: float = 100_000.0) -> MinuteBacktestConfig:
    return MinuteBacktestConfig(
        path=tmp_path / "config.yaml",
        run_name="test",
        output_root=tmp_path / "runs",
        data=MinuteDataConfig(
            minute_root=tmp_path,
            daily_root=None,
            cache_root=tmp_path / "cache",
            universe_name="test",
            start_date=pd.Timestamp("2025-01-02"),
            end_date=pd.Timestamp("2025-01-03"),
        ),
        targets=TargetConfig(
            path=None,
            date_only_signal_time="09:30:00",
        ),
        account=AccountConfig(
            initial_capital=initial_capital,
            ),
        execution=ExecutionConfig(
            slippage_bps=10,
            max_participation_rate=1.0,
            block_one_price_limit=False,
            enforce_t_plus_one=True,
        ),
        costs=CostConfig(
            commission_rate=0.0003,
            minimum_commission=5.0,
            transfer_fee_rate=0.00001,
            stamp_duty_rate_before_20230828=0.001,
            stamp_duty_rate_from_20230828=0.0005,
        ),
        raw={},
    )


def _bars(rows: list[tuple[str, str, float]]) -> pd.DataFrame:
    records = []
    for timestamp, code, close in rows:
        records.append(
            {
                "timestamp": pd.Timestamp(timestamp, tz="Asia/Shanghai"),
                "code": code,
                "open": close,
                "high": close + 1,
                "low": close - 1,
                "close": close,
                "amount": close * 100_000,
                "volume": 100_000,
                "vwap": close,
            }
        )
    return pd.DataFrame(records)


def _targets(rows: list[tuple[str, str, float]]) -> pd.DataFrame:
    frame = pd.DataFrame(rows, columns=["signal_timestamp", "code", "target_weight"])
    return normalize_target_weights(frame, "09:30:00")


def test_first_filled_bar_cost_is_included_in_total_return(tmp_path: Path) -> None:
    config = _config(tmp_path)
    market = _bars([
        ("2025-01-02 15:00", "600000.SH", 10.0),
        ("2025-01-03 09:59", "600000.SH", 10.0),
        ("2025-01-03 10:00", "600000.SH", 10.0),
        ("2025-01-03 10:01", "600000.SH", 10.0),
    ])
    targets = _targets([("2025-01-02 15:00", "600000.SH", 0.5)])
    result = MinuteBacktestEngine(config).run(market, targets)
    assert result.metrics["initial_nav"] == config.account.initial_capital
    assert result.metrics["total_return"] < 0
    assert result.metrics["transaction_cost"] > 0


def test_missing_reference_price_is_deferred_until_next_day(tmp_path: Path) -> None:
    config = _config(tmp_path)
    market = _bars([
        ("2025-01-02 15:00", "000001.SZ", 10.0),
        ("2025-01-03 09:59", "000001.SZ", 10.0),
        ("2025-01-03 10:00", "000001.SZ", 10.0),
        ("2025-01-03 10:01", "600000.SH", 10.0),
        ("2025-01-06 09:59", "600000.SH", 10.0),
        ("2025-01-06 10:00", "600000.SH", 10.0),
        ("2025-01-06 10:01", "600000.SH", 10.0),
    ])
    targets = _targets([("2025-01-02 15:00", "600000.SH", 0.5)])
    result = MinuteBacktestEngine(config).run(market, targets)
    assert len(result.fills) == 1
    assert result.fills.iloc[0]["timestamp"] == pd.Timestamp(
        "2025-01-06 10:01", tz="Asia/Shanghai",
    )


def test_streaming_and_batch_results_match(tmp_path: Path) -> None:
    market = _bars(
        [
            ("2025-01-02 09:31", "600000.SH", 10.0),
            ("2025-01-02 09:32", "600000.SH", 10.1),
            ("2025-01-03 09:31", "600000.SH", 10.2),
            ("2025-01-03 09:32", "600000.SH", 10.3),
        ]
    )
    targets = _targets([("2025-01-02 09:30", "600000.SH", 0.5)])
    first_day = market[market["timestamp"].dt.day == 2]
    second_day = market[market["timestamp"].dt.day == 3]

    batch = MinuteBacktestEngine(_config(tmp_path / "batch")).run(market, targets)
    streamed = MinuteBacktestEngine(_config(tmp_path / "stream")).run_stream(
        [first_day, second_day],
        targets,
    )

    pd.testing.assert_frame_equal(batch.nav, streamed.nav)
    pd.testing.assert_frame_equal(batch.fills, streamed.fills)
    assert batch.metrics == streamed.metrics


def test_execution_slippage_is_preserved_outside_historical_bar_range(tmp_path: Path) -> None:
    config = _config(tmp_path)
    execution = ExecutionModel(config.execution, config.costs)
    order = Order(
        order_id=1,
        created_at=pd.Timestamp("2025-01-02 09:31", tz="Asia/Shanghai"),
        code="600000.SH",
        side="buy",
        requested_shares=100,
        remaining_shares=100,
    )
    bar = pd.Series(
        {
            "timestamp": order.created_at,
            "high": 10.005,
            "low": 9.9,
            "close": 10.0,
            "vwap": 10.0,
            "volume": 100_000,
        }
    )

    fill = execution.match(order, bar, cash=10_000, sellable_shares=0)

    assert fill is not None
    assert fill.price == pytest.approx(10.01)


def test_rights_issue_subscribes_and_deducts_cash(tmp_path: Path) -> None:
    config = _config(tmp_path)
    market = _bars([
        ("2025-01-02 15:00", "600000.SH", 10.0),
        ("2025-01-03 09:59", "600000.SH", 10.0),
        ("2025-01-03 10:00", "600000.SH", 10.0),
        ("2025-01-03 10:01", "600000.SH", 10.0),
        ("2025-01-06 09:31", "600000.SH", 8.0),
    ])
    targets = _targets([("2025-01-02 15:00", "600000.SH", 0.5)])
    actions = pd.DataFrame({
        "date": [pd.Timestamp("2025-01-06")],
        "code": ["600000.SH"],
        "cash_dividend_per_share": [0.0],
        "share_ratio": [0.0],
        "rights_ratio": [0.2],
        "rights_price": [5.0],
    })
    result = MinuteBacktestEngine(config).run(market, targets, actions)
    first_fill_shares = int(result.fills.iloc[0]["shares"])
    final_position = int(result.positions.iloc[-1]["shares"])
    assert final_position == first_fill_shares + int(first_fill_shares * 0.2)


class _EqualWeightStrategy:
    def on_day_close(
        self,
        trading_date: pd.Timestamp,
        bars: pd.DataFrame,
        context: DailyMinuteContext,
    ) -> pd.DataFrame:
        del trading_date, bars
        weight = 1 / len(context.universe_codes)
        return pd.DataFrame(
            {
                "code": context.universe_codes,
                "target_weight": weight,
            }
        )


def test_daily_strategy_signal_is_stamped_at_close() -> None:
    first_day = _bars(
        [
            ("2025-01-02 09:31", "600000.SH", 10.0),
            ("2025-01-02 15:00", "600000.SH", 10.2),
        ]
    )

    targets = generate_daily_strategy_targets(
        _EqualWeightStrategy(),
        [first_day],
        ["600000.SH"],
    )

    assert targets.iloc[0]["signal_timestamp"] == pd.Timestamp(
        "2025-01-02 15:00",
        tz="Asia/Shanghai",
    )


def test_cache_rebuilds_when_source_archive_changes(tmp_path: Path) -> None:
    minute_root = tmp_path / "minute"
    minute_root.mkdir()
    archive_path = minute_root / "20250102.zip"
    _write_minute_archive(archive_path, close=10.0)
    reader = MinuteArchiveReader(minute_root, tmp_path / "cache", "test")
    first = reader.read_day("2025-01-02", ["600000.SH"])

    _write_minute_archive(archive_path, close=11.0)
    archive_stat = archive_path.stat()
    os.utime(
        archive_path,
        ns=(archive_stat.st_atime_ns, archive_stat.st_mtime_ns + 1),
    )
    second = reader.read_day("2025-01-02", ["600000.SH"])

    assert first["close"].iloc[0] == 10.0
    assert second["close"].iloc[0] == 11.0
    metadata_path = tmp_path / "cache/minute/test/2025/2025-01-02.json"
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    assert metadata["source"]["mtime_ns"] == archive_path.stat().st_mtime_ns


def test_retired_execution_config_is_rejected(tmp_path: Path) -> None:
    from src.intraday.config import _load_execution_config
    with pytest.raises(ValueError, match="未知字段"):
        _load_execution_config({
            "slippage_bps": 5,
            "max_participation_rate": 0.1,
            "lot_size": 100,
            "block_one_price_limit": True,
            "enforce_t_plus_one": True,
        })


def test_daily_trade_status_normalizes_boolean_fields(tmp_path: Path) -> None:
    status_path = tmp_path / "daily_status.csv"
    status_path.write_text(
        "date,code,is_st,is_suspended,limit_up,limit_down\n"
        "2025-01-02,600000.SH,0,false,11,9\n",
        encoding="utf-8",
    )

    status = load_daily_trade_status(
        status_path,
        ["600000.SH"],
        "2025-01-02",
        "2025-01-02",
    )

    assert not bool(status.iloc[0]["is_st"])
    assert not bool(status.iloc[0]["is_suspended"])


def _write_minute_archive(path: Path, close: float) -> None:
    frame = pd.DataFrame(
        {
            "open": [close] * 240,
            "high": [close + 0.1] * 240,
            "low": [close - 0.1] * 240,
            "close": [close] * 240,
            "amount": [close * 1_000] * 240,
            "volume": [1_000] * 240,
        }
    )
    csv_content = frame.to_csv(index=False).encode("utf-8")
    with zipfile.ZipFile(path, mode="w") as archive:
        archive.writestr("sh/600000.csv", csv_content)
