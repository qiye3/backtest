"""保存分钟回测的可复现配置、明细账本和质量报告。"""

from __future__ import annotations

import importlib.metadata
import json
import os
import platform
import subprocess
import sys
import tempfile
from collections.abc import Mapping
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd
import yaml

from src.intraday.config import MinuteBacktestConfig
from src.intraday.data import DataQualityIssue
from src.intraday.engine import BacktestResult

TRACKED_PACKAGES = [
    "factor-backtest",
    "matplotlib",
    "numpy",
    "openpyxl",
    "pandas",
    "pyarrow",
    "py7zr",
    "PyYAML",
    "scipy",
]


def save_run_outputs(
    config: MinuteBacktestConfig,
    result: BacktestResult,
    issues: list[DataQualityIssue],
    source_snapshot: Mapping[str, Any] | None = None,
) -> Path:
    """完整写入临时目录后再发布，避免留下看似成功的半成品。"""
    config.output_root.mkdir(parents=True, exist_ok=True)
    run_directory = config.output_root / config.run_name
    if run_directory.exists():
        raise FileExistsError(f"运行结果目录已存在: {run_directory}")

    with tempfile.TemporaryDirectory(
        prefix=f".{config.run_name}.",
        dir=config.output_root,
    ) as temporary_directory:
        temporary_path = Path(temporary_directory)
        _write_run_files(
            temporary_path,
            config,
            result,
            issues,
            source_snapshot,
        )
        os.replace(temporary_path, run_directory)
    return run_directory


def _write_run_files(
    run_directory: Path,
    config: MinuteBacktestConfig,
    result: BacktestResult,
    issues: list[DataQualityIssue],
    source_snapshot: Mapping[str, Any] | None,
) -> None:
    (run_directory / "config_snapshot.yaml").write_text(
        yaml.safe_dump(config.raw, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    manifest = {
        "status": "complete",
        "created_at": datetime.now().astimezone().isoformat(),
        "python": sys.version,
        "platform": platform.platform(),
        "packages": _package_versions(),
        "git": _git_identity(config.path),
        "config_path": str(config.path),
        "config_file": _file_identity(config.path),
        "target_input": _target_input_identity(config),
        "start_date": str(config.data.start_date.date()),
        "end_date": str(config.data.end_date.date()),
        "data_snapshot": dict(source_snapshot or {}),
    }
    _write_json(run_directory / "manifest.json", manifest)
    _write_json(run_directory / "metrics.json", result.metrics)
    _write_json(
        run_directory / "data_quality.json",
        {"issue_count": len(issues), "issues": [asdict(issue) for issue in issues]},
    )
    frames = {
        "orders.parquet": result.orders,
        "fills.parquet": result.fills,
        "positions.parquet": result.positions,
        "nav.parquet": result.nav,
        "daily_nav.parquet": _daily_nav(result.nav),
    }
    for filename, frame in frames.items():
        frame.to_parquet(run_directory / filename, index=False)


def _daily_nav(nav: pd.DataFrame) -> pd.DataFrame:
    daily = nav.copy()
    daily["date"] = daily["timestamp"].dt.tz_localize(None).dt.normalize()
    daily = daily.groupby("date", sort=True).last().reset_index()
    daily["return"] = daily["nav"].pct_change()
    return daily


def _package_versions() -> dict[str, str]:
    versions: dict[str, str] = {}
    for package_name in TRACKED_PACKAGES:
        try:
            versions[package_name] = importlib.metadata.version(package_name)
        except importlib.metadata.PackageNotFoundError:
            versions[package_name] = "not-installed"
    return versions


def _git_identity(config_path: Path) -> dict[str, object]:
    repository_root = _find_repository_root(config_path.parent)
    if repository_root is None:
        return {"repository_root": None, "commit": None, "dirty": None}
    commit = subprocess.run(
        ["git", "-C", str(repository_root), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    status = subprocess.run(
        ["git", "-C", str(repository_root), "status", "--porcelain"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    return {
        "repository_root": str(repository_root),
        "commit": commit,
        "dirty": bool(status.strip()),
    }


def _find_repository_root(start: Path) -> Path | None:
    for candidate in (start, *start.parents):
        if (candidate / ".git").exists():
            return candidate
    return None


def _target_input_identity(config: MinuteBacktestConfig) -> dict[str, object]:
    if config.targets.mode == "file":
        assert config.targets.path is not None
        return {
            "mode": "file",
            "file": _file_identity(config.targets.path),
        }
    assert config.targets.universe_path is not None
    assert config.targets.implementation is not None
    return {
        "mode": "daily_minute_strategy",
        "universe_file": _file_identity(config.targets.universe_path),
        "implementation": {
            "module": config.targets.implementation.module,
            "class": config.targets.implementation.class_name,
            "params": config.targets.implementation.params,
        },
    }


def _file_identity(path: Path) -> dict[str, object]:
    stat = path.stat()
    return {
        "path": str(path.resolve()),
        "size": stat.st_size,
        "mtime_ns": stat.st_mtime_ns,
    }


def _write_json(path: Path, values: object) -> None:
    path.write_text(
        json.dumps(values, ensure_ascii=False, indent=2, default=_json_default),
        encoding="utf-8",
    )


def _json_default(value: object) -> str:
    if isinstance(value, (pd.Timestamp, Path)):
        return str(value)
    raise TypeError(f"无法 JSON 序列化: {type(value).__name__}")
