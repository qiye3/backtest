"""验证部署新增的数据对齐与邮件去重。"""

import json
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo
from unittest.mock import MagicMock

import pandas as pd

from scripts import notify_minute_update, tencent_minutes, update_daily_minutes
from src.intraday.free_minute import normalize_eastmoney_minute


def test_tencent_amount_is_differenced_and_auction_bar_is_excluded(monkeypatch):
    symbol = "sz000012"
    payloads = iter([
        {"code": 0, "data": {symbol: {"m1": [
            ["202611130930", "10", "10", "10", "10", "1", {}, "0"],
            ["202611130931", "10", "10", "10", "10", "2", {}, "0"],
        ]}}},
        {"code": 0, "data": {symbol: {"data": {
            "date": "20261113",
            "data": ["0930 10 1 1000", "0931 10 3 3000"],
        }}}},
    ])
    monkeypatch.setattr(tencent_minutes, "request_market_json", lambda *args: next(payloads))
    raw = tencent_minutes.fetch_tencent_minutes(MagicMock(), "000012.SZ")
    bars = normalize_eastmoney_minute(raw, "000012.SZ", "2026-11-13")
    assert raw.attrs["source"] == tencent_minutes.SOURCE
    assert bars["timestamp"].dt.strftime("%H:%M").tolist() == ["09:31"]
    assert bars["volume"].tolist() == [200]
    assert bars["amount"].tolist() == [2000]
    assert bars["vwap"].tolist() == [10]


def test_completion_mail_is_sent_once_after_publication(tmp_path, monkeypatch):
    authorization = tmp_path / "authorization"
    authorization.write_text("test-authorization")
    monkeypatch.setattr(notify_minute_update, "AUTHORIZATION_PATH", authorization)
    minute_path = tmp_path / "minutes" / "2026" / "2026-11-13.parquet"
    minute_path.parent.mkdir(parents=True)
    minute_path.touch()
    minute_path.with_suffix(".source.json").write_text(json.dumps({
        "requested_codes": ["000012.SZ"],
        "present_codes": ["000012.SZ"],
        "empty_codes": [],
        "rows": 240,
        "rows_per_code": {"000012.SZ": 240},
    }))
    status_path = tmp_path / "status.json"
    status_path.write_text(json.dumps({
        "latest_date": "2026-11-13",
        "minute_root": str(tmp_path / "minutes"),
        "updated_at": "2026-11-13T17:00:00+08:00",
    }))
    smtp_factory = MagicMock()
    monkeypatch.setattr(notify_minute_update.smtplib, "SMTP_SSL", smtp_factory)
    assert notify_minute_update.notify_minute_completion(status_path) == "sent"
    assert notify_minute_update.notify_minute_completion(status_path) == "sent"
    smtp = smtp_factory.return_value.__enter__.return_value
    smtp.send_message.assert_called_once()
    message = smtp.send_message.call_args.args[0]
    assert message["To"] == "783829986@qq.com"
    assert "100.00%" in message.get_content()


def test_negative_cumulative_amount_leaves_an_explicit_minute_gap(monkeypatch):
    symbol = "sz301622"
    payloads = iter([
        {"code": 0, "data": {symbol: {"m1": [
            ["202611131129", "32.73", "32.73", "32.73", "32.73", "2", {}, "0"],
            ["202611131130", "32.73", "32.72", "32.73", "32.72", "1", {}, "0"],
        ]}}},
        {"code": 0, "data": {symbol: {"data": {
            "date": "20261113",
            "data": ["1129 32.73 200 654600", "1130 32.72 201 654565.98"],
        }}}},
    ])
    monkeypatch.setattr(tencent_minutes, "request_market_json", lambda *args: next(payloads))
    raw = tencent_minutes.fetch_tencent_minutes(MagicMock(), "301622.SZ")
    assert raw["时间"].dt.strftime("%H:%M").tolist() == ["11:29"]
    assert raw.attrs["omitted_bars"] == ["2026-11-13 11:30:00"]


def test_existing_day_retries_mail_without_market_requests(tmp_path, monkeypatch):
    minute_root = tmp_path / "minutes"
    minute_path = minute_root / "2026" / "2026-11-13.parquet"
    minute_path.parent.mkdir(parents=True)
    pd.DataFrame({"code": ["000012.SZ"]}).to_parquet(minute_path)
    minute_path.with_suffix(".source.json").write_text(json.dumps({
        "source": "akshare.stock_zh_a_hist_min_em",
        "present_codes": ["000012.SZ"],
        "empty_codes": [],
    }))
    status_path = tmp_path / "status.json"
    clock = MagicMock()
    clock.now.return_value = datetime(2026, 11, 13, 17, tzinfo=ZoneInfo("Asia/Shanghai"))
    monkeypatch.setattr(update_daily_minutes, "datetime", clock)
    market_session = MagicMock(side_effect=AssertionError("已发布行情无需重新访问数据源"))
    monkeypatch.setattr(update_daily_minutes, "create_session", market_session)
    monkeypatch.setattr(update_daily_minutes, "notify_minute_completion", lambda path: "sent")
    monkeypatch.setattr("sys.argv", [
        "update_daily_minutes", "--minute-root", str(minute_root),
        "--snapshot-root", str(tmp_path / "snapshots"),
        "--status-path", str(status_path),
    ])
    update_daily_minutes.main()
    assert json.loads(status_path.read_text())["mail_status"] == "sent"
    market_session.assert_not_called()


def test_v4_incremental_download_preserves_source_and_gap_metadata(tmp_path):
    from src.intraday.free_minute import FreeMinuteDailyUpdater

    calls = []

    def fetcher(code, day):
        calls.append(code)
        raw = pd.DataFrame({
            "时间": ["2025-01-02 13:21:00"],
            "开盘": [10], "收盘": [10], "最高": [10], "最低": [10],
            "成交量": [2], "成交额": [2000],
        })
        raw.attrs["source"] = "tencent.mkline+minute.query"
        raw.attrs["omitted_bars"] = ["2025-01-02 11:30:00"]
        return raw

    updater = FreeMinuteDailyUpdater(tmp_path, fetcher, delay_seconds=0, min_coverage=1)
    updater.update_day("2025-01-02", ["000012.SZ"])
    summary = updater.update_day("2025-01-02", ["000012.SZ", "000028.SZ"])
    manifest = json.loads(Path(summary.path).with_suffix(".source.json").read_text())
    assert calls == ["000012.SZ", "000028.SZ"]
    assert summary.received_codes == 2
    assert manifest["sources_by_code"] == {
        "000012.SZ": "tencent.mkline+minute.query",
        "000028.SZ": "tencent.mkline+minute.query",
    }
    assert manifest["omitted_bars_by_code"]["000012.SZ"] == ["2025-01-02 11:30:00"]
