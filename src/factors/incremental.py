"""按市场版本和因子历史依赖更新已发布的标准因子面板。"""

from __future__ import annotations

import json
import os
import shutil
from dataclasses import dataclass
from inspect import getfile
from pathlib import Path
from typing import Any, Mapping, Sequence

import pandas as pd

from src.config import RunConfig
from src.data.incremental import MarketUpdateResult
from src.data.market_data import MarketData
from src.factors.base import Factor, HistoryRequirement
from src.factors.config import load_factors
from src.factors.domains import build_domain_masks, domain_config_snapshot
from src.factors.engine import _factor_output_names, iter_factor_panels
from src.factors.io import FACTOR_FILE_NAME, load_factor_panel, save_factor_panels
from src.output_layout import factor_output_root

FACTOR_UPDATE_STATE = ".state/factor_update.json"


@dataclass(frozen=True)
class FactorUpdateResult:
    """记录一个实验内各基础因子的更新方式。"""

    output_root: Path
    reused: tuple[str, ...]
    incremental: tuple[str, ...]
    rebuilt: tuple[str, ...]


def update_factor_results(
    config: RunConfig,
    market_update: MarketUpdateResult,
    rebuild: bool = False,
    dry_run: bool = False,
) -> FactorUpdateResult:
    """更新一份实验配置的 factor.parquet，并在成功后发布统一状态。"""
    if config.factor_parquet_files is not None:
        raise ValueError(
            "显式 factor.parquet 是只读输入，不能由 update_factor_cache 更新"
        )
    factors = load_factors(config.factor_config_directory)
    published_root = factor_output_root(config.output_root)
    state_path = config.output_root / FACTOR_UPDATE_STATE
    previous_state = _read_state(state_path)
    code_files = _project_code_inventory()
    code_changed = previous_state.get("code_files") != code_files
    domain_changed = previous_state.get("domain_config") != (
        domain_config_snapshot(config.factor_domains)
        if config.factor_domains is not None
        else None
    )
    variants_changed = previous_state.get("selected_variants") != list(
        config.selected_factor_variants or ()
    )
    previous_market_revision = int(previous_state.get("market_revision", -1))
    skipped_market_revision = previous_market_revision < market_update.revision_before
    factor_states = previous_state.get("factors", {})
    update_modes = {
        factor.name: _factor_update_mode(
            factor=factor,
            output_names=_factor_output_names(
                factor,
                _domain_names(config, factor),
                config.selected_factor_variants,
            ),
            previous_state=factor_states.get(factor.name),
            published_root=published_root,
            market_update=market_update,
            force_rebuild=(
                rebuild
                or code_changed
                or domain_changed
                or variants_changed
                or skipped_market_revision
            ),
        )
        for factor in factors
    }
    result = _factor_update_result(config.output_root, update_modes)
    if dry_run:
        return result

    market_data = market_update.market_data
    if market_data is None:
        raise ValueError("正式因子更新需要已构造的 MarketData")

    staging_root = config.output_root / ".factor_update_staging"
    if staging_root.exists():
        shutil.rmtree(staging_root)
    staging_factor_root = factor_output_root(staging_root)
    factors_by_name = {factor.name: factor for factor in factors}
    rebuilt_factors = [factors_by_name[name] for name in result.rebuilt]
    incremental_factors = [factors_by_name[name] for name in result.incremental]

    if rebuilt_factors:
        _calculate_to_staging(
            factors=rebuilt_factors,
            config=config,
            market_data=market_data,
            staging_root=staging_factor_root,
        )
    if incremental_factors:
        history_start = min(
            _history_start_date(
                factor.history_requirement(),
                market_data.calendar,
                market_update.changed_from,
            )
            for factor in incremental_factors
        )
        tail_market_data = market_data.window(history_start)
        _calculate_to_staging(
            factors=incremental_factors,
            config=config,
            market_data=tail_market_data,
            staging_root=staging_factor_root,
        )
        _merge_incremental_outputs(
            factors=incremental_factors,
            config=config,
            changed_from=market_update.changed_from,
            published_root=published_root,
            staging_root=staging_factor_root,
        )

    expected_outputs = _expected_output_names(factors, config)
    _publish_staged_factors(staging_factor_root, published_root)
    _remove_retired_outputs(
        previous_state=previous_state,
        expected_outputs=expected_outputs,
        published_root=published_root,
    )
    state = _build_factor_state(
        config=config,
        factors=factors,
        market_revision=market_update.revision_after,
        code_files=code_files,
    )
    _write_json_atomic(state_path, state)
    if staging_root.exists():
        shutil.rmtree(staging_root)
    return result


