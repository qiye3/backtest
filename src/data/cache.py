"""管理 MarketData 的来源级共享 Parquet 缓存和元数据。"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Mapping

import pandas as pd


def resolve_market_cache_directory(
    config_path: Path,
    cache_root: str | Path,
) -> Path:
    """
    解析所有 YAML 共享的 MarketData 缓存目录。

    相对路径以当前 YAML 所在目录为基准；返回值不再附加 YAML 文件名，因此只要
    多份配置指向同一个 ``cache_root``，就会复用同一套来源缓存。
    """
    resolved_cache_root = Path(cache_root).expanduser()
    if not resolved_cache_root.is_absolute():
        resolved_cache_root = config_path.parent / resolved_cache_root
    return resolved_cache_root.resolve()


def load_source_metadata(
    cache_directory: Path,
    source_name: str,
) -> dict[str, Any] | None:
    """
    读取单个来源的 metadata。

    两个文件必须同时存在才算可复用缓存。旧版只有 Parquet、没有 metadata 的缓存
    无法证明字段和日期覆盖范围，因此由上层重新构建并覆盖。
    """
    cache_path = cache_directory / f"{source_name}.parquet"
    metadata_path = cache_directory / f"{source_name}.meta.json"
    if not cache_path.exists() or not metadata_path.exists():
        return None

    return json.loads(metadata_path.read_text(encoding="utf-8"))


def load_source_data(
    cache_directory: Path,
    source_name: str,
) -> pd.DataFrame:
    """在 metadata 已通过复用检查后读取来源面板或明细长表。"""
    cache_path = cache_directory / f"{source_name}.parquet"
    return pd.read_parquet(cache_path)


def load_financial_records(
    cache_directory: Path,
    source_name: str,
) -> pd.DataFrame | None:
    """读取财务来源的规范化事件记录；旧缓存没有伴随文件时返回空。"""
    records_path = cache_directory / f"{source_name}.records.parquet"
    if not records_path.exists():
        return None
    return pd.read_parquet(records_path)


def save_source_cache(
    cache_directory: Path,
    source_name: str,
    source_data: pd.DataFrame,
    metadata: Mapping[str, Any],
) -> Path:
    """覆盖保存单个来源的数据及其复用条件。"""
    cache_directory.mkdir(parents=True, exist_ok=True)
    cache_path = cache_directory / f"{source_name}.parquet"
    metadata_path = cache_directory / f"{source_name}.meta.json"
    temporary_cache_path = cache_directory / f"{source_name}.tmp.parquet"
    temporary_metadata_path = cache_directory / f"{source_name}.meta.json.tmp"
    source_data.to_parquet(temporary_cache_path)
    temporary_metadata_path.write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    os.replace(temporary_cache_path, cache_path)
    os.replace(temporary_metadata_path, metadata_path)
    return cache_path


def save_financial_records(
    cache_directory: Path,
    source_name: str,
    financial_records: pd.DataFrame,
) -> Path:
    """保存财务公告事件，供报告期历史算子按 PIT 时点复原。"""
    cache_directory.mkdir(parents=True, exist_ok=True)
    records_path = cache_directory / f"{source_name}.records.parquet"
    temporary_path = cache_directory / f"{source_name}.records.tmp.parquet"
    financial_records.to_parquet(temporary_path)
    os.replace(temporary_path, records_path)
    return records_path
