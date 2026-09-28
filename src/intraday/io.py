"""保存分钟回测的可复现配置、明细账本和质量报告。"""

from __future__ import annotations

import json
import platform
import sys
from dataclasses import asdict
from datetime import datetime
from pathlib import Path

import pandas as pd
import yaml

from src.intraday.config import MinuteBacktestConfig
from src.intraday.data import DataQualityIssue
from src.intraday.engine import BacktestResult


def save_run_outputs(
    config: MinuteBacktestConfig,
    result: BacktestResult,
    issues: list[DataQualityIssue],
) -> Path:
    """以 run_name 建立独立结果目录，并保存全部审计文件。"""
    run_directory = config.output_root / config.run_name
    run_directory.mkdir(parents=True, exist_ok=False)
    (run_directory / "config_snapshot.yaml").write_text(
        yaml.safe_dump(config.raw, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    manifest = {
        "created_at": datetime.now().astimezone().isoformat(),
        "python": sys.version,
        "platform": platform.platform(),
        "config_path": str(config.path),
        "start_date": str(config.data.start_date.date()),
        "end_date": str(config.data.end_date.date()),
    }
    _write_json(run_directory / "manifest.json", manifest)
    _write_json(run_directory / "metrics.json", result.metrics)
    _write_json(
        run_directory / "data_quality.json",
        {"issue_count": len(issues), "issues": [asdict(issue) for issue in issues]},
    )
    for filename, frame in {
        "orders.parquet": result.orders,
        "fills.parquet": result.fills,
        "positions.parquet": result.positions,
        "nav.parquet": result.nav,
    }.items():
        frame.to_parquet(run_directory / filename, index=False)
    return run_directory


def _write_json(path: Path, values: object) -> None:
    path.write_text(
        json.dumps(values, ensure_ascii=False, indent=2, default=_json_default),
        encoding="utf-8",
    )


def _json_default(value: object) -> str:
    if isinstance(value, (pd.Timestamp, Path)):
        return str(value)
    raise TypeError(f"无法 JSON 序列化: {type(value).__name__}")
