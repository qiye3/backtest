"""扫描原始文件变化，并为独立更新任务维护共享市场版本。"""

from __future__ import annotations

import fcntl
import json
import os
import re
from contextlib import contextmanager
from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator, Mapping, Sequence

import pandas as pd

from src.config import RunConfig
from src.data.cache import resolve_market_cache_directory
from src.data.load_data import DATA_SOURCE_SPECS, _select_source_files
from src.data.market_data import MARKET_UPDATE_STATE, MarketData

COLLECTION_SOURCE_KEYS = {"fields", "codes", "forecast_year_offsets"}


@dataclass(frozen=True)
class MarketUpdateResult:
    """保存一次市场缓存同步的版本、失效起点和变化来源。"""

    market_data: MarketData | None
    revision_before: int
    revision_after: int
    changed_sources: tuple[str, ...]
    changed_from: pd.Timestamp | None
    mode: str


@dataclass(frozen=True)
class _MarketUpdatePlan:
    """保存在文件锁内生成的一次市场更新决策。"""

    previous_revision: int
    current_files: dict[str, list[dict[str, Any]]]
    config_signature: dict[str, Any]
    changed_sources: tuple[str, ...]
    changed_from: pd.Timestamp | None
    must_update: bool
    force_rebuild: bool


def update_market_data(
    configs: Sequence[RunConfig],
    rebuild: bool = False,
    dry_run: bool = False,
) -> MarketUpdateResult:
    """合并多份实验的数据需求，并在原始文件变化时发布新市场版本。"""
    market_config = merge_market_data_configs(configs)
    config_path = configs[0].path
    cache_root = resolve_market_cache_directory(
        config_path,
        market_config["cache_root"],
    )
    state_path = cache_root / MARKET_UPDATE_STATE

    if dry_run:
        update_plan = _plan_market_update(
            config_path=config_path,
            cache_root=cache_root,
            market_config=market_config,
            rebuild=rebuild,
        )
        return MarketUpdateResult(
            market_data=None,
            revision_before=update_plan.previous_revision,
            revision_after=(
                update_plan.previous_revision + int(update_plan.must_update)
            ),
            changed_sources=update_plan.changed_sources,
            changed_from=update_plan.changed_from,
            mode=_market_update_mode(update_plan),
        )

    cache_root.mkdir(parents=True, exist_ok=True)
    with _exclusive_cache_lock(cache_root):
        # 等锁期间另一个任务可能已发布新版本，因此必须在锁内重新决策。
        update_plan = _plan_market_update(
            config_path=config_path,
            cache_root=cache_root,
            market_config=market_config,
            rebuild=rebuild,
        )
        market_data = MarketData.from_yaml(
            config_path,
            refresh=update_plan.force_rebuild,
            market_data_config=market_config,
            refresh_sources=update_plan.changed_sources,
            incremental_from=update_plan.changed_from,
        )
        current_revision = update_plan.previous_revision + int(
            update_plan.must_update
        )
        state = {
            "revision": current_revision,
            "config": update_plan.config_signature,
            "source_files": update_plan.current_files,
            "changed_from": (
                update_plan.changed_from.strftime("%Y-%m-%d")
                if update_plan.changed_from is not None
                else None
            ),
        }
        _write_json_atomic(state_path, state)
        market_data.revision = current_revision

    return MarketUpdateResult(
        market_data=market_data,
        revision_before=update_plan.previous_revision,
        revision_after=current_revision,
        changed_sources=update_plan.changed_sources,
        changed_from=update_plan.changed_from,
        mode=_market_update_mode(update_plan),
    )