def validate_factor_market_revision(
    config: RunConfig,
    market_data: MarketData,
) -> None:
    """复用因子时拒绝市场版本不一致的实验结果。"""
    if market_data.revision == 0:
        return
    state_path = _factor_state_path(config)
    factor_state = _read_state(state_path)
    factor_revision = int(factor_state.get("market_revision", -1))
    if factor_revision != market_data.revision:
        raise ValueError(
            "因子结果对应的市场数据版本已过期，请先运行 update_factor_cache"
        )


def record_factor_update_state(
    config: RunConfig,
    market_data: MarketData,
) -> None:
    """记录普通全链路已成功发布的因子与市场版本。"""
    factors = load_factors(config.factor_config_directory)
    state = _build_factor_state(config, factors, market_data.revision)
    _write_json_atomic(_factor_state_path(config), state)


def _factor_update_mode(
    factor: Factor,
    output_names: Sequence[str],
    previous_state: Mapping[str, Any] | None,
    published_root: Path,
    market_update: MarketUpdateResult,
    force_rebuild: bool,
) -> str:
    """根据已有结果、代码配置和市场失效范围选择更新方式。"""
    outputs_exist = all(
        (published_root / output_name / FACTOR_FILE_NAME).is_file()
        for output_name in output_names
    )
    config_matches = (
        previous_state is not None
        and previous_state.get("config") == factor.config
        and previous_state.get("outputs") == list(output_names)
        and previous_state.get("implementation_file")
        == _factor_implementation_identity(factor)
    )
    if force_rebuild or not outputs_exist or not config_matches:
        return "rebuilt"
    if market_update.revision_after == market_update.revision_before:
        return "reused"
    if factor.history_requirement().full_history:
        return "rebuilt"
    return "incremental"


def _calculate_to_staging(
    factors: Sequence[Factor],
    config: RunConfig,
    market_data: MarketData,
    staging_root: Path,
) -> None:
    domain_masks = None
    domain_factor_names: Sequence[str] = ()
    if config.factor_domains is not None:
        domain_masks = build_domain_masks(config.factor_domains.domains, market_data)
        domain_factor_names = config.factor_domains.factor_names
    for factor_name, factor_panel in iter_factor_panels(
        factors=factors,
        market_data=market_data,
        max_workers=config.raw["run"]["max_workers"],
        domain_masks=domain_masks,
        domain_factor_names=domain_factor_names,
        selected_variants=config.selected_factor_variants,
    ):
        save_factor_panels({factor_name: factor_panel}, staging_root)


def _merge_incremental_outputs(
    factors: Sequence[Factor],
    config: RunConfig,
    changed_from: pd.Timestamp | None,
    published_root: Path,
    staging_root: Path,
) -> None:
    if changed_from is None:
        return
    for factor in factors:
        for output_name in _factor_output_names(
            factor,
            _domain_names(config, factor),
            config.selected_factor_variants,
        ):
            previous_panel = load_factor_panel(output_name, published_root)
            updated_panel = load_factor_panel(output_name, staging_root)
            previous_prefix = previous_panel.loc[previous_panel.index < changed_from]
            previous_prefix = previous_prefix.reindex(columns=updated_panel.columns)
            merged_panel = pd.concat(
                [
                    previous_prefix,
                    updated_panel.loc[updated_panel.index >= changed_from],
                ]
            )
            save_factor_panels({output_name: merged_panel}, staging_root)


def _history_start_date(
    requirement: HistoryRequirement,
    calendar: pd.DatetimeIndex,
    changed_from: pd.Timestamp | None,
) -> pd.Timestamp:
    if changed_from is None:
        return calendar[0]
    changed_position = int(calendar.searchsorted(changed_from, side="left"))
    changed_position = min(changed_position, len(calendar) - 1)
    first_position = max(0, changed_position - requirement.trading_days)
    trading_start = calendar[first_position]
    calendar_start = changed_from - pd.Timedelta(days=requirement.calendar_days)
    return min(trading_start, calendar_start)


