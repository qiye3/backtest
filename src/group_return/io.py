"""用单个 Parquet 保存和恢复一个因子的评价结果。"""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any

import pandas as pd

RESULT_FILE_NAME = "group_return.parquet"
FACTOR_SUMMARY_FILE_NAMES = {
    "daily": "factor_summary_daily.csv",
    "weekly": "factor_summary_weekly.csv",
}
_SAVED_TABLES = [
    "definitions",
    "detail",
    "ic",
    "summary",
    "ic_summary",
    "factor_quality",
]


def save_evaluation_results(
    results: Mapping[str, Mapping[str, Any]],
    output_root: str | Path,
) -> dict[str, Path]:
    """覆盖保存一批评价结果，省略逐股成员和标签大表。"""
    output_root = Path(output_root)
    output_paths = {}
    for factor_name, result in results.items():
        packed_tables = [
            _pack_frame(result[table_name], table_name)
            for table_name in _SAVED_TABLES
        ]
        stored_result = pd.concat(packed_tables, ignore_index=True)

        factor_directory = output_root / factor_name
        factor_directory.mkdir(parents=True, exist_ok=True)
        output_path = factor_directory / RESULT_FILE_NAME
        stored_result.to_parquet(output_path, index=False)
        output_paths[factor_name] = output_path
    return output_paths


def save_factor_summaries(
    factor_summaries: Mapping[str, pd.DataFrame],
    output_root: str | Path,
) -> dict[str, Path]:
    """按调仓频率覆盖保存每因子一行的汇总表。"""
    output_root = Path(output_root)
    output_root.mkdir(parents=True, exist_ok=True)
    output_paths = {}
    for frequency, factor_summary in factor_summaries.items():
        output_path = output_root / FACTOR_SUMMARY_FILE_NAMES[frequency]
        factor_summary.to_csv(output_path, index=False)
        output_paths[frequency] = output_path
    return output_paths


def load_factor_summaries(
    output_root: str | Path,
) -> dict[str, pd.DataFrame]:
    """读取根目录中已经存在的各调仓频率汇总表。"""
    output_root = Path(output_root)
    return {
        frequency: pd.read_csv(output_root / file_name)
        for frequency, file_name in FACTOR_SUMMARY_FILE_NAMES.items()
        if (output_root / file_name).exists()
    }


def load_evaluation_results(
    factor_names: Iterable[str],
    output_root: str | Path,
) -> dict[str, dict[str, Any]]:
    """加载指定因子中已经存在的评价结果。"""
    output_root = Path(output_root)
    results = {}
    for factor_name in factor_names:
        result_path = output_root / factor_name / RESULT_FILE_NAME
        if not result_path.exists():
            continue
        stored_result = pd.read_parquet(result_path)
        result = {
            table_name: _unpack_frame(stored_result, table_name)
            for table_name in _SAVED_TABLES
        }
        result["sample_dates"] = pd.DatetimeIndex(
            result["detail"]["date"].drop_duplicates(),
            name="date",
        )
        results[factor_name] = result
    return results


def load_evaluation_result(
    factor_name: str,
    output_root: str | Path,
) -> dict[str, Any] | None:
    """加载一个因子已经存在的完整评价结果。"""
    return load_evaluation_results([factor_name], output_root).get(factor_name)


def load_evaluation_summaries(
    factor_names: Iterable[str],
    output_root: str | Path,
) -> dict[str, dict[str, pd.DataFrame]]:
    """只加载汇总指标所需的各因子 IC 汇总表。"""
    output_root = Path(output_root)
    summaries = {}
    for factor_name in factor_names:
        result_path = output_root / factor_name / RESULT_FILE_NAME
        if not result_path.exists():
            continue
        stored_result = pd.read_parquet(result_path)
        summaries[factor_name] = {
            "ic_summary": _unpack_frame(stored_result, "ic_summary")
        }
    return summaries


def _pack_frame(frame: pd.DataFrame, record_type: str) -> pd.DataFrame:
    """把一张结果表及其列结构编码成可合并记录。"""
    column_names = json.dumps(list(frame.columns), ensure_ascii=False)
    schema_record = pd.DataFrame(
        {
            "__record_type": [record_type],
            "__schema": [True],
            "__columns": [column_names],
        }
    )
    records = frame.copy()
    records["__record_type"] = record_type
    records["__schema"] = False
    records["__columns"] = None
    return pd.concat([schema_record, records], ignore_index=True)


def _unpack_frame(
    stored_result: pd.DataFrame,
    record_type: str,
) -> pd.DataFrame:
    """按保存的列顺序恢复一张评价结果表。"""
    selected = stored_result.loc[
        stored_result["__record_type"] == record_type
    ]
    schema_record = selected.loc[selected["__schema"]].iloc[0]
    column_names = json.loads(schema_record["__columns"])
    return selected.loc[~selected["__schema"], column_names].reset_index(
        drop=True
    )
