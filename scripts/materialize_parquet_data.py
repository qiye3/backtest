"""把受保护的原始行情目录物化为可断点续跑的英文 Parquet 数据层。

本脚本处于原始数据与回测读取层之间，负责分钟线、日线、资金流和财报四类
数据。输入目录始终只读，输出写入独立目录；每个文件先写临时文件再原子发布。主入口
``main`` 解析命令行参数，``materialize_*`` 函数分别处理四类数据并生成清单。
"""

from __future__ import annotations

import argparse
import io
import json
import os
import re
import shutil
import tempfile
import zipfile
from collections.abc import Callable, Iterator
from concurrent.futures import ProcessPoolExecutor
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path, PurePosixPath
from typing import Any

import numpy as np
import pandas as pd
import py7zr
import pyarrow as pa
import pyarrow.parquet as pq

from src.intraday.data import HUNDREDFOLD_UNIT_DATES, MINUTE_COLUMNS, minute_bar_end_times
from src.intraday.targets import normalize_stock_code

MINUTE_SOURCE_DIRECTORY = "stock_minute"
DAILY_SOURCE_DIRECTORY = "日K线数据---复权因子-经典技术指标--bs点缠论划线"
MONEY_FLOW_SOURCE_DIRECTORY = "日线资金--每日沪深京个股日线数据和资金流数据"
FINANCIAL_SOURCE_DIRECTORY = "财报报表---有史以来--每周更新"

DATASET_NAMES = ("minute", "daily", "money_flow", "financial")
MONEY_FLOW_COLUMN_NAMES = {
    "序": "rank",
    "代码": "code",
    "名称": "name",
    "最新": "close",
    "涨幅%": "pct_change",
    "主力净流入": "main_net_inflow",
    "集合竞价": "opening_auction_net_inflow",
    "超大单流入": "extra_large_inflow",
    "超大单流出": "extra_large_outflow",
    "超大单净额": "extra_large_net_inflow",
    "超大单净占比%": "extra_large_net_ratio",
    "大单流入": "large_inflow",
    "大单流出": "large_outflow",
    "大单净额": "large_net_inflow",
    "大单净占比%": "large_net_ratio",
    "中单流入": "medium_inflow",
    "中单流出": "medium_outflow",
    "中单净额": "medium_net_inflow",
    "中单净占比%": "medium_net_ratio",
    "小单流入": "small_inflow",
    "小单流出": "small_outflow",
    "小单净额": "small_net_inflow",
    "小单净占比%": "small_net_ratio",
}
MONEY_AMOUNT_COLUMNS = [
    "main_net_inflow",
    "opening_auction_net_inflow",
    "extra_large_inflow",
    "extra_large_outflow",
    "extra_large_net_inflow",
    "large_inflow",
    "large_outflow",
    "large_net_inflow",
    "medium_inflow",
    "medium_outflow",
    "medium_net_inflow",
    "small_inflow",
    "small_outflow",
    "small_net_inflow",
]
MONEY_RATIO_COLUMNS = [
    "pct_change",
    "extra_large_net_ratio",
    "large_net_ratio",
    "medium_net_ratio",
    "small_net_ratio",
]

_DAILY_ARCHIVES: list[zipfile.ZipFile] = []
_DAILY_MEMBER_MAPS: list[dict[str, str]] = []
_DAILY_DELISTED_PATHS: dict[str, Path] = {}
_DAILY_OUTPUT_ROOT: Path | None = None
_DAILY_OVERWRITE = False


# ===================== 命令行与流程编排 ===================== #

