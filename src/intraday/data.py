"""按需读取 zxy 分钟归档，并构造回测使用的标准行情表。"""

from __future__ import annotations

import io
import json
import tempfile
import zipfile
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

import numpy as np
import pandas as pd

from src.intraday.targets import normalize_stock_code

MINUTE_COLUMNS = ["open", "high", "low", "close", "amount", "volume"]
TIMEZONE = "Asia/Shanghai"


def minute_bar_end_times(trading_date: object) -> pd.DatetimeIndex:
    """返回 A 股连续竞价 240 根分钟 bar 的结束时间。"""
    date = pd.Timestamp(trading_date).normalize()
    morning = pd.date_range(
        date + pd.Timedelta(hours=9, minutes=31),
        periods=120,
        freq="min",
    )
    afternoon = pd.date_range(
        date + pd.Timedelta(hours=13, minutes=1),
        periods=120,
        freq="min",
    )
    return morning.append(afternoon).tz_localize(TIMEZONE)


@dataclass(frozen=True)
class DataQualityIssue:
    """记录不阻断整次运行的单文件数据问题。"""

    trading_date: str
    code: str
    reason: str


class MinuteArchiveReader:
    """从每日压缩包读取指定股票，并按股票池按日缓存 Parquet。"""

    def __init__(self, minute_root: Path, cache_root: Path, universe_name: str) -> None:
        self.minute_root = Path(minute_root)
        self.cache_root = Path(cache_root) / "minute" / universe_name
        self.issues: list[DataQualityIssue] = []
        self._archives = self._index_archives()

    def available_dates(self) -> list[pd.Timestamp]:
        """返回当前归档中可识别的交易日。"""
        return sorted(pd.Timestamp(date) for date in self._archives)

    def read_day(self, trading_date: object, codes: Iterable[str]) -> pd.DataFrame:
        """读取一个交易日的股票子集；缓存严格绑定配置中的 universe_name。"""
        date = pd.Timestamp(trading_date).normalize()
        normalized_codes = sorted({normalize_stock_code(code) for code in codes})
        cache_path = self.cache_root / f"{date.year}" / f"{date:%Y-%m-%d}.parquet"
        metadata_path = cache_path.with_suffix(".json")
        cached = self._read_complete_cache(cache_path, metadata_path, normalized_codes)
        if cached is not None:
            return cached

        archive_path = self._archives.get(date.strftime("%Y%m%d"))
        if archive_path is None:
            raise FileNotFoundError(f"找不到 {date:%Y-%m-%d} 的分钟归档")
        frames = self._read_archive(archive_path, date, normalized_codes)
        if not frames:
            return _empty_minute_frame()
        result = pd.concat(frames, ignore_index=True).sort_values(
            ["timestamp", "code"], kind="stable"
        )
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        result.to_parquet(cache_path, index=False)
        metadata_path.write_text(
            json.dumps({"codes": normalized_codes}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return result.reset_index(drop=True)

    def read_range(
        self,
        start_date: object,
        end_date: object,
        codes: Iterable[str],
    ) -> pd.DataFrame:
        """读取闭区间内已有归档交易日，不凭空补周末和停牌 bar。"""
        start = pd.Timestamp(start_date).normalize()
        end = pd.Timestamp(end_date).normalize()
        dates = [date for date in self.available_dates() if start <= date <= end]
        frames = [self.read_day(date, codes) for date in dates]
        frames = [frame for frame in frames if not frame.empty]
        if not frames:
            return _empty_minute_frame()
        return pd.concat(frames, ignore_index=True).sort_values(
            ["timestamp", "code"], kind="stable"
        ).reset_index(drop=True)

    def _index_archives(self) -> dict[str, Path]:
        archives: dict[str, Path] = {}
        for path in sorted(self.minute_root.rglob("*")):
            if not path.is_file() or path.suffix.lower() not in {".zip", ".7z"}:
                continue
            digits = "".join(character for character in path.stem if character.isdigit())
            for offset in range(max(1, len(digits) - 7)):
                candidate = digits[offset : offset + 8]
                try:
                    pd.Timestamp(candidate)
                except ValueError:
                    continue
                archives[candidate] = path
                break
        return archives

    def _read_complete_cache(
        self,
        cache_path: Path,
        metadata_path: Path,
        requested_codes: list[str],
    ) -> pd.DataFrame | None:
        if not cache_path.is_file() or not metadata_path.is_file():
            return None
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        if metadata.get("codes") != requested_codes:
            return None
        return pd.read_parquet(cache_path)

    def _read_archive(
        self,
        archive_path: Path,
        trading_date: pd.Timestamp,
        codes: list[str],
    ) -> list[pd.DataFrame]:
        if archive_path.suffix.lower() == ".zip":
            with zipfile.ZipFile(archive_path) as archive:
                members = _member_lookup(archive.namelist())
                frames: list[pd.DataFrame] = []
                for code in codes:
                    if code not in members:
                        self._missing_member(trading_date, code)
                        continue
                    frame = self._read_member(archive.read(members[code]), trading_date, code)
                    if frame is not None:
                        frames.append(frame)
                return frames
        return self._read_7z(archive_path, trading_date, codes)

    def _read_7z(
        self,
        archive_path: Path,
        trading_date: pd.Timestamp,
        codes: list[str],
    ) -> list[pd.DataFrame]:
        try:
            import py7zr
        except ImportError as error:
            raise RuntimeError("读取 7z 分钟归档需要安装 py7zr") from error
        with py7zr.SevenZipFile(archive_path, mode="r") as archive:
            members = _member_lookup(archive.getnames())
            selected = {code: members[code] for code in codes if code in members}
            frames: list[pd.DataFrame] = []
            with tempfile.TemporaryDirectory(prefix="minute-7z-") as temporary_directory:
                archive.extract(path=temporary_directory, targets=list(selected.values()))
                temporary_root = Path(temporary_directory)
                for code in codes:
                    if code not in selected:
                        self._missing_member(trading_date, code)
                        continue
                    content = (temporary_root / selected[code]).read_bytes()
                    frame = self._read_member(content, trading_date, code)
                    if frame is not None:
                        frames.append(frame)
        return frames

    def _read_member(
        self,
        content: bytes,
        trading_date: pd.Timestamp,
        code: str,
    ) -> pd.DataFrame | None:
        frame = pd.read_csv(io.BytesIO(content))
        if list(frame.columns) != MINUTE_COLUMNS:
            self.issues.append(
                DataQualityIssue(str(trading_date.date()), code, "分钟字段不符合预期")
            )
            return None
        if len(frame) != 240:
            self.issues.append(
                DataQualityIssue(str(trading_date.date()), code, f"bar 数为 {len(frame)}，预期 240")
            )
            return None
        for column in MINUTE_COLUMNS:
            frame[column] = pd.to_numeric(frame[column], errors="coerce")
        if frame[MINUTE_COLUMNS].isna().any().any():
            self.issues.append(
                DataQualityIssue(str(trading_date.date()), code, "分钟字段包含非数值或空值")
            )
            return None
        frame.insert(0, "code", code)
        frame.insert(0, "timestamp", minute_bar_end_times(trading_date))
        frame["vwap"] = np.where(
            frame["volume"] > 0,
            frame["amount"] / frame["volume"],
            frame["close"],
        )
        return frame

    def _missing_member(self, trading_date: pd.Timestamp, code: str) -> None:
        self.issues.append(DataQualityIssue(str(trading_date.date()), code, "归档内无该股票"))
        return None


def _member_lookup(member_names: Iterable[str]) -> dict[str, str]:
    lookup: dict[str, str] = {}
    for member_name in member_names:
        path = PurePosixPath(member_name.replace("\\", "/"))
        if path.suffix.lower() != ".csv" or len(path.parts) < 2:
            continue
        exchange = path.parts[-2].lower()
        digits = path.stem
        if digits.lower().startswith(exchange):
            digits = digits[len(exchange) :]
        if exchange not in {"sh", "sz", "bj"} or not digits.isdigit():
            continue
        code = normalize_stock_code(f"{digits}.{exchange.upper()}")
        lookup[code] = member_name
    return lookup


def _empty_minute_frame() -> pd.DataFrame:
    return pd.DataFrame(columns=["timestamp", "code", *MINUTE_COLUMNS, "vwap"])


def load_corporate_actions(daily_root: Path, codes: Iterable[str]) -> pd.DataFrame:
    """从散装或 ZIP 内 XLSX 提取除权事件；红利和送转字段按每十股换算。"""
    wanted = {normalize_stock_code(code) for code in codes}
    records: list[pd.DataFrame] = []
    for path in sorted(Path(daily_root).rglob("*.xlsx")):
        inferred = _code_from_filename(path)
        if inferred is None or inferred not in wanted:
            continue
        records.append(_corporate_actions_from_excel(path, inferred))
    for archive_path in sorted(Path(daily_root).rglob("*.zip")):
        with zipfile.ZipFile(archive_path) as archive:
            members = _xlsx_member_lookup(archive.namelist())
            for code in sorted(wanted & set(members)):
                content = io.BytesIO(archive.read(members[code]))
                records.append(_corporate_actions_from_excel(content, code))
    records = [record for record in records if not record.empty]
    if not records:
        return pd.DataFrame(
            columns=["date", "code", "cash_dividend_per_share", "share_ratio"]
        )
    return (
        pd.concat(records, ignore_index=True)
        .drop_duplicates(["date", "code"], keep="last")
        .sort_values(["date", "code"])
        .reset_index(drop=True)
    )


def _corporate_actions_from_excel(source: object, code: str) -> pd.DataFrame:
    raw = pd.read_excel(source)
    _validate_adjusted_prices(raw, code)
    date_column = next((name for name in ("日期", "交易日期", "date") if name in raw), None)
    if date_column is None:
        return pd.DataFrame()
    event = pd.DataFrame(
        {
            "date": pd.to_datetime(raw[date_column], errors="coerce").dt.normalize(),
            "code": code,
            "cash_dividend_per_share": _numeric_column(raw, "红利") / 10,
            "share_ratio": (
                _numeric_column(raw, "送股数") + _numeric_column(raw, "转增股")
            )
            / 10,
        }
    )
    event = event.dropna(subset=["date"])
    return event[
        (event["cash_dividend_per_share"] != 0) | (event["share_ratio"] != 0)
    ]


def _validate_adjusted_prices(frame: pd.DataFrame, code: str) -> None:
    close_column = "close" if "close" in frame else "收盘价"
    required = {close_column, "复权因子", "扣减值", "后复权价"}
    if not required.issubset(frame.columns):
        return
    values = frame.loc[:, list(required)].apply(pd.to_numeric, errors="coerce").dropna()
    if values.empty:
        return
    expected = values[close_column] * values["复权因子"] + values["扣减值"]
    consistent = np.isclose(expected, values["后复权价"], rtol=1e-6, atol=0.011)
    if not consistent.all():
        invalid_count = int((~consistent).sum())
        raise ValueError(f"{code} 有 {invalid_count} 行后复权价不符合复权公式")


def _xlsx_member_lookup(member_names: Iterable[str]) -> dict[str, str]:
    lookup: dict[str, str] = {}
    for member_name in member_names:
        path = PurePosixPath(member_name.replace("\\", "/"))
        if path.suffix.lower() != ".xlsx":
            continue
        code = _code_from_filename(Path(path.name))
        if code is not None:
            lookup[code] = member_name
    return lookup


def _code_from_filename(path: Path) -> str | None:
    for token in path.stem.replace("-", "_").split("_"):
        if len(token) == 6 and token.isdigit():
            try:
                return normalize_stock_code(token)
            except ValueError:
                return None
    return None


def _numeric_column(frame: pd.DataFrame, name: str) -> pd.Series:
    if name not in frame:
        return pd.Series(0.0, index=frame.index)
    return pd.to_numeric(frame[name], errors="coerce").fillna(0.0)