def _domain_names(config: RunConfig, factor: Factor) -> tuple[str, ...]:
    if config.factor_domains is None:
        return ()
    if factor.name not in config.factor_domains.factor_names:
        return ()
    return tuple(domain.name for domain in config.factor_domains.domains)


def _expected_output_names(
    factors: Sequence[Factor],
    config: RunConfig,
) -> set[str]:
    return {
        output_name
        for factor in factors
        for output_name in _factor_output_names(
            factor,
            _domain_names(config, factor),
            config.selected_factor_variants,
        )
    }


def _publish_staged_factors(staging_root: Path, published_root: Path) -> None:
    for source_path in sorted(staging_root.glob(f"*/{FACTOR_FILE_NAME}")):
        output_path = published_root / source_path.parent.name / FACTOR_FILE_NAME
        output_path.parent.mkdir(parents=True, exist_ok=True)
        os.replace(source_path, output_path)


def _remove_retired_outputs(
    previous_state: Mapping[str, Any],
    expected_outputs: set[str],
    published_root: Path,
) -> None:
    previous_outputs = {
        output_name
        for factor_state in previous_state.get("factors", {}).values()
        for output_name in factor_state["outputs"]
    }
    for retired_output in previous_outputs - expected_outputs:
        retired_path = published_root / retired_output / FACTOR_FILE_NAME
        retired_path.unlink(missing_ok=True)


def _factor_update_result(
    output_root: Path,
    update_modes: Mapping[str, str],
) -> FactorUpdateResult:
    return FactorUpdateResult(
        output_root=output_root,
        reused=tuple(
            sorted(
                name for name, mode in update_modes.items() if mode == "reused"
            )
        ),
        incremental=tuple(
            sorted(name for name, mode in update_modes.items() if mode == "incremental")
        ),
        rebuilt=tuple(
            sorted(name for name, mode in update_modes.items() if mode == "rebuilt")
        ),
    )


def _factor_state_path(config: RunConfig) -> Path:
    if config.factor_result_root == factor_output_root(config.output_root):
        return config.output_root / FACTOR_UPDATE_STATE
    return config.factor_result_root.parent / FACTOR_UPDATE_STATE


def _build_factor_state(
    config: RunConfig,
    factors: Sequence[Factor],
    market_revision: int,
    code_files: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """生成独立更新和普通全链路共用的因子版本快照。"""
    return {
        "market_revision": market_revision,
        "code_files": code_files or _project_code_inventory(),
        "domain_config": (
            domain_config_snapshot(config.factor_domains)
            if config.factor_domains is not None
            else None
        ),
        "selected_variants": list(config.selected_factor_variants or ()),
        "factors": {
            factor.name: {
                "config": factor.config,
                "implementation_file": _factor_implementation_identity(factor),
                "outputs": _factor_output_names(
                    factor,
                    _domain_names(config, factor),
                    config.selected_factor_variants,
                ),
                "history_requirement": _history_requirement_snapshot(
                    factor.history_requirement()
                ),
            }
            for factor in factors
        },
    }


def _factor_implementation_identity(factor: Factor) -> dict[str, Any]:
    """记录 YAML 动态导入类的实际 Python 文件属性。"""
    implementation_path = Path(getfile(factor.__class__)).resolve()
    implementation_stat = implementation_path.stat()
    return {
        "path": str(implementation_path),
        "size": implementation_stat.st_size,
        "mtime_ns": implementation_stat.st_mtime_ns,
    }


def _project_code_inventory() -> list[dict[str, Any]]:
    project_root = Path(__file__).resolve().parents[2]
    code_roots = [project_root / "src" / "factors", project_root / "factors"]
    return [
        {
            "path": str(source_path.relative_to(project_root)),
            "size": source_path.stat().st_size,
            "mtime_ns": source_path.stat().st_mtime_ns,
        }
        for code_root in code_roots
        for source_path in sorted(code_root.rglob("*.py"))
    ]


def _history_requirement_snapshot(
    requirement: HistoryRequirement,
) -> dict[str, Any]:
    return {
        "trading_days": requirement.trading_days,
        "calendar_days": requirement.calendar_days,
        "full_history": requirement.full_history,
    }


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
