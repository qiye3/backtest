"""按需读取分钟归档或标准 Parquet，并构造回测使用的行情表。"""

from __future__ import annotations

import io
import json
import os
import re
import tempfile
import zipfile
from collections.abc import Iterable, Iterator, Callable
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

import numpy as np
import pandas as pd

from src.intraday.targets import normalize_stock_code

MINUTE_COLUMNS = ["open", "high", "low", "close", "amount", "volume"]
TIMEZONE = "Asia/Shanghai"
CACHE_FORMAT_VERSION = 3
DATA_CORRECTIONS = json.loads(
    Path(__file__).with_name("data_corrections.json").read_text(encoding="utf-8")
)
CORRECTIONS_VERSION = int(DATA_CORRECTIONS["version"])
HUNDREDFOLD_UNIT_DATES = set(DATA_CORRECTIONS["hundredfold_unit_dates"])


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
    """从每日压缩包或 Parquet 读取指定股票，并按股票池缓存。"""

    def __init__(self, minute_root: Path, cache_root: Path, universe_name: str) -> None:
        self.minute_root = Path(minute_root)
        self.cache_root = Path(cache_root) / "minute" / universe_name
        self.issues: list[DataQualityIssue] = []
        self._archives = self._index_archives()

    def available_dates(self) -> list[pd.Timestamp]:
        """返回当前归档中可识别的交易日。"""
        return sorted(pd.Timestamp(date) for date in self._archives)

    def dates_in_range(self, start_date: object, end_date: object) -> list[pd.Timestamp]:
        """返回闭区间内真实存在的归档日期。"""
        start = pd.Timestamp(start_date).normalize()
        end = pd.Timestamp(end_date).normalize()
        dates = [date for date in self.available_dates() if start <= date <= end]
        if not dates:
            raise ValueError(f"{start.date()} 至 {end.date()} 没有分钟归档")
        return dates

    def latest_available_date(self) -> pd.Timestamp:
        """返回数据截止日。"""
        dates = self.available_dates()
        if not dates:
            raise ValueError(f"分钟归档目录为空: {self.minute_root}")
        return dates[-1]

    def read_day(self, trading_date: object, codes: Iterable[str]) -> pd.DataFrame:
        """读取一个交易日的股票子集，并安全复用完整缓存。"""
        date = pd.Timestamp(trading_date).normalize()
        normalized_codes = sorted({normalize_stock_code(code) for code in codes})
        archive_path = self._archives.get(date.strftime("%Y%m%d"))
        if archive_path is None:
            raise FileNotFoundError(f"找不到 {date:%Y-%m-%d} 的分钟归档")

        cache_path = self.cache_root / f"{date.year}" / f"{date:%Y-%m-%d}.parquet"
        metadata_path = cache_path.with_suffix(".json")
        source_identity = _source_identity(archive_path)
        cache_path.parent.mkdir(parents=True, exist_ok=True)

        with _exclusive_cache_lock(cache_path.with_suffix(".lock")):
            cached = self._read_complete_cache(
                cache_path,
                metadata_path,
                normalized_codes,
                source_identity,
            )
            if cached is not None:
                return cached

            frames = self._read_archive(archive_path, date, normalized_codes)
            if not frames:
                return _empty_minute_frame()
            result = pd.concat(frames, ignore_index=True).sort_values(
                ["timestamp", "code"],
                kind="stable",
            )
            metadata = {
                "format_version": CACHE_FORMAT_VERSION,
                "corrections_version": CORRECTIONS_VERSION,
                "codes": normalized_codes,
                "source": source_identity,
            }
            _write_parquet_atomic(result, cache_path)
            _write_json_atomic(metadata, metadata_path)
        return result.reset_index(drop=True)

    def iter_days(
        self,
        start_date: object,
        end_date: object,
        codes: Iterable[str] | Callable[[pd.Timestamp], Iterable[str]],
    ) -> Iterator[pd.DataFrame]:
        """逐日读取。codes 可以是按日期返回历史成份和在途持仓的函数。"""
        static_codes = None if callable(codes) else sorted({normalize_stock_code(code) for code in codes})
        for trading_date in self.dates_in_range(start_date, end_date):
            daily_codes = codes(trading_date) if callable(codes) else static_codes
            bars = self.read_day(trading_date, daily_codes)
            if not bars.empty:
                yield bars

    def read_range(
        self,
        start_date: object,
        end_date: object,
        codes: Iterable[str],
    ) -> pd.DataFrame:
        """兼容旧调用；大区间生产运行应使用 :meth:`iter_days`。"""
        frames = list(self.iter_days(start_date, end_date, codes))
        if not frames:
            return _empty_minute_frame()
        return pd.concat(frames, ignore_index=True).sort_values(
            ["timestamp", "code"],
            kind="stable",
        ).reset_index(drop=True)

    def source_snapshot(self, start_date: object, end_date: object) -> dict[str, Any]:
        """返回运行清单使用的轻量数据快照，不扫描压缩包内容。"""
        dates = self.dates_in_range(start_date, end_date)
        archive_paths = [self._archives[date.strftime("%Y%m%d")] for date in dates]
        total_size = sum(path.stat().st_size for path in archive_paths)
        return {
            "minute_root": str(self.minute_root.resolve()),
            "first_date": str(dates[0].date()),
            "last_date": str(dates[-1].date()),
            "archive_count": len(archive_paths),
            "archive_bytes": total_size,
        }

    def _index_archives(self) -> dict[str, Path]:
        archives: dict[str, Path] = {}
        for path in sorted(self.minute_root.rglob("*")):
            supported_suffixes = {".zip", ".7z", ".parquet"}
            if not path.is_file() or path.suffix.lower() not in supported_suffixes:
                continue
            trading_date = _date_from_archive_name(path)
            if trading_date is None:
                continue
            previous_path = archives.get(trading_date)
            if previous_path is not None:
                raise ValueError(
                    f"分钟数据日期重复: {trading_date}: {previous_path} 与 {path}"
                )
            archives[trading_date] = path
        return archives

    def _read_complete_cache(
        self,
        cache_path: Path,
        metadata_path: Path,
        requested_codes: list[str],
        source_identity: dict[str, Any],
    ) -> pd.DataFrame | None:
        if not cache_path.is_file() or not metadata_path.is_file():
            return None
        try:
            metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        if metadata.get("format_version") != CACHE_FORMAT_VERSION:
            return None
        if metadata.get("corrections_version") != CORRECTIONS_VERSION:
            return None
        if metadata.get("codes") != requested_codes:
            return None
        if metadata.get("source") != source_identity:
            return None
        try:
            return pd.read_parquet(cache_path)
        except (OSError, ValueError):
            return None

    def _read_archive(
        self,
        archive_path: Path,
        trading_date: pd.Timestamp,
        codes: list[str],
    ) -> list[pd.DataFrame]:
        if archive_path.suffix.lower() == ".parquet":
            return self._read_parquet(archive_path, trading_date, codes)
        if archive_path.suffix.lower() == ".zip":
            with zipfile.ZipFile(archive_path) as archive:
                members, duplicate_codes = _member_lookup(archive.namelist())
                self._record_duplicate_members(trading_date, duplicate_codes, codes)
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

    # 从标准 Parquet 过滤请求股票，并保留与压缩包读取一致的问题记录。
    def _read_parquet(
        self,
        parquet_path: Path,
        trading_date: pd.Timestamp,
        codes: list[str],
    ) -> list[pd.DataFrame]:
        """读取标准分钟 Parquet，并记录请求股票的缺失情况。

        输入：
        - ``parquet_path``：单个交易日的全市场分钟 Parquet。
        - ``trading_date``：该文件对应的交易日。
        - ``codes``：本次回测需要的标准股票代码。

        输出：
        - 有记录时返回单元素 DataFrame 列表；全为空时返回空列表。

        功能和用途：
        - 使用 Parquet 过滤下推只读取股票池，并统一时间戳时区。
        - 缺失股票沿用压缩包读取器的问题记录格式。
        """
        columns = ["timestamp", "code", *MINUTE_COLUMNS, "vwap"]
        frame = pd.read_parquet(
            parquet_path,
            columns=columns,
            filters=[("code", "in", codes)],
        )
        present_codes = set(frame["code"].astype(str))
        for code in sorted(set(codes) - present_codes):
            self._missing_member(trading_date, code)
        if frame.empty:
            return []
        frame["timestamp"] = pd.to_datetime(frame["timestamp"], errors="raise")
        if frame["timestamp"].dt.tz is None:
            frame["timestamp"] = frame["timestamp"].dt.tz_localize(TIMEZONE)
        return [frame]

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
            members, duplicate_codes = _member_lookup(archive.getnames())
            self._record_duplicate_members(trading_date, duplicate_codes, codes)
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

    def _record_duplicate_members(
        self,
        trading_date: pd.Timestamp,
        duplicate_codes: set[str],
        requested_codes: list[str],
    ) -> None:
        for code in sorted(duplicate_codes & set(requested_codes)):
            self.issues.append(
                DataQualityIssue(
                    str(trading_date.date()),
                    code,
                    "归档内存在重复代码成员，已使用首份文件",
                )
            )

    def _read_member(
        self,
        content: bytes,
        trading_date: pd.Timestamp,
        code: str,
    ) -> pd.DataFrame | None:
        frame = pd.read_csv(io.BytesIO(content))
        if not _has_supported_minute_columns(frame.columns):
            self.issues.append(
                DataQualityIssue(str(trading_date.date()), code, "分钟字段不符合预期")
            )
            return None
        frame = frame.loc[:, MINUTE_COLUMNS].copy()
        if len(frame) != 240:
            self.issues.append(
                DataQualityIssue(
                    str(trading_date.date()),
                    code,
                    f"bar 数为 {len(frame)}，预期 240",
                )
            )
            return None
        for column in MINUTE_COLUMNS:
            frame[column] = pd.to_numeric(frame[column], errors="coerce")
        if frame[MINUTE_COLUMNS].isna().any().any():
            self.issues.append(
                DataQualityIssue(
                    str(trading_date.date()),
                    code,
                    "分钟字段包含非数值或空值",
                )
            )
            return None
        if trading_date.strftime("%Y%m%d") in HUNDREDFOLD_UNIT_DATES:
            frame["amount"] *= 100
            frame["volume"] *= 100
        frame.insert(0, "code", code)
        frame.insert(0, "timestamp", minute_bar_end_times(trading_date))
        frame["vwap"] = np.where(
            frame["volume"] > 0,
            frame["amount"] / frame["volume"],
            frame["close"],
        )
        return frame

    def _missing_member(self, trading_date: pd.Timestamp, code: str) -> None:
        self.issues.append(
            DataQualityIssue(str(trading_date.date()), code, "归档内无该股票")
        )


