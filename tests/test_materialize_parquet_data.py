"""验证原始数据到英文 Parquet 层的关键规范化规则。"""

from __future__ import annotations

import zipfile

import numpy as np
import pandas as pd
import py7zr
import pytest

from scripts.materialize_parquet_data import (
    _convert_minute_archive,
    _daily_delisted_lookup,
    _date_from_text,
    _parse_chinese_amount,
    materialize_minute_bars,
)


# 验证分钟物化结果能保留 240 根 bar、市场代码和正确 VWAP。
def test_convert_minute_archive_writes_standard_parquet(tmp_path) -> None:
    """将一个最小每日 ZIP 转换为标准分钟 Parquet。

    输入：
    - 使用临时目录构造一只股票、240 根 bar 的 ZIP。

    输出：
    - 断言输出路径、行数、字段和 VWAP 均符合回测读取合同。

    功能和用途：
    - 覆盖转换脚本与 ``MinuteArchiveReader`` 共享的核心数据格式。
    """
    close = np.linspace(10.0, 11.0, 240)
    raw = pd.DataFrame(
        {
            "open": close,
            "high": close + 0.1,
            "low": close - 0.1,
            "close": close,
            "amount": close * 1_000,
            "volume": [1_000.0] * 240,
        }
    )
    archive_path = tmp_path / "20250401.zip"
    with zipfile.ZipFile(archive_path, "w") as archive:
        archive.writestr("sh/600000.csv", raw.to_csv(index=False))
        archive.writestr("sz/300157.csv", b"")

    result = _convert_minute_archive((str(archive_path), str(tmp_path / "out"), False))
    output = pd.read_parquet(tmp_path / "out/2025/2025-04-01.parquet")

    assert result["rows"] == 240
    assert result["invalid_members"] == 1
    assert output["code"].unique().tolist() == ["600000.SH"]
    assert output["timestamp"].dt.tz is not None
    assert np.allclose(output["vwap"], output["close"])


# 验证退市目录中的空占位表不会生成无效股票任务。
def test_daily_delisted_lookup_excludes_empty_workbooks(tmp_path) -> None:
    """仅保留至少含一行数据的退市股 Excel。

    输入：
    - 构造有数据、只有表头和完全空白三类 XLSX。

    输出：
    - 断言映射只包含有数据的股票，并准确统计两个空源。

    功能和用途：
    - 防止供应商空占位表进入日线转换后触发缺失日期列错误。
    """
    pd.DataFrame({"date": ["2020-01-02"], "close": [10.0]}).to_excel(
        tmp_path / "000001_平安银行.xlsx",
        index=False,
    )
    pd.DataFrame(columns=["date", "close"]).to_excel(
        tmp_path / "000002_万科A.xlsx",
        index=False,
    )
    pd.DataFrame().to_excel(tmp_path / "000003_空占位.xlsx", index=False)

    delisted_paths, empty_source_count = _daily_delisted_lookup(tmp_path)

    assert sorted(delisted_paths) == ["000001.SZ"]
    assert empty_source_count == 2


# 验证中文资金单位统一换算为元，并保留负号。
def test_parse_chinese_amount_converts_units() -> None:
    """检查资金流中文数量级解析。

    输入：
    - 提供亿、万、普通数字和空占位符四类值。

    输出：
    - 断言数值统一为元，空占位符转换为 ``NaN``。

    功能和用途：
    - 防止资金流物化后仍混用字符串数量级。
    """
    assert _parse_chinese_amount("7.68亿") == 768_000_000.0
    assert _parse_chinese_amount("-9990万") == -99_900_000.0
    assert _parse_chinese_amount("123") == 123.0
    assert np.isnan(_parse_chinese_amount("--"))
    assert np.isnan(_parse_chinese_amount("—"))


# 验证数据文件名中的连续和连字符日期都能归一为八位日期。
def test_date_from_text_supports_source_filename_formats() -> None:
    """检查现场存在的两种日期命名格式。

    输入：
    - 提供分钟包连续日期和财报快照连字符日期。

    输出：
    - 断言两者均返回统一的 YYYYMMDD 字符串。

    功能和用途：
    - 保证四类原始数据可以共用日期解析器。
    """
    assert _date_from_text("20260828.zip") == "20260828"
    assert _date_from_text("2026-08-28_financial.parquet") == "20260828"


@pytest.mark.parametrize("suffix", [".7z", ".zip"])
def test_minute_import_detects_seven_zip_container(tmp_path, suffix) -> None:
    """原始7z及错标为zip的7z均可由物化入口发现并读取。"""
    raw = pd.DataFrame({
        "open": [10.0] * 240,
        "high": [10.1] * 240,
        "low": [9.9] * 240,
        "close": [10.0] * 240,
        "amount": [10_000.0] * 240,
        "volume": [1000] * 240,
    })
    csv_path = tmp_path / "600000.csv"
    raw.to_csv(csv_path, index=False)
    source_root = tmp_path / "raw"
    source_root.mkdir()
    archive_path = source_root / f"20261015{suffix}"
    with py7zr.SevenZipFile(archive_path, "w") as archive:
        archive.write(csv_path, "20261015/sh/600000.csv")
    result = materialize_minute_bars(source_root, tmp_path / "out", workers=1, overwrite=False)
    output = pd.read_parquet(tmp_path / "out/2026/2026-10-15.parquet")
    assert result["files"] == 1
    assert len(output) == 240
    assert output["code"].unique().tolist() == ["600000.SH"]
    assert output["vwap"].eq(10).all()