def _plan_market_update(
    config_path: Path,
    cache_root: Path,
    market_config: Mapping[str, Any],
    rebuild: bool,
) -> _MarketUpdatePlan:
    """比较当前原始文件、配置和已发布状态。"""
    previous_state = _read_state(cache_root / MARKET_UPDATE_STATE)
    current_files = _source_file_inventory(config_path, market_config)
    config_signature = _market_config_signature(config_path, market_config)
    changed_sources = tuple(
        _changed_sources(
            previous_state.get("source_files", {}),
            current_files,
        )
    )
    if {"index_price", "index_membership"} & set(changed_sources):
        # 交易日历或股票池改变会同时改变所有来源的行列空间。
        changed_sources = tuple(
            sorted(
                {
                    *changed_sources,
                    *market_config["sources"],
                    "index_membership",
                }
            )
        )
    config_changed = previous_state.get("config") != config_signature
    cache_missing = not (cache_root / "index_price.parquet").exists()
    force_rebuild = rebuild or cache_missing or config_changed
    must_update = force_rebuild or bool(changed_sources)
    changed_from = _changed_from_date(
        previous_state=previous_state,
        current_files=current_files,
        changed_sources=changed_sources,
        market_config=market_config,
        force_full=rebuild or cache_missing,
        config_signature=config_signature,
    )
    return _MarketUpdatePlan(
        previous_revision=int(previous_state.get("revision", 0)),
        current_files=current_files,
        config_signature=config_signature,
        changed_sources=changed_sources,
        changed_from=changed_from,
        must_update=must_update,
        force_rebuild=force_rebuild,
    )


def _market_update_mode(update_plan: _MarketUpdatePlan) -> str:
    """区分无变化复用、变化来源更新和整套重建。"""
    if not update_plan.must_update:
        return "reuse"
    if update_plan.force_rebuild:
        return "rebuild"
    return "incremental"


def merge_market_data_configs(configs: Sequence[RunConfig]) -> dict[str, Any]:
    """按共享缓存口径合并多份运行配置的日期、字段和代码需求。"""
    market_configs = [config.raw["market_data"] for config in configs]
    merged = deepcopy(market_configs[0])
    merged["start_date"] = min(item["start_date"] for item in market_configs)
    merged["end_date"] = max(item["end_date"] for item in market_configs)
    merged_sources: dict[str, dict[str, Any]] = {}
    for market_config in market_configs:
        if market_config["cache_root"] != merged["cache_root"]:
            raise ValueError("一次增量更新的配置必须共享 market_data.cache_root")
        for source_name, source_config in market_config["sources"].items():
            if source_name not in merged_sources:
                merged_sources[source_name] = deepcopy(source_config)
                continue
            _merge_source_config(merged_sources[source_name], source_config)
    merged["sources"] = merged_sources
    return merged


def _merge_source_config(
    target: dict[str, Any],
    incoming: Mapping[str, Any],
) -> None:
    """合并来源集合字段，同时拒绝筛选条件等语义冲突。"""
    semantic_keys = (target.keys() | incoming.keys()) - COLLECTION_SOURCE_KEYS
    conflicts = [
        key for key in semantic_keys if target.get(key) != incoming.get(key)
    ]
    if conflicts:
        raise ValueError(f"共享来源配置不一致: {', '.join(sorted(conflicts))}")
    for key in COLLECTION_SOURCE_KEYS:
        if key in target or key in incoming:
            target[key] = list(
                dict.fromkeys([*target.get(key, []), *incoming.get(key, [])])
            )


def _source_file_inventory(
    config_path: Path,
    market_config: Mapping[str, Any],
) -> dict[str, list[dict[str, Any]]]:
    """记录本次配置实际依赖的原始文件，不读取文件内容。"""
    data_root = Path(market_config["source_root"]).expanduser()
    if not data_root.is_absolute():
        data_root = config_path.parent / data_root
    data_root = data_root.resolve()
    start_date = pd.Timestamp(market_config["start_date"])
    end_date = pd.Timestamp(market_config["end_date"])
    inventory = {}
    for source_name, source_config in market_config["sources"].items():
        source_files = _select_source_files(
            data_root=data_root,
            source_spec=DATA_SOURCE_SPECS[source_name],
            start_date=start_date,
            end_date=end_date,
            index_codes=tuple(source_config.get("codes", ())),
        )
        inventory[source_name] = [
            _file_identity(source_path, data_root) for source_path, _ in source_files
        ]
    membership_files = [
        data_root / "index" / "members" / f"{index_code}.csv"
        for index_code in market_config["universe_indices"]
    ]
    inventory["index_membership"] = [
        _file_identity(source_path, data_root) for source_path in membership_files
    ]
    return inventory


def source_file_inventory(
    config_path: Path,
    market_config: Mapping[str, Any],
) -> dict[str, list[dict[str, Any]]]:
    """公开流水线恢复所需的实际原始文件清单。"""
    return _source_file_inventory(config_path, market_config)


