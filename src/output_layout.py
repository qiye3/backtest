"""定义正式输出目录的固定命名空间。"""

from __future__ import annotations

from pathlib import Path

FACTOR_OUTPUT_DIRECTORY = "factors"
STRATEGY_OUTPUT_DIRECTORY = "strategies"
SUMMARY_OUTPUT_DIRECTORY = "summaries"


def factor_output_root(output_root: str | Path) -> Path:
    """返回因子结果命名空间。"""
    return Path(output_root) / FACTOR_OUTPUT_DIRECTORY


def strategy_output_root(output_root: str | Path) -> Path:
    """返回策略结果命名空间。"""
    return Path(output_root) / STRATEGY_OUTPUT_DIRECTORY


def summary_output_root(output_root: str | Path) -> Path:
    """返回汇总表命名空间。"""
    return Path(output_root) / SUMMARY_OUTPUT_DIRECTORY
