"""v4：发单参考价、增量下载补缺、单路径配置与旧目标下载范围。"""
from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pandas as pd
import pytest

from src.config import load_config
from src.intraday import free_minute
from src.intraday.engine import MinuteBacktestEngine
from src.intraday.execution import Position
from tests.test_intraday_fixed_window import _bar, _config, _targets


def test_retired_daily_account_stages_are_absent() -> None:
    config = load_config(Path("configs/base_config.yaml"))
    assert set(config.raw["run"]) == {
        "factors", "group_return", "strategies", "plotter", "overall_evaluation",
        "max_workers", "refresh_market_data",
    }
    assert set(config.raw["output"]["save_parquet"]) == {
        "factor", "group_return", "strategy_weights",
    }


def test_0931_can_use_only_known_previous_close() -> None:
    config = _config(capital=100_000.0)
    config = replace(config, execution=replace(config.execution,
        order_time="09:31:00", window_start="09:32:00", window_end="09:36:00"))
    data = pd.DataFrame([
        _bar("2025-04-01", "15:00", price=10),
        _bar("2025-04-02", "09:31", price=25),
        _bar("2025-04-02", "09:32", price=12),
    ])
    result = MinuteBacktestEngine(config).run(data, _targets(("2025-04-01 15:00", "600000.SH", .5)))
    assert result.orders.iloc[0]["created_at"].strftime("%H:%M") == "09:31"
    assert result.fills.iloc[0]["shares"] == 5_000  # 以昨收10计算；不用当日09:31的25


def test_missing_prior_price_fails_instead_of_silent_order_loss() -> None:
    config = _config()
    config = replace(config, execution=replace(config.execution,
        order_time="09:31:00", window_start="09:32:00", window_end="09:36:00"))
    data = pd.DataFrame([
        _bar("2025-04-02", "09:31", price=25),
        _bar("2025-04-02", "09:32", price=12),
    ])
    with pytest.raises(ValueError, match="前日已知收盘价"):
        MinuteBacktestEngine(config).run(data, _targets(("2025-04-01 15:00", "600000.SH", .5)))


def test_missing_held_price_does_not_turn_holding_into_zero() -> None:
    engine = MinuteBacktestEngine(_config())
    engine.positions["600000.SH"] = Position(shares=100, lots_by_date={pd.Timestamp("2025-04-01"): 100})
    with pytest.raises(ValueError, match="缺少可用估值价格"):
        engine._portfolio_value()


def test_existing_daily_file_repairs_missing_window_without_redownloading_others(tmp_path, monkeypatch) -> None:
    def save_fake(frame, path):
        path.parent.mkdir(parents=True, exist_ok=True)
        frame.to_pickle(path)
    monkeypatch.setattr(free_minute, "_write_parquet_atomic", save_fake)
    monkeypatch.setattr(pd, "read_parquet", lambda path, **kwargs: pd.read_pickle(path))
    today = tmp_path / "2025" / "2025-01-02.parquet"
    save_fake(pd.DataFrame({
        "timestamp": [pd.Timestamp("2025-01-02 09:31", tz="Asia/Shanghai")],
        "code": ["000001.SZ"], "volume": [100], "close": [10],
    }), today)
    calls = []
    def fetcher(code, day):
        calls.append(code)
        return pd.DataFrame({
            "时间": ["2025-01-02 13:21:00"], "开盘": [10], "最高": [10],
            "最低": [10], "收盘": [10], "成交量": [5], "成交额": [5_000],
        })
    updater = free_minute.FreeMinuteDailyUpdater(tmp_path, fetcher, delay_seconds=0, min_coverage=1)
    done = updater.update_day("2025-01-02", ["000001.SZ", "000002.SZ"],
        required_codes=["000001.SZ"], required_window=("13:21:00", "13:25:00"))
    assert calls == ["000001.SZ", "000002.SZ"]
    assert done.received_codes == 2
    assert set(pd.read_pickle(today)["code"]) == {"000001.SZ", "000002.SZ"}
    again = updater.update_day("2025-01-02", ["000001.SZ", "000002.SZ"],
        required_codes=["000001.SZ"], required_window=("13:21:00", "13:25:00"))
    assert again.existed and calls == ["000001.SZ", "000002.SZ"]


def test_known_suspension_does_not_lower_minute_data_coverage(tmp_path, monkeypatch) -> None:
    def write(frame, path):
        path.parent.mkdir(parents=True, exist_ok=True)
        frame.to_pickle(path)
    monkeypatch.setattr(free_minute, "_write_parquet_atomic", write)
    def fetcher(code, day):
        if code == "000002.SZ":
            return pd.DataFrame()
        return pd.DataFrame({"时间": ["2025-01-02 13:21"],
            "开盘": [10], "最高": [10], "最低": [10], "收盘": [10],
            "成交量": [2], "成交额": [2000]})
    updater = free_minute.FreeMinuteDailyUpdater(tmp_path, fetcher, delay_seconds=0, min_coverage=1)
    summary = updater.update_day("2025-01-02", ["000001.SZ", "000002.SZ"],
        required_codes=["000001.SZ"], exempt_codes=["000002.SZ"])
    assert summary.received_codes == 1