def load_daily_trade_status(
    path: Path | None,
    codes: Iterable[str],
    start_date: object,
    end_date: object,
) -> pd.DataFrame:
    """读取可选的 PIT 每日交易状态和精确涨跌停价。"""
    columns = ["date", "code", "is_st", "is_suspended", "limit_up", "limit_down"]
    if path is None:
        return pd.DataFrame(columns=columns)
    if path.suffix.lower() == ".parquet":
        status = pd.read_parquet(path)
    elif path.suffix.lower() == ".csv":
        status = pd.read_csv(path, dtype={"code": "string"})
    else:
        raise ValueError("每日交易状态只支持 CSV 或 Parquet")
    missing = set(columns) - set(status)
    if missing:
        raise ValueError(f"每日交易状态缺少字段: {sorted(missing)}")
    status = status.loc[:, columns].copy()
    status["date"] = pd.to_datetime(status["date"], errors="raise").dt.normalize()
    status["code"] = status["code"].map(normalize_stock_code)
    status["is_st"] = _boolean_status_column(status["is_st"], "is_st")
    status["is_suspended"] = _boolean_status_column(
        status["is_suspended"],
        "is_suspended",
    )
    status["limit_up"] = pd.to_numeric(status["limit_up"], errors="coerce")
    status["limit_down"] = pd.to_numeric(status["limit_down"], errors="coerce")
    wanted = {normalize_stock_code(code) for code in codes}
    start = pd.Timestamp(start_date).normalize()
    end = pd.Timestamp(end_date).normalize()
    status = status[
        status["code"].isin(wanted) & status["date"].between(start, end, inclusive="both")
    ]
    if status.duplicated(["date", "code"]).any():
        raise ValueError("每日交易状态的 date 与 code 组合不能重复")
    return status.sort_values(["date", "code"], kind="stable").reset_index(drop=True)


