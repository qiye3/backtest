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
    return normalize_target_weights(target_weights, date_only_signal_time)


def normalize_target_weights(
    target_weights: pd.DataFrame,
    date_only_signal_time: str,
) -> pd.DataFrame:
    """把外部文件或策略输出统一为完整目标仓位合同。"""
    missing_columns = set(TARGET_COLUMNS) - set(target_weights.columns)
    if missing_columns:
        raise ValueError(f"目标仓位缺少字段: {sorted(missing_columns)}")
    normalized = target_weights.loc[:, TARGET_COLUMNS].copy()
    normalized["signal_timestamp"] = _signal_timestamps(
        normalized["signal_timestamp"],
        date_only_signal_time,
    )
    normalized["code"] = normalized["code"].map(normalize_stock_code)
    non_stock_codes = sorted(
        code for code in normalized["code"].unique() if not is_a_share_stock_code(code)
    )
    if non_stock_codes:
        raise ValueError(f"分钟回测只支持 A 股普通股，收到: {non_stock_codes}")
    normalized["target_weight"] = pd.to_numeric(
        normalized["target_weight"],
        errors="raise",
    )
    if normalized[TARGET_COLUMNS].isna().any().any():
        raise ValueError("目标仓位包含空值")
    if normalized.duplicated(["signal_timestamp", "code"]).any():
        raise ValueError("目标仓位的 signal_timestamp 与 code 组合不能重复")
    if (normalized["target_weight"] < 0).any():
        raise ValueError("目标权重不能为负")
    weight_sums = normalized.groupby("signal_timestamp")["target_weight"].sum()
    if (weight_sums > 1 + 1e-10).any():
        first_invalid = weight_sums[weight_sums > 1 + 1e-10].index[0]
        raise ValueError(f"{first_invalid} 的目标权重和超过 1")
    return normalized.sort_values(
        ["signal_timestamp", "code"],
        kind="stable",
    ).reset_index(drop=True)


def load_universe_codes(path: str | Path) -> list[str]:
    """读取分钟日频策略使用的固定研究股票池。"""
    universe_path = Path(path)
    if universe_path.suffix.lower() == ".parquet":
        universe = pd.read_parquet(universe_path, columns=["code"])
    elif universe_path.suffix.lower() == ".csv":
        universe = pd.read_csv(universe_path, usecols=["code"], dtype={"code": "string"})
    else:
        raise ValueError("策略股票池只支持 CSV 或 Parquet")
    codes = sorted({normalize_stock_code(code) for code in universe["code"]})
    non_stock_codes = [code for code in codes if not is_a_share_stock_code(code)]
    if non_stock_codes:
        raise ValueError(f"策略股票池只支持 A 股普通股，收到: {non_stock_codes}")
    if not codes:
        raise ValueError("策略股票池不能为空")
    return codes


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


def is_a_share_stock_code(code: str) -> bool:
    """判断代码是否属于当前支持的沪深北 A 股普通股。"""
    digits, exchange = normalize_stock_code(code).split(".")
    if exchange == "SH":
        return digits.startswith(("600", "601", "603", "605", "688", "689"))
    if exchange == "SZ":
        return digits.startswith(("000", "001", "002", "003", "300", "301"))
    return digits.startswith(("4", "8", "9")) and not digits.startswith("899")


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