# 读取物化任务参数，并限制数据集名称和并行度。
def parse_args() -> argparse.Namespace:
    """解析 Parquet 数据层物化参数。

    输入：
    - 从命令行读取只读原始数据根、输出根、数据集列表、进程数和覆盖
      开关。

    输出：
    - 返回校验后的 ``argparse.Namespace``。

    功能和用途：
    - 统一四类数据的运行入口，默认处理全部数据集。
    - ``--overwrite`` 只允许覆盖输出层文件，不会修改原始目录。
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument(
        "--datasets",
        nargs="+",
        choices=DATASET_NAMES,
        default=list(DATASET_NAMES),
    )
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--overwrite", action="store_true")
    arguments = parser.parse_args()
    if arguments.workers < 1:
        parser.error("--workers 必须大于 0")
    return arguments


# 串联四类数据的物化步骤，并在成功后发布统一清单。
def main() -> None:
    """执行用户选择的数据集物化任务。

    输入：
    - 使用 ``parse_args`` 返回的命令行参数。

    输出：
    - 在输出根下写入 Parquet 文件和 ``data_manifest.json``，无 Python 返回值。

    功能和用途：
    - 按分钟、日线、资金流、财报顺序执行，已存在文件默认跳过。
    - 只有已完成的数据集才会进入最终清单，失败时保留可续跑的已发布
      文件。
    """
    arguments = parse_args()
    source_root = arguments.source_root.expanduser().resolve()
    output_root = arguments.output_root.expanduser().resolve()
    if not source_root.is_dir():
        raise FileNotFoundError(f"原始数据根不存在: {source_root}")
    output_root.mkdir(parents=True, exist_ok=True)

    manifest: dict[str, Any] = {
        "created_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "source_root": str(source_root),
        "output_root": str(output_root),
        "datasets": {},
    }
    if "minute" in arguments.datasets:
        manifest["datasets"]["minute_bars"] = materialize_minute_bars(
            source_root / MINUTE_SOURCE_DIRECTORY,
            output_root / "minute_bars",
            arguments.workers,
            arguments.overwrite,
        )
    if "daily" in arguments.datasets:
        manifest["datasets"]["daily_bars"] = materialize_daily_bars(
            source_root / DAILY_SOURCE_DIRECTORY,
            output_root / "daily_bars",
            arguments.workers,
            arguments.overwrite,
        )
    if "money_flow" in arguments.datasets:
        manifest["datasets"]["money_flow"] = materialize_money_flow(
            source_root / MONEY_FLOW_SOURCE_DIRECTORY,
            output_root / "money_flow",
            arguments.overwrite,
        )
    if "financial" in arguments.datasets:
        manifest["datasets"]["financial_statements"] = materialize_financial_statements(
            source_root / FINANCIAL_SOURCE_DIRECTORY,
            output_root / "financial_statements",
            arguments.overwrite,
        )
    _write_json_atomic(manifest, output_root / "data_manifest.json")


# ===================== 分钟行情物化 ===================== #

# 将每日分钟压缩包并行转换为按年分目录的标准 Parquet。
def materialize_minute_bars(
    source_root: Path,
    output_root: Path,
    workers: int,
    overwrite: bool,
) -> dict[str, Any]:
    """物化全历史分钟行情。

    输入：
    - ``source_root``：包含每日 ZIP/7z 的分钟原始目录。
    - ``output_root``：英文输出目录 ``minute_bars``。
    - ``workers``：并行转换进程数。
    - ``overwrite``：是否重建已经存在的日期文件。

    输出：
    - 返回文件数、行数、日期范围、重复成员和无效成员统计。

    功能和用途：
    - 每个交易日输出 ``YYYY/YYYY-MM-DD.parquet``，每只股票保留 240 根 bar。
    - 已知三日成交额和成交量单位异常在此统一修正，后续回测不再读
      压缩包。
    """
    archive_paths = sorted([*source_root.rglob("*.zip"), *source_root.rglob("*.7z")])
    if not archive_paths:
        raise FileNotFoundError(f"分钟原始目录没有 ZIP/7z: {source_root}")
    output_root.mkdir(parents=True, exist_ok=True)
    tasks = [(str(path), str(output_root), overwrite) for path in archive_paths]
    results: list[dict[str, Any]] = []
    with ProcessPoolExecutor(max_workers=workers) as executor:
        for result in executor.map(_convert_minute_archive, tasks, chunksize=1):
            results.append(result)
            if len(results) % 25 == 0 or len(results) == len(tasks):
                print(f"minute_bars: {len(results)}/{len(tasks)}", flush=True)
    return {
        "files": len(results),
        "rows": sum(result["rows"] for result in results),
        "first_date": min(result["date"] for result in results),
        "last_date": max(result["date"] for result in results),
        "duplicate_members": sum(result["duplicate_members"] for result in results),
        "invalid_members": sum(result["invalid_members"] for result in results),
        "skipped_existing": sum(result["skipped"] for result in results),
    }


# 把单个交易日的所有有效股票分批写成一个 Parquet 文件。
def _convert_minute_archive(task: tuple[str, str, bool]) -> dict[str, Any]:
    """转换一个每日分钟 ZIP。

    输入：
    - ``task``：原始 ZIP、输出根和覆盖开关组成的元组。

    输出：
    - 返回该日的行数、重复成员数、无效成员数和跳过状态。

    功能和用途：
    - 逐批读取股票 CSV，避免把全市场所有小表同时留在内存中。
    - 同代码重复成员使用 ZIP 中首份文件；异常成员计数但不写入结果。
    """
    archive_path = Path(task[0])
    output_root = Path(task[1])
    overwrite = task[2]
    date_text = _date_from_text(archive_path.stem)
    trading_date = pd.Timestamp(date_text)
    output_path = output_root / date_text[:4] / f"{trading_date:%Y-%m-%d}.parquet"
    if output_path.is_file() and not overwrite:
        rows = pq.ParquetFile(output_path).metadata.num_rows
        return {
            "date": str(trading_date.date()),
            "rows": rows,
            "duplicate_members": 0,
            "invalid_members": 0,
            "skipped": 1,
        }

    output_path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = _temporary_output_path(output_path)
    writer: pq.ParquetWriter | None = None
    row_count = 0
    invalid_members = 0
    try:
        with _open_minute_archive(archive_path) as (members, duplicate_codes, read_member):
            frame_batch: list[pd.DataFrame] = []
            for code, member_name in sorted(members.items()):
                frame = _read_minute_member(
                    read_member(member_name),
                    trading_date,
                    code,
                )
                if frame is None:
                    invalid_members += 1
                    continue
                frame_batch.append(frame)
                if len(frame_batch) < 64:
                    continue
                writer, written_rows = _write_minute_batch(writer, temporary_path, frame_batch)
                row_count += written_rows
                frame_batch.clear()
            if frame_batch:
                writer, written_rows = _write_minute_batch(writer, temporary_path, frame_batch)
                row_count += written_rows
        if writer is None:
            raise ValueError(f"分钟归档没有有效股票: {archive_path}")
        writer.close()
        writer = None
        os.replace(temporary_path, output_path)
    finally:
        if writer is not None:
            writer.close()
        temporary_path.unlink(missing_ok=True)
    return {
        "date": str(trading_date.date()),
        "rows": row_count,
        "duplicate_members": len(duplicate_codes),
        "invalid_members": invalid_members,
        "skipped": 0,
    }


@contextmanager
def _open_minute_archive(
    archive_path: Path,
) -> Iterator[tuple[dict[str, str], set[str], Callable[[str], bytes]]]:
    """按实际容器读取 ZIP 或 7z，兼容文件名为 .zip 的 7z 日包。"""
    if zipfile.is_zipfile(archive_path):
        with zipfile.ZipFile(archive_path) as archive:
            members, duplicates = _minute_member_lookup(archive.infolist())
            yield members, duplicates, archive.read
        return

    # 7z 使用临时解包目录，CSV 解析和数据口径复用现有分钟转换逻辑。
    with tempfile.TemporaryDirectory(prefix="backtest_minute_") as directory:
        extraction_root = Path(directory)
        with py7zr.SevenZipFile(archive_path, "r") as archive:
            member_infos = [zipfile.ZipInfo(name) for name in archive.getnames()]
            archive.extractall(extraction_root)
        members, duplicates = _minute_member_lookup(member_infos)

        def read_member(member_name: str) -> bytes:
            return (extraction_root / member_name).read_bytes()

        yield members, duplicates, read_member


# 识别 ZIP 中每只股票的首个 CSV，并统计重复代码成员。
def _minute_member_lookup(
    member_infos: list[zipfile.ZipInfo],
) -> tuple[dict[str, str], set[str]]:
    """建立分钟 ZIP 的股票代码到成员路径映射。

    输入：
    - ``member_infos``：ZIP 中完整成员信息。

    输出：
    - 返回首份成员映射和出现多次的标准股票代码集合。

    功能和用途：
    - 同时兼容 ``sh/600000.csv`` 与 ``YYYYMMDD/sh/600000.csv`` 等结构。
    - 包内原路径保持不变，只在读取时解析市场和六位代码。
    """
    members: dict[str, str] = {}
    duplicate_codes: set[str] = set()
    for info in member_infos:
        path = PurePosixPath(info.filename.replace("\\", "/"))
        if info.is_dir() or path.suffix.lower() != ".csv" or len(path.parts) < 2:
            continue
        exchange = path.parts[-2].lower()
        matched = re.search(r"\d{6}", path.stem)
        if exchange not in {"sh", "sz", "bj"} or matched is None:
            continue
        code = normalize_stock_code(f"{matched.group()}.{exchange.upper()}")
        if code in members:
            duplicate_codes.add(code)
            continue
        members[code] = info.filename
    return members, duplicate_codes


# 将单只股票 CSV 规范为统一字段、时区和成交单位。
def _read_minute_member(
    content: bytes,
    trading_date: pd.Timestamp,
    code: str,
) -> pd.DataFrame | None:
    """读取并校验单只股票的一日分钟表。

    输入：
    - ``content``：ZIP 成员的 CSV 字节。
    - ``trading_date``：该压缩包对应的交易日。
    - ``code``：带市场后缀的标准股票代码。

    输出：
    - 返回 240 行标准分钟表；字段或数值不合格时返回 ``None``。

    功能和用途：
    - 忽略原始可选 ``time`` 列，用固定 A 股交易时段重建分钟结束时刻。
    - 计算 VWAP，并修复数据说明中已经确认的三日百倍单位异常。
    """
    if not content:
        return None
    frame = pd.read_csv(io.BytesIO(content))
    column_names = {str(column) for column in frame.columns}
    if not set(MINUTE_COLUMNS).issubset(column_names):
        return None
    if not column_names <= set(MINUTE_COLUMNS) | {"time"} or len(frame) != 240:
        return None
    frame = frame.loc[:, MINUTE_COLUMNS].copy()
    for column in MINUTE_COLUMNS:
        frame[column] = pd.to_numeric(frame[column], errors="coerce")
    if frame[MINUTE_COLUMNS].isna().any().any():
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


# 把一批股票分钟表追加为独立 row group，便于按代码过滤。
def _write_minute_batch(
    writer: pq.ParquetWriter | None,
    temporary_path: Path,
    frames: list[pd.DataFrame],
) -> tuple[pq.ParquetWriter, int]:
    """追加写入一批分钟行情。

    输入：
    - ``writer``：首次调用为 ``None``，后续复用已打开的 Parquet writer。
    - ``temporary_path``：尚未发布的临时输出路径。
    - ``frames``：同一交易日的一组股票分钟表。

    输出：
    - 返回 writer 和本批写入行数。

    功能和用途：
    - 每 64 只股票形成一个 row group，控制内存并保留代码统计信息供
      过滤下推。
    """
    combined = pd.concat(frames, ignore_index=True)
    table = pa.Table.from_pandas(combined, preserve_index=False)
    if writer is None:
        writer = pq.ParquetWriter(
            temporary_path,
            table.schema,
            compression="zstd",
            use_dictionary=["code"],
        )
    writer.write_table(table)
    return writer, len(combined)


# ===================== 日线行情物化 ===================== #

# 将全量、增量和退市股票日线合并为按股票存储的 Parquet。
def materialize_daily_bars(
    source_root: Path,
    output_root: Path,
    workers: int,
    overwrite: bool,
) -> dict[str, Any]:
    """物化全历史日线行情。

    输入：
    - ``source_root``：包含全量 ZIP、增量 ZIP 和退市股 XLSX 的原始目录。
    - ``output_root``：英文输出目录 ``daily_bars``。
    - ``workers``：并行解析股票 XLSX 的进程数。
    - ``overwrite``：是否重建已有股票文件。

    输出：
    - 返回股票文件数、总行数、日期范围和跳过数量。

    功能和用途：
    - 每只股票输出 ``<code>.<market>.parquet``，增量快照覆盖较早快照的
      同日记录。
    - 退市数据先作为低优先级历史补充，不会覆盖完整日线中的同日记录。
    """
    archive_paths = sorted(source_root.glob("*.zip"), key=_daily_archive_priority)
    if not archive_paths:
        raise FileNotFoundError(f"日线原始目录没有 ZIP: {source_root}")
    archive_member_maps: list[dict[str, str]] = []
    for archive_path in archive_paths:
        with zipfile.ZipFile(archive_path) as archive:
            archive_member_maps.append(_daily_member_lookup(archive.infolist()))
    delisted_paths, empty_delisted_sources = _daily_delisted_lookup(
        source_root / "退市股"
    )
    codes = sorted(set(delisted_paths).union(*(set(mapping) for mapping in archive_member_maps)))
    output_root.mkdir(parents=True, exist_ok=True)
    initializer_arguments = (
        [str(path) for path in archive_paths],
        {code: str(path) for code, path in delisted_paths.items()},
        str(output_root),
        overwrite,
    )
    results: list[dict[str, Any]] = []
    with ProcessPoolExecutor(
        max_workers=workers,
        initializer=_initialize_daily_worker,
        initargs=initializer_arguments,
    ) as executor:
        for result in executor.map(_convert_daily_symbol, codes, chunksize=8):
            results.append(result)
            if len(results) % 100 == 0 or len(results) == len(codes):
                print(f"daily_bars: {len(results)}/{len(codes)}", flush=True)
    dated_results = [result for result in results if result["first_date"] is not None]
    return {
        "files": len(results),
        "rows": sum(result["rows"] for result in results),
        "first_date": min(result["first_date"] for result in dated_results),
        "last_date": max(result["last_date"] for result in dated_results),
        "skipped_existing": sum(result["skipped"] for result in results),
        "empty_delisted_sources": empty_delisted_sources,
    }


# 为每个日线工作进程打开一次 ZIP，避免按股票反复读取目录。
def _initialize_daily_worker(
    archive_paths: list[str],
    delisted_paths: dict[str, str],
    output_root: str,
    overwrite: bool,
) -> None:
    """初始化日线并行进程的只读数据句柄。

    输入：
    - ``archive_paths``：按覆盖优先级排序的日线 ZIP。
    - ``delisted_paths``：标准代码到退市 XLSX 的映射。
    - ``output_root``：日线 Parquet 输出根。
    - ``overwrite``：是否覆盖已有文件。

    输出：
    - 无返回值，把只读句柄和配置保存到当前子进程模块状态。

    功能和用途：
    - 一个工作进程只打开每个大 ZIP 一次，减少 5,000 多只股票转换时的
      固定开销。
    """
    global _DAILY_ARCHIVES
    global _DAILY_MEMBER_MAPS
    global _DAILY_DELISTED_PATHS
    global _DAILY_OUTPUT_ROOT
    global _DAILY_OVERWRITE

    _DAILY_ARCHIVES = [zipfile.ZipFile(path) for path in archive_paths]
    _DAILY_MEMBER_MAPS = [
        _daily_member_lookup(archive.infolist()) for archive in _DAILY_ARCHIVES
    ]
    _DAILY_DELISTED_PATHS = {
        code: Path(path) for code, path in delisted_paths.items()
    }
    _DAILY_OUTPUT_ROOT = Path(output_root)
    _DAILY_OVERWRITE = overwrite


# 合并单只股票的退市、全量和增量记录，并按日期去重。
def _convert_daily_symbol(code: str) -> dict[str, Any]:
    """转换一只股票的完整日线历史。

    输入：
    - ``code``：带市场后缀的标准股票代码。

    输出：
    - 返回该股票行数、日期范围和跳过状态。

    功能和用途：
    - 子进程按低到高优先级拼接来源，同日期保留最后一条。
    - 输出使用原子替换，任务中断不会留下可见的半文件。
    """
    if _DAILY_OUTPUT_ROOT is None:
        raise RuntimeError("日线工作进程尚未初始化")
    output_path = _DAILY_OUTPUT_ROOT / f"{code}.parquet"
    if output_path.is_file() and not _DAILY_OVERWRITE:
        metadata = pq.ParquetFile(output_path).metadata
        date_values = pd.read_parquet(output_path, columns=["date"])["date"]
        return {
            "code": code,
            "rows": metadata.num_rows,
            "first_date": str(date_values.min().date()) if not date_values.empty else None,
            "last_date": str(date_values.max().date()) if not date_values.empty else None,
            "skipped": 1,
        }
    frames: list[pd.DataFrame] = []
    delisted_path = _DAILY_DELISTED_PATHS.get(code)
    if delisted_path is not None:
        frames.append(pd.read_excel(delisted_path))
    for archive, member_map in zip(_DAILY_ARCHIVES, _DAILY_MEMBER_MAPS):
        member_name = member_map.get(code)
        if member_name is not None:
            frames.append(pd.read_excel(io.BytesIO(archive.read(member_name))))
    if not frames:
        raise ValueError(f"日线来源为空: {code}")
    normalized = [_normalize_daily_frame(frame, code) for frame in frames]
    combined = pd.concat(normalized, ignore_index=True, sort=False)
    combined = (
        combined.dropna(subset=["date"])
        .drop_duplicates(["date", "code"], keep="last")
        .sort_values(["date", "code"], kind="stable")
        .reset_index(drop=True)
    )
    _write_parquet_atomic(combined, output_path)
    return {
        "code": code,
        "rows": len(combined),
        "first_date": str(combined["date"].min().date()),
        "last_date": str(combined["date"].max().date()),
        "skipped": 0,
    }


# 为日线 ZIP 建立标准股票代码到 XLSX 成员的映射。
def _daily_member_lookup(member_infos: list[zipfile.ZipInfo]) -> dict[str, str]:
    """解析日线 ZIP 成员。

    输入：
    - ``member_infos``：ZIP 的成员信息列表。

    输出：
    - 返回标准股票代码到 XLSX 成员路径的映射。

    功能和用途：
    - 只接受文件名中可识别六位 A 股代码的 XLSX，忽略目录和说明文件。
    """
    members: dict[str, str] = {}
    for info in member_infos:
        path = Path(PurePosixPath(info.filename.replace("\\", "/")).name)
        if info.is_dir() or path.suffix.lower() != ".xlsx":
            continue
        code = _code_from_path(path)
        if code is not None:
            members[code] = info.filename
    return members


# 空退市占位表不是有效股票历史，在生成代码集合前排除。
def _daily_delisted_lookup(directory: Path) -> tuple[dict[str, Path], int]:
    """建立有数据的退市股文件映射。

    输入：
    - ``directory``：退市股 XLSX 所在目录。

    输出：
    - 返回标准代码到非空 XLSX 的映射，以及空占位文件数量。

    功能和用途：
    - 供应商退市目录包含只有表头或连表头都没有的占位表。
    - 只排除零数据行文件；非空文件仍由后续 schema 校验严格处理。
    """
    delisted_paths: dict[str, Path] = {}
    empty_source_count = 0
    for path in sorted(directory.glob("*.xlsx")):
        code = _code_from_path(path)
        if code is None:
            continue
        if pd.read_excel(path, nrows=1).empty:
            empty_source_count += 1
            continue
        delisted_paths[code] = path
    return delisted_paths, empty_source_count


# 将不同来源的单股日线统一日期、代码和无效索引列。
def _normalize_daily_frame(frame: pd.DataFrame, code: str) -> pd.DataFrame:
    """规范化单只股票日线表。

    输入：
    - ``frame``：全量、增量或退市来源读取出的 DataFrame。
    - ``code``：从文件名确认的标准股票代码。

    输出：
    - 返回至少包含 ``date`` 和 ``code`` 的规范表，其他供应商字段原样保留。

    功能和用途：
    - 删除 Excel 导出的匿名索引列，统一日期类型和股票代码。
    - 不翻译供应商指标列，避免在未建立字段字典时改变业务含义。
    """
    retained_columns = [
        column for column in frame if not str(column).startswith("Unnamed:")
    ]
    normalized = frame.loc[:, retained_columns].copy()
    date_column = next(
        (column for column in ("date", "日期", "交易日期") if column in normalized),
        None,
    )
    if date_column is None:
        raise ValueError(f"{code} 日线缺少日期列")
    if date_column != "date":
        normalized = normalized.rename(columns={date_column: "date"})
    normalized["date"] = pd.to_datetime(normalized["date"], errors="coerce").dt.normalize()
    if "code" in normalized:
        normalized["code"] = code
    else:
        normalized.insert(1, "code", code)
    return normalized


# 按全量基线在前、较新增量在后的顺序确定覆盖优先级。
def _daily_archive_priority(path: Path) -> tuple[int, str]:
    """计算日线 ZIP 的合并优先级。

    输入：
    - ``path``：日线 ZIP 路径。

    输出：
    - 返回排序元组，全量大包排在增量包之前，增量按文件名日期递增。

    功能和用途：
    - 确保最新增量快照在同日冲突时覆盖旧快照。
    """
    is_full_snapshot = path.stat().st_size > 1_000_000_000
    return (0 if is_full_snapshot else 1, path.name)


# ===================== 资金流与财报物化 ===================== #

# 汇总所有 zj.xls，规范代码和带“万/亿”的金额后按年份写出。
def materialize_money_flow(
    source_root: Path,
    output_root: Path,
    overwrite: bool,
) -> dict[str, Any]:
    """物化日频个股资金流。

    输入：
    - ``source_root``：包含月包和日包的资金流原始目录。
    - ``output_root``：英文输出目录 ``money_flow``。
    - ``overwrite``：是否覆盖已有年度文件。

    输出：
    - 返回年度文件数、总行数和日期范围。

    功能和用途：
    - 只抽取代表个股资金流的 ``zj.xls``，兼容 GB18030 制表符文本。
    - 金额统一换算为元，比例统一为数值百分比，股票代码增加市场后缀。
    """
    dated_frames: list[pd.DataFrame] = []
    for archive_path in sorted(source_root.rglob("*.zip")):
        with zipfile.ZipFile(archive_path) as archive:
            for info in archive.infolist():
                if Path(info.filename).name.lower() != "zj.xls":
                    continue
                date_text = _date_from_text(info.filename)
                dated_frames.append(
                    _read_money_flow_member(archive.read(info), pd.Timestamp(date_text))
                )
    if not dated_frames:
        raise FileNotFoundError(f"资金流目录没有 zj.xls: {source_root}")
    combined = pd.concat(dated_frames, ignore_index=True)
    if combined.duplicated(["date", "code"]).any():
        duplicate_count = int(combined.duplicated(["date", "code"], keep=False).sum())
        raise ValueError(f"资金流 date/code 重复行数: {duplicate_count}")
    combined = combined.sort_values(["date", "code"], kind="stable").reset_index(drop=True)
    output_root.mkdir(parents=True, exist_ok=True)
    skipped_existing = 0
    for year, year_frame in combined.groupby(combined["date"].dt.year, sort=True):
        output_path = output_root / f"{year}.parquet"
        if output_path.is_file() and not overwrite:
            skipped_existing += 1
            continue
        _write_parquet_atomic(year_frame.reset_index(drop=True), output_path)
    return {
        "files": int(combined["date"].dt.year.nunique()),
        "rows": len(combined),
        "first_date": str(combined["date"].min().date()),
        "last_date": str(combined["date"].max().date()),
        "skipped_existing": skipped_existing,
    }


# 解析单日 GB18030 资金流文本，并统一列名和数值单位。
def _read_money_flow_member(content: bytes, trading_date: pd.Timestamp) -> pd.DataFrame:
    """读取一份个股资金流表。

    输入：
    - ``content``：名为 ``zj.xls`` 的制表符文本字节。
    - ``trading_date``：从 ZIP 成员路径提取的交易日。

    输出：
    - 返回英文列名、标准代码和元单位金额的单日资金流表。

    功能和用途：
    - 清理末尾空列和 Excel 公式样式代码，并把中文金额单位转换为数值。
    """
    frame = pd.read_csv(
        io.BytesIO(content),
        sep="\t",
        encoding="gb18030",
        dtype=str,
    )
    frame.columns = [str(column).strip() for column in frame.columns]
    frame = frame.loc[:, [column for column in frame if not column.startswith("Unnamed:")]]
    missing_columns = set(MONEY_FLOW_COLUMN_NAMES) - set(frame.columns)
    if missing_columns:
        raise ValueError(f"{trading_date.date()} 资金流缺列: {sorted(missing_columns)}")
    frame = frame.rename(columns=MONEY_FLOW_COLUMN_NAMES)
    frame = frame.loc[:, list(MONEY_FLOW_COLUMN_NAMES.values())].copy()
    frame.insert(0, "date", trading_date.normalize())
    frame["code"] = frame["code"].map(_normalize_money_flow_code)
    frame["name"] = frame["name"].astype("string").str.strip()
    frame["rank"] = pd.to_numeric(frame["rank"], errors="coerce").astype("Int64")
    frame["close"] = pd.to_numeric(frame["close"], errors="coerce")
    for column in MONEY_AMOUNT_COLUMNS:
        frame[column] = frame[column].map(_parse_chinese_amount).astype("float64")
    for column in MONEY_RATIO_COLUMNS:
        frame[column] = pd.to_numeric(frame[column], errors="coerce")
    return frame.dropna(subset=["code"]).reset_index(drop=True)


# 从 Excel 公式样式的六位代码推断沪深京交易所后缀。
def _normalize_money_flow_code(value: object) -> str | None:
    """规范资金流股票代码。

    输入：
    - ``value``：例如 ``= \"002549\"`` 的原始单元格文本。

    输出：
    - 返回 ``002549.SZ`` 等标准代码；无法识别时返回 ``None``。

    功能和用途：
    - 去除公式包装并按 A 股代码前缀补充市场后缀。
    """
    matched = re.search(r"\d{6}", str(value))
    if matched is None:
        return None
    return normalize_stock_code(matched.group())


# 将“7.68亿”“-9990万”等文本统一转换为元。
def _parse_chinese_amount(value: object) -> float:
    """解析带中文数量级的资金金额。

    输入：
    - ``value``：数字、空值或带 ``万``/``亿`` 后缀的文本。

    输出：
    - 返回以元为单位的浮点数；空白和占位符返回 ``NaN``。

    功能和用途：
    - 统一不同数量级，避免字符串排序或聚合造成错误。
    """
    if pd.isna(value):
        return float("nan")
    text = str(value).strip().replace(",", "")
    if text in {"", "--", "-", "—"}:
        return float("nan")
    multiplier = 1.0
    if text.endswith("亿"):
        multiplier = 100_000_000.0
        text = text[:-1]
    elif text.endswith("万"):
        multiplier = 10_000.0
        text = text[:-1]
    return float(text) * multiplier


# 复制最新完整财报 Parquet，并验证公司报告期主键唯一。
def materialize_financial_statements(
    source_root: Path,
    output_root: Path,
    overwrite: bool,
) -> dict[str, Any]:
    """物化最新财报历史快照。

    输入：
    - ``source_root``：包含带日期财报 Parquet 的原始目录。
    - ``output_root``：英文输出目录 ``financial_statements``。
    - ``overwrite``：是否覆盖已有英文快照。

    输出：
    - 返回源快照日期、行列数和主键重复数。

    功能和用途：
    - 最新周更文件本身包含全历史，因此只复制日期最大的完整快照。
    - 保留 423 列供应商字段原名，避免未经字段字典确认的语义翻译。
    """
    source_paths = sorted(source_root.glob("*_financial.parquet"))
    if not source_paths:
        raise FileNotFoundError(f"财报目录没有 financial parquet: {source_root}")
    source_path = max(source_paths, key=lambda path: _date_from_text(path.name))
    parquet_file = pq.ParquetFile(source_path)
    schema_names = set(parquet_file.schema_arrow.names)
    key_columns = ["code_0", "报告日期_1"]
    if not set(key_columns).issubset(schema_names):
        raise ValueError(f"财报缺少主键列: {key_columns}")
    keys = pd.read_parquet(source_path, columns=key_columns)
    duplicate_keys = int(keys.duplicated(key_columns, keep=False).sum())
    if duplicate_keys:
        raise ValueError(f"财报 code/report_date 重复行数: {duplicate_keys}")
    output_root.mkdir(parents=True, exist_ok=True)
    output_path = output_root / "financial_history.parquet"
    skipped_existing = int(output_path.is_file() and not overwrite)
    if not skipped_existing:
        temporary_path = _temporary_output_path(output_path)
        try:
            shutil.copyfile(source_path, temporary_path)
            os.replace(temporary_path, output_path)
        finally:
            temporary_path.unlink(missing_ok=True)
    return {
        "files": 1,
        "rows": parquet_file.metadata.num_rows,
        "columns": len(parquet_file.schema_arrow.names),
        "snapshot_date": _date_from_text(source_path.name),
        "duplicate_keys": duplicate_keys,
        "skipped_existing": skipped_existing,
    }


# ===================== 通用路径与原子写入 ===================== #

# 从文件名或成员路径中提取第一个合法八位日期。
def _date_from_text(value: str) -> str:
    """提取 YYYYMMDD 日期。

    输入：
    - ``value``：可能包含目录、连接符和其他文字的名称。

    输出：
    - 返回八位日期字符串；找不到合法日期时抛出 ``ValueError``。

    功能和用途：
    - 统一分钟包、资金流成员和财报快照的日期识别方式。
    """
    date_matches = re.findall(
        r"(?<!\d)(\d{4})[-_/]?(\d{2})[-_/]?(\d{2})(?!\d)",
        value,
    )
    for year, month, day in date_matches:
        candidate = f"{year}{month}{day}"
        try:
            pd.Timestamp(candidate)
        except ValueError:
            continue
        return candidate
    raise ValueError(f"名称中没有合法八位日期: {value}")


# 从文件名中的六位数字推断标准股票代码。
def _code_from_path(path: Path) -> str | None:
    """解析股票文件名。

    输入：
    - ``path``：日线 XLSX 或其他以六位代码命名的文件。

    输出：
    - 返回带交易所后缀的标准代码；无法识别时返回 ``None``。

    功能和用途：
    - 同时支持纯代码文件名和 ``代码_名称`` 文件名。
    """
    matched = re.search(r"\d{6}", path.stem)
    if matched is None:
        return None
    try:
        return normalize_stock_code(matched.group())
    except ValueError:
        return None


# 为目标文件创建同目录临时路径，保证最终替换不跨文件系统。
def _temporary_output_path(output_path: Path) -> Path:
    """创建原子写入使用的临时文件。

    输入：
    - ``output_path``：最终输出文件路径，父目录必须已存在。

    输出：
    - 返回已经创建、位于同一目录的临时路径。

    功能和用途：
    - 同目录临时文件可以通过 ``os.replace`` 原子发布，避免任务中断暴露
      半文件。
    """
    with tempfile.NamedTemporaryFile(
        prefix=f".{output_path.name}.",
        suffix=".tmp",
        dir=output_path.parent,
        delete=False,
    ) as temporary_file:
        return Path(temporary_file.name)


# 以 Zstandard 压缩写入 DataFrame，并在完成后原子替换目标。
def _write_parquet_atomic(frame: pd.DataFrame, output_path: Path) -> None:
    """原子写入 Parquet。

    输入：
    - ``frame``：需要持久化的数据表。
    - ``output_path``：最终 Parquet 路径。

    输出：
    - 无返回值，成功时目标文件完整可读。

    功能和用途：
    - 所有非流式数据集共用同一发布规则，失败时删除临时文件。
    """
    output_path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = _temporary_output_path(output_path)
    try:
        frame.to_parquet(
            temporary_path,
            index=False,
            engine="pyarrow",
            compression="zstd",
        )
        os.replace(temporary_path, output_path)
    finally:
        temporary_path.unlink(missing_ok=True)


# 以 UTF-8 JSON 原子发布数据层清单。
def _write_json_atomic(values: object, output_path: Path) -> None:
    """原子写入数据清单。

    输入：
    - ``values``：可序列化的清单对象。
    - ``output_path``：最终 JSON 路径。

    输出：
    - 无返回值，成功时目标文件为完整 UTF-8 JSON。

    功能和用途：
    - 记录每类数据的覆盖范围和质量统计，供全量转换验收。
    """
    output_path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = _temporary_output_path(output_path)
    try:
        temporary_path.write_text(
            json.dumps(values, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        os.replace(temporary_path, output_path)
    finally:
        temporary_path.unlink(missing_ok=True)


if __name__ == "__main__":
    main()
