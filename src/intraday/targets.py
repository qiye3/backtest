"""读取统一的时间戳、股票代码和目标权重合同。"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

TARGET_COLUMNS = ["signal_timestamp", "code", "target_weight"]
TIMEZONE = "Asia/Shanghai"


def load_target_weights(
    path: str | Path,
    date_only_signal_time: str,
) -> pd.DataFrame:
    """读取长表目标仓位，并校验多头、无杠杆账户约束。"""
    target_path = Path(path)
    if target_path.suffix.lower() == ".parquet":
        target_weights = pd.read_parquet(target_path)
    elif target_path.suffix.lower() == ".csv":
        target_weights = pd.read_csv(target_path, dtype={"code": "string"})
    else:
        raise ValueError("目标仓位文件只支持 CSV 或 Parquet")

    missing_columns = set(TARGET_COLUMNS) - set(target_weights.columns)
    if missing_columns:
        raise ValueError(f"目标仓位缺少字段: {sorted(missing_columns)}")
    target_weights = target_weights.loc[:, TARGET_COLUMNS].copy()
    target_weights["signal_timestamp"] = _signal_timestamps(
        target_weights["signal_timestamp"],
        date_only_signal_time,
    )
    target_weights["code"] = target_weights["code"].map(normalize_stock_code)
    target_weights["target_weight"] = pd.to_numeric(
        target_weights["target_weight"],
        errors="raise",
    )
    if target_weights[TARGET_COLUMNS].isna().any().any():
        raise ValueError("目标仓位包含空值")
    if target_weights.duplicated(["signal_timestamp", "code"]).any():
        raise ValueError("目标仓位的 signal_timestamp 与 code 组合不能重复")
    if (target_weights["target_weight"] < 0).any():
        raise ValueError("首版目标权重不能为负")
    weight_sums = target_weights.groupby("signal_timestamp")["target_weight"].sum()
    if (weight_sums > 1 + 1e-10).any():
        first_invalid = weight_sums[weight_sums > 1 + 1e-10].index[0]
        raise ValueError(f"{first_invalid} 的目标权重和超过 1")
    return target_weights.sort_values(
        ["signal_timestamp", "code"],
        kind="stable",
    ).reset_index(drop=True)


def normalize_stock_code(value: object) -> str:
    """把六位代码或常见带市场代码统一为 ``000001.SZ`` 形式。"""
    text = str(value).strip().upper()
    if text.endswith((".SH", ".SZ", ".BJ")) and len(text) == 9:
        digits, exchange = text.split(".")
    elif text.startswith(("SH", "SZ", "BJ")) and len(text) == 8:
        exchange = text[:2]
        digits = text[2:]
    elif text.isdigit() and len(text) == 6:
        digits = text
        exchange = _infer_exchange(digits)
    else:
        raise ValueError(f"无法识别股票代码: {value!r}")
    if not digits.isdigit() or len(digits) != 6:
        raise ValueError(f"股票代码必须包含六位数字: {value!r}")
    return f"{digits}.{exchange}"


def code_to_archive_parts(code: str) -> tuple[str, str]:
    """返回分钟归档使用的小写交易所目录和六位代码。"""
    normalized = normalize_stock_code(code)
    digits, exchange = normalized.split(".")
    return exchange.lower(), digits


def _signal_timestamps(values: pd.Series, date_only_signal_time: str) -> pd.Series:
    raw_text = values.astype(str).str.strip()
    date_only = raw_text.str.fullmatch(r"\d{4}-\d{2}-\d{2}")
    timestamps = pd.to_datetime(raw_text, errors="raise")
    if date_only.any():
        time_offset = pd.Timestamp(f"2000-01-01 {date_only_signal_time}") - pd.Timestamp(
            "2000-01-01"
        )
        timestamps.loc[date_only] = timestamps.loc[date_only].dt.normalize() + time_offset
    if timestamps.dt.tz is None:
        return timestamps.dt.tz_localize(TIMEZONE)
    return timestamps.dt.tz_convert(TIMEZONE)


def _infer_exchange(digits: str) -> str:
    if digits.startswith("6"):
        return "SH"
    if digits.startswith(("0", "3")):
        return "SZ"
    if digits.startswith(("4", "8", "9")):
        return "BJ"
    raise ValueError(f"无法根据代码推断交易所: {digits}")
