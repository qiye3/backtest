"""维护可恢复流水线的运行签名、完成项和排他锁。"""

from __future__ import annotations

import fcntl
import json
import os
import shutil
from collections.abc import Callable, Iterator, Mapping, Sequence
from contextlib import contextmanager
from copy import deepcopy
from inspect import getfile
from pathlib import Path
from typing import Any

from src.config import RunConfig
from src.data.incremental import source_file_inventory
from src.data.market_data import MarketData
from src.factors.config import load_factors
from src.factors.domains import domain_config_snapshot
from src.strategy.config import load_strategies

PIPELINE_STATE_FILE = "run_state.json"
PIPELINE_STATE_VERSION = 1
PIPELINE_LOCK_FILE = ".pipeline_run.lock"


class PipelineState:
    """原子维护一次未完成运行的签名和逐项完成状态。"""

    def __init__(self, cache_root: Path, values: dict[str, Any]) -> None:
        self.cache_root = cache_root
        self.state_path = cache_root / PIPELINE_STATE_FILE
        self._values = values

    @classmethod
    def open(
        cls,
        cache_root: Path,
        signature: Mapping[str, Any],
        fresh: bool,
    ) -> PipelineState:
        """创建新状态，或在签名完全一致时恢复旧状态。"""
        if fresh and cache_root.exists():
            shutil.rmtree(cache_root)

        state_path = cache_root / PIPELINE_STATE_FILE
        if not cache_root.exists():
            cache_root.mkdir(parents=True)
            values = {
                "schema_version": PIPELINE_STATE_VERSION,
                "signature": deepcopy(dict(signature)),
                "completed": {},
            }
            state = cls(cache_root, values)
            state._write()
            return state

        if not state_path.is_file():
            raise RuntimeError(
                f"发现旧版或不完整的流水线缓存: {cache_root}；"
                "请确认后使用 --fresh 清空并重跑"
            )
        values = json.loads(state_path.read_text(encoding="utf-8"))
        if values.get("schema_version") != PIPELINE_STATE_VERSION:
            raise RuntimeError(
                f"流水线缓存版本不兼容: {cache_root}；"
                "请确认后使用 --fresh 清空并重跑"
            )
        previous_signature = values.get("signature", {})
        if previous_signature != signature:
            changed_sections = sorted(
                previous_signature.keys() ^ signature.keys()
                | {
                    section_name
                    for section_name in previous_signature.keys() & signature.keys()
                    if previous_signature[section_name] != signature[section_name]
                }
            )
            changed_text = ", ".join(changed_sections) or "unknown"
            raise RuntimeError(
                f"流水线缓存与当前运行不兼容（变化: {changed_text}）: "
                f"{cache_root}；请确认后使用 --fresh 清空并重跑"
            )
        return cls(cache_root, values)

    def completed_items(self, stage_name: str) -> set[str]:
        """返回一个阶段已经完整落盘的项目名。"""
        return set(self._values["completed"].get(stage_name, []))

    def mark_complete(self, stage_name: str, item_name: str) -> None:
        """在项目产物全部关闭后原子记录完成状态。"""
        completed_items = self.completed_items(stage_name)
        if item_name in completed_items:
            return
        completed_items.add(item_name)
        self._values["completed"][stage_name] = sorted(completed_items)
        self._write()

    def forget(self, stage_name: str, item_name: str) -> None:
        """产物缺失时撤销过期完成标记，使该项目重新计算。"""
        completed_items = self.completed_items(stage_name)
        if item_name not in completed_items:
            return
        completed_items.remove(item_name)
        self._values["completed"][stage_name] = sorted(completed_items)
        self._write()

    def pending_items(
        self,
        stage_name: str,
        item_names: Sequence[str],
        required_paths: Mapping[str, Sequence[Path]],
    ) -> tuple[str, ...]:
        """核对完成标记和必需产物，并返回仍需计算的项目。"""
        completed_items = self.completed_items(stage_name)
        for item_name in tuple(completed_items):
            paths = required_paths.get(item_name, ())
            if not paths or any(not path.is_file() for path in paths):
                self.forget(stage_name, item_name)
        valid_completed = self.completed_items(stage_name)
        pending = tuple(
            item_name for item_name in item_names if item_name not in valid_completed
        )
        reused_count = len(item_names) - len(pending)
        if reused_count:
            print(
                f"[resume] {stage_name}: reused={reused_count} pending={len(pending)}",
                flush=True,
            )
        return pending

    def _write(self) -> None:
        temporary_path = self.state_path.with_suffix(".json.tmp")
        temporary_path.write_text(
            json.dumps(self._values, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        os.replace(temporary_path, self.state_path)


def build_pipeline_signature(
    config: RunConfig,
    market_data: MarketData | None,
) -> dict[str, Any]:
    """生成可直接比较的配置、代码和输入文件清单。"""
    factors = _load_configured_instances(
        config.factor_config_directory,
        load_factors,
    )
    strategies = _load_configured_instances(
        config.strategy_config_directory,
        load_strategies,
    )
    package_roots = _package_roots(
        config=config,
        implementation_paths=[
            Path(getfile(instance.__class__)).resolve()
            for instance in [*factors, *strategies]
        ],
    )
    return {
        "config": deepcopy(config.raw),
        "resolved_paths": _resolved_paths(config),
        "domain_config": (
            domain_config_snapshot(config.factor_domains)
            if config.factor_domains is not None
            else None
        ),
        "factor_configs": [factor.config for factor in factors],
        "strategy_configs": [strategy.config for strategy in strategies],
        "framework_files": _python_inventory(Path(__file__).resolve().parents[1]),
        "package_files": [
            {
                "root": str(package_root),
                "files": _python_inventory(package_root),
            }
            for package_root in sorted(package_roots)
        ],
        "market_revision": market_data.revision if market_data is not None else None,
        "market_source_files": (
            source_file_inventory(config.path, config.raw["market_data"])
            if market_data is not None and "market_data" in config.raw
            else {}
        ),
        "external_files": _external_file_inventory(config),
    }


def _load_configured_instances(
    config_directory: Path | None,
    loader: Callable[[Path], list[Any]],
) -> list[Any]:
    """只在配置目录确有 YAML 时加载实现，供签名记录外部代码。"""
    if config_directory is None or not any(config_directory.glob("*.yaml")):
        return []
    return loader(config_directory)


def _resolved_paths(config: RunConfig) -> dict[str, Any]:
    return {
        "output_root": str(config.output_root),
        "factor_config_directory": _optional_path(config.factor_config_directory),
        "factor_result_root": str(config.factor_result_root),
        "factor_parquet_files": {
            factor_name: str(factor_path)
            for factor_name, factor_path in (config.factor_parquet_files or {}).items()
        },
        "strategy_config_directory": _optional_path(config.strategy_config_directory),
        "external_return_path": _optional_path(config.external_return_path),
    }


def _optional_path(path: Path | None) -> str | None:
    return str(path) if path is not None else None


def _external_file_inventory(config: RunConfig) -> list[dict[str, Any]]:
    input_paths = list((config.factor_parquet_files or {}).values())
    if config.factor_parquet_files is None and not config.raw["run"]["factors"]:
        input_paths.extend(config.factor_result_root.rglob("*.parquet"))
    if not config.raw["run"]["strategies"]:
        strategy_result_root = config.output_root / "strategies"
        if strategy_result_root.is_dir():
            input_paths.extend(strategy_result_root.rglob("*.parquet"))
    if config.external_return_path is not None:
        input_paths.append(config.external_return_path)
    return [_file_identity(path) for path in sorted(set(input_paths))]


def _package_roots(
    config: RunConfig,
    implementation_paths: Sequence[Path],
) -> set[Path]:
    candidate_paths = [
        path
        for path in (
            config.factor_config_directory,
            config.strategy_config_directory,
            *implementation_paths,
        )
        if path is not None
    ]
    roots = set()
    framework_root = Path(__file__).resolve().parents[1]
    for candidate_path in candidate_paths:
        for ancestor in candidate_path.resolve().parents:
            if (ancestor / "factors").is_dir() or (ancestor / "strategies").is_dir():
                if ancestor != framework_root:
                    roots.add(ancestor)
                break
    return roots


def _python_inventory(root: Path) -> list[dict[str, Any]]:
    return [
        _file_identity(source_path, root)
        for source_path in sorted(root.rglob("*.py"))
    ]


def _file_identity(path: Path, relative_root: Path | None = None) -> dict[str, Any]:
    file_stat = path.stat()
    displayed_path = path.relative_to(relative_root) if relative_root is not None else path
    return {
        "path": str(displayed_path),
        "size": file_stat.st_size,
        "mtime_ns": file_stat.st_mtime_ns,
    }


@contextmanager
def pipeline_run_lock(output_root: Path) -> Iterator[None]:
    """拒绝两个进程同时修改同一输出根的恢复状态。"""
    output_root.mkdir(parents=True, exist_ok=True)
    lock_path = output_root / PIPELINE_LOCK_FILE
    with lock_path.open("w", encoding="utf-8") as lock_file:
        try:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise RuntimeError(f"同一输出目录已有流水线运行: {output_root}") from error
        try:
            yield
        finally:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)