def _boolean_status_column(values: pd.Series, name: str) -> pd.Series:
    normalized = values.astype(str).str.strip().str.lower()
    mapping = {
        "true": True,
        "false": False,
        "1": True,
        "0": False,
    }
    unknown = sorted(set(normalized) - set(mapping))
    if unknown:
        raise ValueError(f"每日交易状态 {name} 包含非法值: {unknown}")
    return normalized.map(mapping).astype(bool)


def attach_daily_trade_status(
    bars: pd.DataFrame,
    daily_status: pd.DataFrame,
) -> pd.DataFrame:
    """给单日分钟行情附加当日可交易状态。"""
    if daily_status.empty:
        return bars
    trading_date = bars["timestamp"].iloc[0].tz_localize(None).normalize()
    selected = daily_status[daily_status["date"] == trading_date].drop(columns="date")
    if selected.empty:
        return bars
    return bars.merge(selected, on="code", how="left", validate="many_to_one")


def _date_from_archive_name(path: Path) -> str | None:
    digits = "".join(character for character in path.stem if character.isdigit())
    for offset in range(max(1, len(digits) - 7)):
        candidate = digits[offset : offset + 8]
        try:
            pd.Timestamp(candidate)
        except ValueError:
            continue
        return candidate
    return None


def _source_identity(path: Path) -> dict[str, Any]:
    stat = path.stat()
    return {
        "path": str(path.resolve()),
        "size": stat.st_size,
        "mtime_ns": stat.st_mtime_ns,
    }


