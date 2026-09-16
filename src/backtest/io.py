"""用单个 Parquet 保存和恢复一个因子的回测核心结果。"""

from __future__ import annotations

import json
import pickle
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any

import pandas as pd

from src.backtest.events import make_curve_views

RESULT_FILE_NAMES = {
    "simple": "simple_backtest.parquet",
    "account": "account_backtest.parquet",
}
CHECKPOINT_FILE_NAMES = {
    "simple": "simple_backtest.checkpoint.pkl",
    "account": "account_backtest.checkpoint.pkl",
}


def build_metrics_summary(
    results: Mapping[str, Mapping[str, Any]],
) -> pd.DataFrame:
    """汇总各因子 simple 回测的 G10 指标。"""
    metric_frames = []
    for factor_name, factor_result in results.items():
        factor_metrics = factor_result["metrics"].loc[
            lambda frame: frame["group_id"] == "G10",
            [
                "rebalance_frequency",
                "rebalance_interval",
                "total_return",
                "annual_return",
                "sharpe",
                "annual_turnover",
                "benchmark_total_return",
                "excess_total_return",
            ],
        ].copy()
        factor_metrics.insert(0, "factor_name", factor_name)
        factor_metrics = factor_metrics.rename(
            columns={"annual_turnover": "turnover"}
        )
        metric_frames.append(factor_metrics)
    return pd.concat(metric_frames, ignore_index=True)


def save_backtest_results(
    results: Mapping[str, Mapping[str, Any]],
    output_root: str | Path,
    mode: str,
    save_details: bool = False,
) -> dict[str, Path]:
    """覆盖保存汇总指标，并按配置选择是否保留回测明细。"""
    output_root = Path(output_root)
    output_paths = {}
    for factor_name, result in results.items():
        rebalance_frequency = result["rebalance_frequency"]
        packed_frames = [
            _pack_frame(
                result["definitions"],
                "definitions",
                rebalance_frequency=rebalance_frequency,
            ),
            _pack_frame(
                result["metrics"],
                "metrics",
                rebalance_frequency=rebalance_frequency,
            ),
        ]
        if save_details:
            packed_frames.extend(
                _pack_backtest_details(result, rebalance_frequency)
            )

        stored_result = pd.concat(packed_frames, ignore_index=True)
        factor_directory = output_root / factor_name
        factor_directory.mkdir(parents=True, exist_ok=True)
        output_path = factor_directory / RESULT_FILE_NAMES[mode]
        stored_result.to_parquet(output_path, index=False)
        output_paths[factor_name] = output_path
    return output_paths


def save_backtest_checkpoints(
    results: Mapping[str, Mapping[str, Any]],
    output_root: str | Path,
    mode: str,
) -> dict[str, Path]:
    """逐因子流式保存完整内部 checkpoint，避免拼接回测明细。"""
    output_root = Path(output_root)
    output_paths = {}
    for factor_name, result in results.items():
        factor_directory = output_root / factor_name
        factor_directory.mkdir(parents=True, exist_ok=True)
        output_path = factor_directory / CHECKPOINT_FILE_NAMES[mode]
        with output_path.open("wb") as checkpoint_file:
            pickle.dump(
                result,
                checkpoint_file,
                protocol=pickle.HIGHEST_PROTOCOL,
            )
        output_paths[factor_name] = output_path
    return output_paths


def _pack_backtest_details(
    result: Mapping[str, Any],
    rebalance_frequency: str,
) -> list[pd.DataFrame]:
    """打包各调仓周期的动作、曲线、逐股成交和换手明细。"""
    packed_frames = []
    for interval, period_result in result["periods"].items():
        period_context = {
            "rebalance_frequency": rebalance_frequency,
            "rebalance_interval": interval,
        }
        packed_frames.append(
            _pack_frame(
                period_result["actions"],
                "actions",
                **period_context,
            )
        )
        for group_id, group_result in period_result["groups"].items():
            curve_views = group_result["curves"]
            context = {
                **period_context,
                "group_id": group_id,
            }
            packed_frames.extend(
                [
                    _pack_frame(
                        curve_views["all"],
                        "curves",
                        daily_available="daily" in curve_views,
                        **context,
                    ),
                    _pack_frame(
                        group_result["trades"],
                        "trades",
                        **context,
                    ),
                    _pack_frame(
                        group_result["turnover"],
                        "turnover",
                        **context,
                    ),
                ]
            )
    return packed_frames


def load_backtest_results(
    factor_names: Iterable[str],
    output_root: str | Path,
    mode: str,
) -> dict[str, dict[str, Any]]:
    """加载指定因子中已经存在的一类回测结果。"""
    output_root = Path(output_root)
    results = {}
    for factor_name in factor_names:
        result_path = output_root / factor_name / RESULT_FILE_NAMES[mode]
        if not result_path.exists():
            continue
        stored_result = pd.read_parquet(result_path)
        results[factor_name] = _restore_backtest_result(stored_result)
    return results