def _file_identity(source_path: Path, data_root: Path) -> dict[str, Any]:
    file_stat = source_path.stat()
    return {
        "path": str(source_path.relative_to(data_root)),
        "size": file_stat.st_size,
        "mtime_ns": file_stat.st_mtime_ns,
    }


def _changed_sources(
    previous_files: Mapping[str, Any],
    current_files: Mapping[str, Any],
) -> list[str]:
    """按来源列出文件新增、删除或属性变化。"""
    source_names = sorted(previous_files.keys() | current_files.keys())
    return [
        source_name
        for source_name in source_names
        if previous_files.get(source_name) != current_files.get(source_name)
    ]


def _changed_from_date(
    previous_state: Mapping[str, Any],
    current_files: Mapping[str, list[dict[str, Any]]],
    changed_sources: Sequence[str],
    market_config: Mapping[str, Any],
    force_full: bool,
    config_signature: Mapping[str, Any],
) -> pd.Timestamp | None:
    """用变化年度给出保守失效起点；无法定位的来源从配置起点失效。"""
    if force_full:
        return pd.Timestamp(market_config["start_date"])
    previous_config = previous_state.get("config")
    config_change_date = _config_change_date(previous_config, config_signature)
    if not changed_sources:
        return config_change_date

    previous_files = previous_state.get("source_files", {})
    changed_dates = []
    for source_name in changed_sources:
        previous_by_path = {
            file_info["path"]: file_info
            for file_info in previous_files.get(source_name, [])
        }
        current_by_path = {
            file_info["path"]: file_info
            for file_info in current_files.get(source_name, [])
        }
        changed_paths = [
            file_path
            for file_path in previous_by_path.keys() | current_by_path.keys()
            if previous_by_path.get(file_path) != current_by_path.get(file_path)
        ]
        source_years = [
            year
            for file_path in changed_paths
            if (year := _file_year(file_path)) is not None
        ]
        if not source_years or source_name == "index_membership":
            changed_dates.append(pd.Timestamp(market_config["start_date"]))
        else:
            changed_dates.append(pd.Timestamp(year=min(source_years), month=1, day=1))
    if config_change_date is not None:
        changed_dates.append(config_change_date)
    return min(changed_dates)


def _config_change_date(
    previous_config: Mapping[str, Any] | None,
    current_config: Mapping[str, Any],
) -> pd.Timestamp | None:
    """结束日单向扩展只失效新增尾部，其余配置变化失效完整区间。"""
    if previous_config is None:
        return pd.Timestamp(current_config["start_date"])
    if previous_config == current_config:
        return None

    previous_without_end = dict(previous_config)
    current_without_end = dict(current_config)
    previous_end = pd.Timestamp(previous_without_end.pop("end_date"))
    current_end = pd.Timestamp(current_without_end.pop("end_date"))
    if previous_without_end == current_without_end and current_end > previous_end:
        return previous_end + pd.Timedelta(days=1)
    return pd.Timestamp(current_config["start_date"])


def _file_year(relative_path: str) -> int | None:
    match = re.search(r"(\d{4})(?=\.csv$)", relative_path)
    return int(match.group(1)) if match is not None else None


def _market_config_signature(
    config_path: Path,
    market_config: Mapping[str, Any],
) -> dict[str, Any]:
    """生成可直接比较且路径已解析的市场配置快照。"""
    signature = deepcopy(dict(market_config))
    for path_name in ("source_root", "cache_root"):
        configured_path = Path(signature[path_name]).expanduser()
        if not configured_path.is_absolute():
            configured_path = config_path.parent / configured_path
        signature[path_name] = str(configured_path.resolve())
    return signature


def _read_state(state_path: Path) -> dict[str, Any]:
    if not state_path.exists():
        return {}
    return json.loads(state_path.read_text(encoding="utf-8"))


def _write_json_atomic(output_path: Path, values: Mapping[str, Any]) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = output_path.with_suffix(output_path.suffix + ".tmp")
    temporary_path.write_text(
        json.dumps(values, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    os.replace(temporary_path, output_path)


@contextmanager
def _exclusive_cache_lock(cache_root: Path) -> Iterator[None]:
    """避免两个定时任务同时发布同一共享市场缓存。"""
    lock_path = cache_root / ".update.lock"
    with lock_path.open("w", encoding="utf-8") as lock_file:
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)