@contextmanager
def _exclusive_cache_lock(lock_path: Path) -> Iterator[None]:
    """同一天缓存只允许一个进程构建，避免并发写出半文件。"""
    import fcntl

    with lock_path.open("a", encoding="utf-8") as lock_file:
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)


def _write_parquet_atomic(frame: pd.DataFrame, path: Path) -> None:
    with tempfile.NamedTemporaryFile(
        prefix=f".{path.name}.",
        suffix=".tmp",
        dir=path.parent,
        delete=False,
    ) as temporary_file:
        temporary_path = Path(temporary_file.name)
    try:
        frame.to_parquet(temporary_path, index=False)
        os.replace(temporary_path, path)
    finally:
        temporary_path.unlink(missing_ok=True)


def _write_json_atomic(values: object, path: Path) -> None:
    with tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        prefix=f".{path.name}.",
        suffix=".tmp",
        dir=path.parent,
        delete=False,
    ) as temporary_file:
        json.dump(values, temporary_file, ensure_ascii=False, indent=2)
        temporary_path = Path(temporary_file.name)
    try:
        os.replace(temporary_path, path)
    finally:
        temporary_path.unlink(missing_ok=True)


def _member_lookup(member_names: Iterable[str]) -> tuple[dict[str, str], set[str]]:
    lookup: dict[str, str] = {}
    duplicate_codes: set[str] = set()
    for member_name in member_names:
        path = PurePosixPath(member_name.replace("\\", "/"))
        if path.suffix.lower() != ".csv" or len(path.parts) < 2:
            continue
        exchange = path.parts[-2].lower()
        digits = _stock_digits_from_minute_filename(path.stem)
        if exchange not in {"sh", "sz", "bj"} or digits is None:
            continue
        code = normalize_stock_code(f"{digits}.{exchange.upper()}")
        if code in lookup:
            duplicate_codes.add(code)
            continue
        lookup[code] = member_name
    return lookup, duplicate_codes


