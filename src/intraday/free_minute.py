"""通过免费的 AKShare 东方财富接口增量补齐 A 股未复权 1 分钟行情。"""

from __future__ import annotations

import json
import os
import shutil
import tempfile
import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import datetime, time as clock_time
from zoneinfo import ZoneInfo
from pathlib import Path

import numpy as np
import pandas as pd

from src.intraday.data import _write_json_atomic, _write_parquet_atomic, minute_bar_end_times
from src.intraday.targets import normalize_stock_code

SOURCE = "akshare.stock_zh_a_hist_min_em"
BAR_COLUMNS = ["timestamp", "code", "open", "high", "low", "close", "amount", "volume", "vwap"]


def missing_execution_minutes(
    bars: pd.DataFrame,
    trading_date: object,
    required_codes: Iterable[str],
    execution_window: tuple[str, str],
) -> dict[str, int]:
    """统计关键股票在固定成交窗口缺少的分钟数；停牌标的由调用方排除。"""
    required = {normalize_stock_code(code) for code in required_codes}
    if not required:
        return {}
    start, end = execution_window
    expected = minute_bar_end_times(trading_date)
    expected = expected[(expected.strftime("%H:%M:%S") >= start)
                        & (expected.strftime("%H:%M:%S") <= end)]
    window_bars = bars.loc[bars["code"].isin(required) & bars["timestamp"].isin(expected)]
    counts = window_bars.groupby("code")["timestamp"].nunique().to_dict()
    return {
        code: len(expected) - counts.get(code, 0)
        for code in sorted(required)
        if counts.get(code, 0) < len(expected)
    }


def normalize_eastmoney_minute(
    raw: pd.DataFrame, code: str, trading_date: object,
) -> pd.DataFrame:
    """转成现有每日 Parquet schema；原始成交量的单位是手，必须乘100。"""
    code = normalize_stock_code(code)
    day = pd.Timestamp(trading_date).normalize()
    if raw.empty:
        return pd.DataFrame(columns=BAR_COLUMNS)
    required = {"时间", "开盘", "收盘", "最高", "最低", "成交量", "成交额"}
    missing = required - set(raw)
    if missing:
        raise ValueError(f"{code} 东方财富分钟数据缺少字段: {sorted(missing)}")

    ts = pd.to_datetime(raw["时间"], errors="raise")
    if ts.dt.tz is None:
        ts = ts.dt.tz_localize("Asia/Shanghai")
    else:
        ts = ts.dt.tz_convert("Asia/Shanghai")
    frames = pd.DataFrame({
        "timestamp": ts,
        "code": code,
        "open": pd.to_numeric(raw["开盘"], errors="coerce"),
        "high": pd.to_numeric(raw["最高"], errors="coerce"),
        "low": pd.to_numeric(raw["最低"], errors="coerce"),
        "close": pd.to_numeric(raw["收盘"], errors="coerce"),
        "volume": pd.to_numeric(raw["成交量"], errors="coerce") * 100.0,
        "amount": pd.to_numeric(raw["成交额"], errors="coerce"),
    })
    expected = minute_bar_end_times(day)
    frames = frames[frames["timestamp"].isin(expected)].copy()
    if frames.empty:
        return pd.DataFrame(columns=BAR_COLUMNS)
    frames = frames.sort_values("timestamp").reset_index(drop=True)
    if frames["timestamp"].duplicated().any():
        raise ValueError(f"{code} {day.date()} 有重复分钟K线")

    price_cols = ["high", "low", "close"]
    valid_prices = (frames[price_cols].gt(0).all(axis=1)
                    & np.isfinite(frames[price_cols].to_numpy()).all(axis=1))
    valid_volume = (frames["volume"].ge(0) & np.isfinite(frames["volume"]))
    valid_amount = (frames["amount"].ge(0) & np.isfinite(frames["amount"]))
    if not (valid_prices & valid_volume & valid_amount).all():
        raise ValueError(f"{code} {day.date()} 含无效价格或成交量/额")
    if (frames["high"] < frames["low"]).any() or (
        (frames["close"] > frames["high"] + 1e-6)
        | (frames["close"] < frames["low"] - 1e-6)
    ).any():
        raise ValueError(f"{code} {day.date()} OHLC 价格关系无效")

    # 东财近5日数据可能把历史分钟开盘价置零；用上一根收盘价替代，首根用本根收盘价。
    # 替代的 open 仅用于展示和数据格式兼容，VWAP及成交撮合从不读取它。
    missing_open = frames["open"].isna() | frames["open"].le(0)
    frames.loc[missing_open, "open"] = (
        frames["close"].shift(1).fillna(frames["close"])[missing_open]
    )
    frames["vwap"] = np.where(
        frames["volume"] > 0,
        frames["amount"] / frames["volume"].replace(0, np.nan),
        frames["close"],
    )
    invalid_vwap = (~np.isfinite(frames["vwap"])) | frames["vwap"].le(0)
    if invalid_vwap.any():
        raise ValueError(f"{code} {day.date()} 有成交量但成交均价无效")
    return frames[BAR_COLUMNS].reset_index(drop=True)