def load_backtest_result(
    factor_name: str,
    output_root: str | Path,
    mode: str,
) -> dict[str, Any] | None:
    """加载一个因子已经存在的一类完整回测结果。"""
    return load_backtest_results([factor_name], output_root, mode).get(
        factor_name
    )


def load_backtest_checkpoint(
    factor_name: str,
    output_root: str | Path,
    mode: str,
) -> dict[str, Any]:
    """加载流水线自身生成的单因子完整回测 checkpoint。"""
    checkpoint_path = (
        Path(output_root) / factor_name / CHECKPOINT_FILE_NAMES[mode]
    )
    with checkpoint_path.open("rb") as checkpoint_file:
        return pickle.load(checkpoint_file)


def load_backtest_checkpoint_summaries(
    factor_names: Iterable[str],
    output_root: str | Path,
    mode: str,
) -> dict[str, dict[str, Any]]:
    """逐因子读取内部 checkpoint，并仅保留根目录汇总所需指标。"""
    summaries = {}
    for factor_name in factor_names:
        checkpoint = load_backtest_checkpoint(
            factor_name,
            output_root,
            mode,
        )
        summaries[factor_name] = {"metrics": checkpoint["metrics"]}
    return summaries


def load_backtest_summaries(
    factor_names: Iterable[str],
    output_root: str | Path,
    mode: str,
) -> dict[str, dict[str, Any]]:
    """只加载根目录指标汇总所需的回测指标。"""
    output_root = Path(output_root)
    summaries = {}
    for factor_name in factor_names:
        result_path = output_root / factor_name / RESULT_FILE_NAMES[mode]
        if not result_path.exists():
            continue
        stored_result = pd.read_parquet(result_path)
        summaries[factor_name] = {
            "metrics": _unpack_frame(stored_result, "metrics")
        }
    return summaries


def _restore_backtest_result(
    stored_result: pd.DataFrame,
) -> dict[str, Any]:
    """把扁平记录恢复为 backtest 引擎的周期和分组结构。"""
    rebalance_frequency = stored_result[
        "__rebalance_frequency"
    ].dropna().iloc[0]
    result = {
        "definitions": _unpack_frame(stored_result, "definitions"),
        "metrics": _unpack_frame(stored_result, "metrics"),
        "rebalance_frequency": rebalance_frequency,
        "periods": {},
    }
    period_values = stored_result["__rebalance_interval"].dropna().unique()
    for interval_value in sorted(period_values):
        interval = int(interval_value)
        actions = _unpack_frame(
            stored_result,
            "actions",
            rebalance_interval=interval,
        )
        group_rows = stored_result.loc[
            (stored_result["__record_type"] == "curves")
            & (stored_result["__rebalance_interval"] == interval)
        ]
        groups = {}
        for group_id in group_rows["__group_id"].dropna().unique():
            all_curve = _unpack_frame(
                stored_result,
                "curves",
                rebalance_interval=interval,
                group_id=group_id,
            )
            daily_available = bool(
                group_rows.loc[
                    group_rows["__group_id"] == group_id,
                    "__daily_available",
                ].iloc[0]
            )
            groups[group_id] = {
                "curves": make_curve_views(
                    all_curve.to_dict("records"),
                    daily_available,
                ),
                "trades": _unpack_frame(
                    stored_result,
                    "trades",
                    rebalance_interval=interval,
                    group_id=group_id,
                ),
                "turnover": _unpack_frame(
                    stored_result,
                    "turnover",
                    rebalance_interval=interval,
                    group_id=group_id,
                ),
            }
        result["periods"][interval] = {
            "actions": actions,
            "groups": groups,
        }
    return result


def _pack_frame(
    frame: pd.DataFrame,
    record_type: str,
    rebalance_frequency: str,
    rebalance_interval: int | None = None,
    group_id: str | None = None,
    daily_available: bool | None = None,
) -> pd.DataFrame:
    """把一张回测表、上下文和列结构编码成可合并记录。"""
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
    packed_frame = pd.concat([schema_record, records], ignore_index=True)
    packed_frame["__rebalance_frequency"] = rebalance_frequency
    packed_frame["__rebalance_interval"] = rebalance_interval
    packed_frame["__group_id"] = group_id
    packed_frame["__daily_available"] = daily_available
    return packed_frame


def _unpack_frame(
    stored_result: pd.DataFrame,
    record_type: str,
    rebalance_interval: int | None = None,
    group_id: str | None = None,
) -> pd.DataFrame:
    """按记录类型、周期和分组恢复一张回测结果表。"""
    selected = stored_result.loc[
        stored_result["__record_type"] == record_type
    ]
    if rebalance_interval is not None:
        selected = selected.loc[
            selected["__rebalance_interval"] == rebalance_interval
        ]
    if group_id is not None:
        selected = selected.loc[selected["__group_id"] == group_id]
    schema_record = selected.loc[selected["__schema"]].iloc[0]
    column_names = json.loads(schema_record["__columns"])
    return selected.loc[~selected["__schema"], column_names].reset_index(
        drop=True
    )