def _stock_digits_from_minute_filename(filename_stem: str) -> str | None:
    matched = re.search(r"\d{6}", filename_stem)
    if matched is None:
        return None
    return matched.group()


def _has_supported_minute_columns(columns: Iterable[object]) -> bool:
    column_names = {str(column) for column in columns}
    required_columns = set(MINUTE_COLUMNS)
    return required_columns.issubset(column_names) and column_names <= required_columns | {"time"}


def _empty_minute_frame() -> pd.DataFrame:
    return pd.DataFrame(columns=["timestamp", "code", *MINUTE_COLUMNS, "vwap"])


def load_corporate_actions(daily_root: Path, codes: Iterable[str]) -> pd.DataFrame:
    """从标准 Parquet、散装 XLSX 或 ZIP 提取除权事件和配股条款。"""
    wanted = {normalize_stock_code(code) for code in codes}
    records: list[pd.DataFrame] = []
    for path in sorted(Path(daily_root).rglob("*.parquet")):
        inferred = _code_from_filename(path)
        if inferred is None or inferred not in wanted:
            continue
        raw = pd.read_parquet(path)
        records.append(_corporate_actions_from_frame(raw, inferred))
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
    columns = [
        "date",
        "code",
        "cash_dividend_per_share",
        "share_ratio",
        "rights_ratio",
        "rights_price",
    ]
    if not records:
        return pd.DataFrame(columns=columns)
    return (
        pd.concat(records, ignore_index=True)
        .drop_duplicates(["date", "code"], keep="last")
        .sort_values(["date", "code"])
        .reset_index(drop=True)
    )


def _corporate_actions_from_excel(source: object, code: str) -> pd.DataFrame:
    raw = pd.read_excel(source)
    return _corporate_actions_from_frame(raw, code)


# 从单只股票的标准日线表构造公司行动记录。
def _corporate_actions_from_frame(raw: pd.DataFrame, code: str) -> pd.DataFrame:
    """提取单只股票的公司行动记录。

    输入：
    - ``raw``：包含日期和可选红利、送转、配股字段的日线表。
    - ``code``：带市场后缀的标准股票代码。

    输出：
    - 返回只包含实际公司行动日期和每股口径字段的 DataFrame。

    功能和用途：
    - 让 Parquet 与 Excel 日线共用同一复权校验和事件换算规则。
    """
    _validate_adjusted_prices(raw, code)
    date_column = next((name for name in ("日期", "交易日期", "date") if name in raw), None)
    if date_column is None:
        return pd.DataFrame()
    event = pd.DataFrame(
        {
            "date": pd.to_datetime(raw[date_column], errors="coerce").dt.normalize(),
            "code": code,
            "cash_dividend_per_share": _numeric_column(raw, "红利") / 10,
            "share_ratio": (_numeric_column(raw, "送股数") + _numeric_column(raw, "转增股"))
            / 10,
            "rights_ratio": _numeric_column(raw, "配股数") / 10,
            "rights_price": _numeric_column(raw, "配股价"),
        }
    )
    event = event.dropna(subset=["date"])
    has_action = (
        (event["cash_dividend_per_share"] != 0)
        | (event["share_ratio"] != 0)
        | (event["rights_ratio"] != 0)
    )
    return event[has_action]


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
    try:
        return normalize_stock_code(path.stem)
    except ValueError:
        pass
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
