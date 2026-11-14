"""验证 zxy 每日压缩包和分钟时间重建。"""

from __future__ import annotations

import io
import zipfile

import numpy as np
import pandas as pd
import pytest

from src.intraday.data import (
    MinuteArchiveReader,
    load_corporate_actions,
    minute_bar_end_times,
)


def _minute_csv(
    include_time: bool = False,
    reverse_amount_and_volume: bool = False,
    unit_scale: float = 1.0,
    close_level: float = 10.0,
) -> bytes:
    close = np.linspace(close_level, close_level + 1, 240)
    frame = pd.DataFrame(
        {
            "open": close,
            "high": close + 0.01,
            "low": close - 0.01,
            "close": close,
            "amount": close * 1_000 / unit_scale,
            "volume": 1_000 / unit_scale,
        }
    )
    if include_time:
        frame.insert(0, "time", minute_bar_end_times("2025-04-01").strftime("%H:%M"))
    if reverse_amount_and_volume:
        leading_columns = ["time"] if include_time else []
        frame = frame.loc[:, [*leading_columns, "open", "high", "low", "close", "volume", "amount"]]
    buffer = io.StringIO()
    frame.to_csv(buffer, index=False)
    return buffer.getvalue().encode()


def test_minute_bar_end_times_have_lunch_break() -> None:
    times = minute_bar_end_times("2025-04-01")

    assert len(times) == 240
    assert times[0].strftime("%H:%M") == "09:31"
    assert times[119].strftime("%H:%M") == "11:30"
    assert times[120].strftime("%H:%M") == "13:01"
    assert times[-1].strftime("%H:%M") == "15:00"


def test_zip_reader_supports_nested_and_flat_member_paths(tmp_path) -> None:
    archive_path = tmp_path / "stock_20250401.zip"
    with zipfile.ZipFile(archive_path, "w") as archive:
        archive.writestr("sh/600000.csv", _minute_csv())
        archive.writestr("20250401/sz/sz000001.csv", _minute_csv())
    reader = MinuteArchiveReader(tmp_path, tmp_path / "cache", "two_stocks")

    result = reader.read_day("2025-04-01", ["600000.SH", "000001.SZ"])

    assert len(result) == 480
    assert set(result["code"]) == {"600000.SH", "000001.SZ"}
    assert result["timestamp"].dt.tz is not None
    assert np.allclose(result["vwap"], result["close"])
    assert reader.read_day("2025-04-01", ["600000.SH", "000001.SZ"]).equals(result)


def test_reader_accepts_time_column_and_market_suffix_filename(tmp_path) -> None:
    archive_path = tmp_path / "stock_20170804.zip"
    with zipfile.ZipFile(archive_path, "w") as archive:
        archive.writestr("20170804/sz/000001.sz.csv", _minute_csv(include_time=True))
    reader = MinuteArchiveReader(tmp_path, tmp_path / "cache", "time_column")

    result = reader.read_day("2017-08-04", ["000001.SZ"])

    assert len(result) == 240
    assert list(result.columns) == [
        "timestamp",
        "code",
        "open",
        "high",
        "low",
        "close",
        "amount",
        "volume",
        "vwap",
    ]
    assert result["volume"].iloc[0] == 1_000


def test_reader_restores_special_three_day_volume_and_amount_units(tmp_path) -> None:
    archive_path = tmp_path / "stock_20251201.zip"
    with zipfile.ZipFile(archive_path, "w") as archive:
        archive.writestr(
            "20251201/sh/600000.sh.csv",
            _minute_csv(include_time=True, reverse_amount_and_volume=True, unit_scale=100),
        )
    reader = MinuteArchiveReader(tmp_path, tmp_path / "cache", "unit_scale")

    result = reader.read_day("2025-12-01", ["600000.SH"])

    assert result["volume"].iloc[0] == 1_000
    assert result["amount"].iloc[0] == 10_000
    assert result["vwap"].iloc[0] == 10


def test_reader_records_duplicate_member_and_uses_first_file(tmp_path) -> None:
    archive_path = tmp_path / "stock_20260617.zip"
    with zipfile.ZipFile(archive_path, "w") as archive:
        archive.writestr("20260617/sh/600000.csv", _minute_csv(close_level=10))
        archive.writestr("20260617/sh/sh600000.csv", _minute_csv(close_level=20))
    reader = MinuteArchiveReader(tmp_path, tmp_path / "cache", "duplicate_member")

    result = reader.read_day("2026-06-17", ["600000.SH"])

    assert result["close"].iloc[0] == 10
    assert reader.issues[0].reason == "归档内存在重复代码成员，已使用首份文件"


def test_reader_loads_standard_daily_parquet(tmp_path) -> None:
    bars = pd.DataFrame(
        {
            "timestamp": minute_bar_end_times("2025-04-01"),
            "code": ["600000.SH"] * 240,
            "open": [10.0] * 240,
            "high": [10.1] * 240,
            "low": [9.9] * 240,
            "close": [10.0] * 240,
            "amount": [10_000.0] * 240,
            "volume": [1_000.0] * 240,
            "vwap": [10.0] * 240,
        }
    )
    minute_root = tmp_path / "minute_bars/2025"
    minute_root.mkdir(parents=True)
    bars.to_parquet(minute_root / "2025-04-01.parquet", index=False)
    reader = MinuteArchiveReader(tmp_path / "minute_bars", tmp_path / "cache", "parquet")

    result = reader.read_day("2025-04-01", ["600000.SH"])

    assert len(result) == 240
    assert result["timestamp"].dt.tz is not None
    assert result["close"].iloc[-1] == 10.0


def test_corporate_actions_read_selected_xlsx_inside_zip(tmp_path) -> None:
    pytest.importorskip("openpyxl")
    excel_buffer = io.BytesIO()
    pd.DataFrame(
        {
            "日期": ["2025-06-01"],
            "红利": [2.0],
            "送股数": [1.0],
            "转增股": [2.0],
            "close": [10.0],
            "复权因子": [1.3],
            "扣减值": [0.2],
            "后复权价": [13.2],
        }
    ).to_excel(excel_buffer, index=False)
    with zipfile.ZipFile(tmp_path / "daily.zip", "w") as archive:
        archive.writestr("daily/600000.xlsx", excel_buffer.getvalue())

    result = load_corporate_actions(tmp_path, ["600000.SH"])

    assert result.loc[0, "cash_dividend_per_share"] == 0.2
    assert result.loc[0, "share_ratio"] == 0.3


def test_corporate_actions_read_standard_symbol_parquet(tmp_path) -> None:
    pd.DataFrame(
        {
            "date": ["2025-06-01"],
            "code": ["600000.SH"],
            "close": [10.0],
            "复权因子": [1.3],
            "扣减值": [0.2],
            "后复权价": [13.2],
            "红利": [2.0],
            "送股数": [1.0],
            "转增股": [2.0],
            "配股数": [0.0],
            "配股价": [0.0],
        }
    ).to_parquet(tmp_path / "600000.SH.parquet", index=False)

    result = load_corporate_actions(tmp_path, ["600000.SH"])

    assert result.loc[0, "cash_dividend_per_share"] == 0.2
    assert result.loc[0, "share_ratio"] == 0.3
