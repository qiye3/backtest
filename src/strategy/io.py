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
        target_frames.append(target_frame)

    stored_targets = pd.concat(target_frames, ignore_index=True)
    stored_targets.insert(0, "benchmark_index", result["benchmark_index"])
    stored_targets.insert(0, "factor_name", result["factor_name"])
    strategy_directory = (
        Path(output_root) / "strategies" / result["strategy_name"]
    )
    strategy_directory.mkdir(parents=True, exist_ok=True)
    output_path = strategy_directory / TARGET_FILE_NAME
    stored_targets.to_parquet(output_path, index=False)
    return output_path


def load_strategy_targets(
    strategy_name: str,
    output_root: str | Path,
) -> dict[str, Any]:
    """从稀疏长表恢复一个策略的各调仓周期目标权重。"""
    target_path = (
        Path(output_root) / "strategies" / strategy_name / TARGET_FILE_NAME
    )
    stored_targets = pd.read_parquet(target_path)
    periods = {}
    for interval, interval_targets in stored_targets.groupby(
        "rebalance_interval",
        sort=True,
    ):
        periods[int(interval)] = interval_targets.pivot(
            index="date",
            columns="stock_code",
            values="target_weight",
        ).fillna(0.0)

    first_row = stored_targets.iloc[0]
    return {
        "strategy_name": strategy_name,
        "factor_name": first_row["factor_name"],
        "benchmark_index": first_row["benchmark_index"],
        "rebalance_frequency": first_row["rebalance_frequency"],
        "periods": periods,
    }


def find_strategy_names(output_root: str | Path) -> tuple[str, ...]:
    """列出已经保存目标权重的策略名称。"""
    strategy_root = Path(output_root) / "strategies"
    return tuple(
        target_path.parent.name
        for target_path in sorted(strategy_root.glob(f"*/{TARGET_FILE_NAME}"))
    )