def fetch_eastmoney_1min(code: str, trading_date: object) -> pd.DataFrame:
    """实时调用免费接口。1分钟数据通常只保留最近5个交易日。"""
    try:
        import akshare as ak
    except ImportError as error:
        raise RuntimeError("使用免费分钟行情需要 pip install '.[free-minute]'") from error
    day = pd.Timestamp(trading_date).strftime("%Y-%m-%d")
    return ak.stock_zh_a_hist_min_em(
        symbol=normalize_stock_code(code)[:6],
        start_date=f"{day} 09:30:00",
        end_date=f"{day} 15:00:00",
        period="1", adjust="",
    )


@dataclass(frozen=True)
class MinuteUpdateSummary:
    date: str
    path: str
    requested_codes: int
    received_codes: int
    empty_codes: tuple[str, ...]
    rows: int
    existed: bool = False


class FreeMinuteDailyUpdater:
    """逐股票缓存下载，全部完成且覆盖比例合格后才原子发布日文件。"""

    def __init__(
        self, minute_root: Path,
        fetcher: Callable[[str, object], pd.DataFrame] = fetch_eastmoney_1min,
        *, delay_seconds: float = 0.25,
        min_coverage: float = 0.97,
    ) -> None:
        if not (0 < min_coverage <= 1):
            raise ValueError("min_coverage 需要在 (0,1] 内")
        if delay_seconds < 0:
            raise ValueError("delay_seconds 不能为负")
        self.minute_root = Path(minute_root)
        self.fetcher = fetcher
        self.delay_seconds = float(delay_seconds)
        self.min_coverage = float(min_coverage)

    def update_day(
        self, trading_date: object, codes: Iterable[str], *,
        overwrite: bool = False,
        required_codes: Iterable[str] = (),
        required_window: tuple[str, str] | None = None,
        exempt_codes: Iterable[str] = (),
    ) -> MinuteUpdateSummary:
        day = pd.Timestamp(trading_date).normalize()
        now_shanghai = datetime.now(ZoneInfo("Asia/Shanghai"))
        if day.date() > now_shanghai.date() or (
            day.date() == now_shanghai.date() and now_shanghai.time() < clock_time(16, 0)
        ):
            raise ValueError("免费分钟行情必须在上海时间交易日16:00之后下载完整当日数据")
        date_text = str(day.date())
        requested = sorted({normalize_stock_code(code) for code in codes})
        if not requested:
            raise ValueError("不能下载空股票池")
        destination = self.minute_root / str(day.year) / f"{date_text}.parquet"
        manifest_path = destination.with_suffix(".source.json")
        previous_manifest = {}
        if manifest_path.exists() and not overwrite:
            previous_manifest = json.loads(manifest_path.read_text())
        sources_by_code = previous_manifest.get("sources_by_code", {}).copy()
        omitted_bars_by_code = previous_manifest.get("omitted_bars_by_code", {}).copy()
        # 旧日文件可能只覆盖部分股票。已发布文件须按真实代码集合检查，
        # 本次缺失的股票增量补进原文件，不反复下载已经存在的标的。
        existing = None
        existing_codes: set[str] = set()
        essential = {normalize_stock_code(code) for code in required_codes}
        exempt = {normalize_stock_code(code) for code in exempt_codes}
        if destination.exists() and not overwrite:
            existing = pd.read_parquet(destination)
            if required_window is not None and essential:
                # 完整比较发单窗口内的分钟时间戳，不以“有一根”冒充完整覆盖。
                incomplete = set(missing_execution_minutes(
                    existing, day, essential, required_window,
                ))
                existing = existing.loc[~existing["code"].isin(incomplete)].copy()
            existing_codes = set(existing["code"].astype(str))
            for code in existing_codes:
                sources_by_code.setdefault(code, previous_manifest.get("source", "existing_archive"))
        self.minute_root.mkdir(parents=True, exist_ok=True)
        checkpoint = self.minute_root / "_ingest_cache" / date_text
        checkpoint.mkdir(parents=True, exist_ok=True)
        parts: list[pd.DataFrame] = [existing] if existing is not None else []
        empty_codes: list[str] = []
        for code in requested:
            if code in existing_codes:
                continue
            cached = checkpoint / f"{code}.parquet"
            normalized = pd.read_parquet(cached) if cached.exists() else None
            if (normalized is not None and required_window is not None and code in essential
                    and missing_execution_minutes(normalized, day, [code], required_window)):
                normalized = None
            if normalized is None:
                # 旧缓存也可能缺少成交窗口分钟，必须重新抓取，而不是反复使用坏缓存。
                raw = self.fetcher(code, day)
                normalized = normalize_eastmoney_minute(raw, code, day)
                normalized.attrs["source"] = raw.attrs.get("source", SOURCE)
                normalized.attrs["omitted_bars"] = raw.attrs.get("omitted_bars", [])
                if not normalized.empty:
                    _write_parquet_atomic(normalized, cached)
                if self.delay_seconds:
                    time.sleep(self.delay_seconds)
            if normalized.empty:
                empty_codes.append(code)
                continue
            sources_by_code[code] = normalized.attrs.get("source", SOURCE)
            omitted_bars = normalized.attrs.get("omitted_bars", [])
            if omitted_bars:
                omitted_bars_by_code[code] = omitted_bars
            else:
                omitted_bars_by_code.pop(code, None)
            parts.append(normalized)

        present = set().union(*(set(frame["code"]) for frame in parts)) if parts else set()
        expected = set(requested) - exempt
        coverage = len(present & expected) / len(expected) if expected else 1.0
        if coverage < self.min_coverage:
            raise RuntimeError(
                f"{date_text} 免费分钟行情覆盖率 {coverage:.1%}，不足 {self.min_coverage:.0%}；"
                "保留逐股票下载缓存，但未发布日行情。可能是超出接口近5交易日范围。"
            )
        result = pd.concat(parts, ignore_index=True).sort_values(
            ["timestamp", "code"], kind="stable"
        ).reset_index(drop=True)
        if result.duplicated(["timestamp", "code"]).any():
            raise ValueError("每日分钟数据含重复 (timestamp,code)")
        missing_essential = essential - present
        if missing_essential:
            raise ValueError(f"关键股票缺少分钟行情: {sorted(missing_essential)[:10]}")
        if required_window is not None and essential:
            missing_window = missing_execution_minutes(result, day, essential, required_window)
            if missing_window:
                raise ValueError(f"关键股票成交窗口分钟数据不完整（缺失分钟数）: {dict(list(missing_window.items())[:10])}")
        destination.parent.mkdir(parents=True, exist_ok=True)
        manifest = {
            "source": " + ".join(sorted(set(sources_by_code.values()))),
            "sources_by_code": sources_by_code,
            "omitted_bars_by_code": omitted_bars_by_code,
            "date": date_text,
            "requested_codes": requested,
            "present_codes": sorted(set(result["code"])),
            "empty_codes": empty_codes,
            "exempt_codes": sorted(exempt),
            "rows": len(result),
            "timezone": "Asia/Shanghai",
            "price_adjustment": "none",
            "volume_unit": "shares",
            "amount_unit": "CNY",
            "bar_timestamp": "end",
            "min_coverage": self.min_coverage,
        }
        # 日文件最后发布：崩溃发生在此之前，读取器不会见到未完成的日数据。
        # 优先发布真实数据，再发布清单；崩溃时清单可能稍旧，但不会虚报新数据已存在。
        if existing is None or len(present - existing_codes) > 0 or overwrite:
            _write_parquet_atomic(result, destination)
        _write_json_atomic(manifest, destination.with_suffix(".source.json"))
        shutil.rmtree(checkpoint)
        return MinuteUpdateSummary(date_text, str(destination), len(requested),
                                   len(present & set(requested)), tuple(empty_codes),
                                   len(result), existed=existing is not None and not overwrite)
