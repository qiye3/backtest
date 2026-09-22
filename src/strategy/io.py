"""保存和恢复策略目标权重，并生成策略绩效汇总表。"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

import pandas as pd

TARGET_FILE_NAME = "target_weights.parquet"


def save_strategy_targets(
    result: Mapping[str, Any],
    output_root: str | Path,
) -> Path:
    """把一个策略的全部调仓周期保存为一张稀疏长表。"""
    target_frames = []
    stored_diagnostics = result.get("selection_diagnostics", {})
    for interval, target_weights in result["periods"].items():
        nonzero_weights = target_weights.where(target_weights != 0).stack()
        target_frame = nonzero_weights.rename("target_weight").reset_index()
        target_frame.columns = ["date", "stock_code", "target_weight"]
        target_frame.insert(0, "rebalance_interval", interval)
        target_frame.insert(
            0,
            "rebalance_frequency",
            result["rebalance_frequency"],
        )
        diagnostics = stored_diagnostics.get(interval)
        if diagnostics is None:
            diagnostics = pd.DataFrame(
                {
                    "date": target_weights.index,
                    "selected_count": target_weights.ne(0).sum(axis=1).to_numpy(),
                }
            )
        target_frame = target_frame.merge(diagnostics, on="date", how="left")
        missing_diagnostics = diagnostics[
            ~diagnostics["date"].isin(target_frame["date"])
        ].copy()
        if not missing_diagnostics.empty:
            missing_diagnostics.insert(0, "target_weight", 0.0)
            missing_diagnostics.insert(0, "stock_code", pd.NA)
            missing_diagnostics.insert(0, "rebalance_interval", interval)
            missing_diagnostics.insert(
                0,
                "rebalance_frequency",
                result["rebalance_frequency"],
            )
            target_frame = pd.concat(
                [target_frame, missing_diagnostics],
                ignore_index=True,
            )
        target_frames.append(target_frame)

    stored_targets = pd.concat(target_frames, ignore_index=True)
    stored_targets.insert(0, "benchmark_index", result["benchmark_index"])
    stored_targets.insert(0, "factor_name", result["factor_name"])
    strategy_directory = Path(output_root) / result["strategy_name"]
    strategy_directory.mkdir(parents=True, exist_ok=True)
    output_path = strategy_directory / TARGET_FILE_NAME
    stored_targets.to_parquet(output_path, index=False)
    return output_path


def load_strategy_targets(
    strategy_name: str,
    output_root: str | Path,
) -> dict[str, Any]:
    """从稀疏长表恢复一个策略的各调仓周期目标权重。"""
    target_path = Path(output_root) / strategy_name / TARGET_FILE_NAME
    stored_targets = pd.read_parquet(target_path)
    periods = {}
    for interval, interval_targets in stored_targets.groupby(
        "rebalance_interval",
        sort=True,
    ):
        holding_targets = interval_targets[interval_targets["stock_code"].notna()]
        periods[int(interval)] = holding_targets.pivot(
            index="date",
            columns="stock_code",
            values="target_weight",
        ).fillna(0.0)

    first_row = stored_targets.iloc[0]
    selection_diagnostics = {}
    diagnostic_columns = [
        column_name
        for column_name in [
            "candidate_count",
            "requested_top_n",
            "selected_count",
            "status",
        ]
        if column_name in stored_targets
    ]
    if diagnostic_columns:
        for interval, interval_targets in stored_targets.groupby(
            "rebalance_interval",
            sort=True,
        ):
            selection_diagnostics[int(interval)] = (
                interval_targets[["date", *diagnostic_columns]]
                .drop_duplicates("date")
                .reset_index(drop=True)
            )
    return {
        "strategy_name": strategy_name,
        "factor_name": first_row["factor_name"],
        "benchmark_index": first_row["benchmark_index"],
        "rebalance_frequency": first_row["rebalance_frequency"],
        "periods": periods,
        "selection_diagnostics": selection_diagnostics,
    }


def find_strategy_names(output_root: str | Path) -> tuple[str, ...]:
    """列出已经保存目标权重的策略名称。"""
    return tuple(
        target_path.parent.name
        for target_path in sorted(
            Path(output_root).glob(f"*/{TARGET_FILE_NAME}")
        )
    )
