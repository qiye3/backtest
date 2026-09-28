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


def _minute_csv() -> bytes:
    close = np.linspace(10, 11, 240)
    frame = pd.DataFrame(
        {
            "open": close,
            "high": close + 0.01,
            "low": close - 0.01,
            "close": close,
            "amount": close * 1_000,
            "volume": 1_000,
        }
    )
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
