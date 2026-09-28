"""读取搜索配置并用正式因子框架生成独立时序变体。"""

from __future__ import annotations

import json
import os
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import yaml

from src.data.market_data import MarketData
from src.factors.base import FactorSearchSource
from src.factors.config import load_factor
from src.factors.io import FACTOR_FILE_NAME, load_factor_parquet
from src.factors.search_operators import (
    SUPPORTED_FREQUENCIES,
    FactorVariant,
    iter_factor_variants,
    planned_variant_names,
)
from src.factors.utils import align_factor_values
from src.pipeline_state import PipelineState, pipeline_run_lock

SEARCH_STATE_VERSION = 1
SEARCH_STAGE_NAME = "factor_search"
SEARCH_CACHE_DIRECTORY = ".pipeline_cache"
SEARCH_MANIFEST_NAME = "factor_search_manifest.csv"
CONFIG_SNAPSHOT_NAME = "config_snapshot.yaml"


@dataclass(frozen=True)
class FactorSearchInput:
    """保存一个基础因子的来源、名称和原生频率。"""

    name: str
    frequency: str
    factor_config: Path | None
    parquet: Path | None


@dataclass(frozen=True)
class FactorSearchConfig:
    """保存一次因子时序搜索所需的全部已解析路径。"""

    path: Path
    raw: dict[str, Any]
    market_config: Path
    factor_code_root: Path | None
    inputs: tuple[FactorSearchInput, ...]
    mode: str
    include_average_growth: bool
    output_root: Path


def load_factor_search_config(path: str | Path) -> FactorSearchConfig:
    """读取并验证搜索 YAML，不访问市场数据或创建输出目录。"""
    config_path = Path(path).expanduser().resolve()
    raw_config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    if not isinstance(raw_config, dict):
        raise TypeError("搜索配置必须是 YAML 映射")

    allowed_keys = {
        "market_config",
        "factor_code_root",
        "inputs",
        "operators",
        "output_root",
    }
    unknown_keys = set(raw_config) - allowed_keys
    if unknown_keys:
        raise ValueError(f"搜索配置包含未知字段: {sorted(unknown_keys)}")

    market_config = _resolve_path(config_path, raw_config["market_config"])
    if not market_config.is_file():
        raise FileNotFoundError(f"市场配置不存在: {market_config}")

    factor_code_root = None
    if raw_config.get("factor_code_root") is not None:
        factor_code_root = _resolve_path(
            config_path,
            raw_config["factor_code_root"],
        )
        if not factor_code_root.is_dir():
            raise FileNotFoundError(f"因子代码根不存在: {factor_code_root}")

    inputs = _parse_inputs(
        config_path,
        factor_code_root,
        raw_config["inputs"],
    )
    operators = raw_config.get("operators", {})
    if not isinstance(operators, dict):
        raise TypeError("operators 必须是映射")
    unknown_operator_keys = set(operators) - {
        "mode",
        "include_average_growth",
    }
    if unknown_operator_keys:
        raise ValueError(
            f"operators 包含未知字段: {sorted(unknown_operator_keys)}"
        )
    mode = str(operators.get("mode", "core"))
    if mode not in {"raw", "core", "all"}:
        raise ValueError("operators.mode 必须是 raw、core 或 all")
    include_average_growth = operators.get(
        "include_average_growth",
        mode == "all",
    )
    if not isinstance(include_average_growth, bool):
        raise TypeError("include_average_growth 必须是布尔值")
    if include_average_growth and mode != "all":
        raise ValueError("平均增长率只允许在 operators.mode=all 时启用")
    for input_config in inputs:
        if (
            input_config.parquet is not None
            and input_config.frequency == "quarterly"
            and mode != "raw"
        ):
            raise ValueError("季度 Parquet 只支持 raw；非 raw 必须使用正式 Factor YAML")

    output_root = _resolve_path(config_path, raw_config["output_root"])
    return FactorSearchConfig(
        path=config_path,
        raw=raw_config,
        market_config=market_config,
        factor_code_root=factor_code_root,
        inputs=inputs,
        mode=mode,
        include_average_growth=include_average_growth,
        output_root=output_root,
    )


def search_plan(config: FactorSearchConfig) -> dict[str, Any]:
    """生成不会写文件的搜索计划。"""
    input_plans = []
    total_variants = 0
    for input_config in config.inputs:
        variant_names = planned_variant_names(
            input_config.name,
            input_config.frequency,
            config.mode,
            config.include_average_growth,
        )
        total_variants += len(variant_names)
        input_plans.append(
            {
                "name": input_config.name,
                "frequency": input_config.frequency,
                "source": _input_source_text(input_config),
                "variants": len(variant_names),
                "first_variants": list(variant_names[:8]),
            }
        )
    return {
        "status": "dry_run",
        "mode": config.mode,
        "include_average_growth": config.include_average_growth,
        "output_root": str(config.output_root),
        "inputs": input_plans,
        "total_variants": total_variants,
    }


def run_factor_search(
    config: FactorSearchConfig,
    fresh: bool = False,
) -> dict[str, Any]:
    """计算全部配置变体并发布标准 Parquet 与清单。"""
    _enable_factor_imports(config.factor_code_root)
    market_data = MarketData.from_yaml(config.market_config, refresh=False)
    signature = _search_signature(config, market_data)

    with pipeline_run_lock(config.output_root):
        cache_root = config.output_root / SEARCH_CACHE_DIRECTORY
        is_new_run = fresh or not cache_root.exists()
        if is_new_run:
            _clear_previous_outputs(config.output_root)
        state = PipelineState.open(cache_root, signature, fresh=fresh)
        manifest_rows = _load_manifest_rows(config.output_root)
        generated_count = 0
        reused_count = 0

        for input_config in config.inputs:
            factor_source = _load_factor_source(
                input_config,
                config.factor_code_root,
                market_data,
            )
            _validate_source_frequency(input_config, factor_source)
            aligned_values = align_factor_values(
                factor_source.values,
                market_data.calendar,
                market_data.membership,
            )
            variant_names = planned_variant_names(
                input_config.name,
                input_config.frequency,
                config.mode,
                config.include_average_growth,
            )
            required_paths = {
                variant_name: (_factor_output_path(config.output_root, variant_name),)
                for variant_name in variant_names
            }
            pending_names = set(
                state.pending_items(
                    SEARCH_STAGE_NAME,
                    variant_names,
                    required_paths,
                )
            )
            reused_count += len(variant_names) - len(pending_names)
            if not pending_names:
                continue

            for variant in iter_factor_variants(
                base_name=input_config.name,
                factor_values=aligned_values,
                source_frequency=input_config.frequency,
                mode=config.mode,
                include_average_growth=config.include_average_growth,
                trading_calendar=market_data.calendar,
                quarterly_events=factor_source.quarterly_events,
            ):
                if variant.name not in pending_names:
                    continue
                output_values = variant.values.where(market_data.membership)
                output_path = _write_factor_atomic(
                    config.output_root,
                    variant.name,
                    output_values,
                )
                manifest_rows[variant.name] = _manifest_row(
                    input_config,
                    variant,
                    output_values,
                    output_path,
                )
                _write_manifest(config.output_root, manifest_rows)
                state.mark_complete(SEARCH_STAGE_NAME, variant.name)
                generated_count += 1
                print(f"[factor-search] generated {variant.name}", flush=True)

        _write_config_snapshot(config)
        shutil.rmtree(cache_root)

    return {
        "status": "complete",
        "mode": config.mode,
        "inputs": len(config.inputs),
        "generated": generated_count,
        "reused": reused_count,
        "total_variants": len(manifest_rows),
        "manifest": str(config.output_root / SEARCH_MANIFEST_NAME),
        "output_root": str(config.output_root),
    }


def _parse_inputs(
    config_path: Path,
    factor_code_root: Path | None,
    raw_inputs: object,
) -> tuple[FactorSearchInput, ...]:
    if not isinstance(raw_inputs, list) or not raw_inputs:
        raise ValueError("inputs 必须是非空列表")
    parsed_inputs = []
    for raw_input in raw_inputs:
        if not isinstance(raw_input, dict):
            raise TypeError("inputs 中每一项必须是映射")
        unknown_keys = set(raw_input) - {
            "name",
            "frequency",
            "factor_config",
            "parquet",
        }
        if unknown_keys:
            raise ValueError(f"因子输入包含未知字段: {sorted(unknown_keys)}")
        factor_config_value = raw_input.get("factor_config")
        parquet_value = raw_input.get("parquet")
        if (factor_config_value is None) == (parquet_value is None):
            raise ValueError("每个输入必须且只能配置 factor_config 或 parquet")
        frequency = str(raw_input["frequency"])
        if frequency not in SUPPORTED_FREQUENCIES:
            raise ValueError(f"未知因子频率: {frequency}")

        factor_config = None
        parquet = None
        if factor_config_value is not None:
            if factor_code_root is None:
                raise ValueError("使用 factor_config 时必须配置 factor_code_root")
            factor_config = _resolve_from_root(
                factor_code_root,
                factor_config_value,
            )
            if not factor_config.is_file():
                raise FileNotFoundError(f"Factor YAML 不存在: {factor_config}")
            yaml_name = _factor_name_from_yaml(factor_config)
            configured_name = raw_input.get("name")
            if configured_name is not None and str(configured_name) != yaml_name:
                raise ValueError(
                    f"输入 name 与 Factor YAML 不一致: {configured_name} != {yaml_name}"
                )
            factor_name = yaml_name
        else:
            parquet = _resolve_path(config_path, parquet_value)
            if not parquet.is_file():
                raise FileNotFoundError(f"因子 Parquet 不存在: {parquet}")
            if raw_input.get("name") is None:
                raise ValueError("Parquet 输入必须显式配置 name")
            factor_name = str(raw_input["name"])
        parsed_inputs.append(
            FactorSearchInput(
                name=factor_name,
                frequency=frequency,
                factor_config=factor_config,
                parquet=parquet,
            )
        )

    input_names = [input_config.name for input_config in parsed_inputs]
    if len(input_names) != len(set(input_names)):
        raise ValueError("inputs 中的基础因子 name 必须唯一")
    return tuple(parsed_inputs)


def _load_factor_source(
    input_config: FactorSearchInput,
    factor_code_root: Path | None,
    market_data: MarketData,
) -> FactorSearchSource:
    if input_config.factor_config is not None:
        if factor_code_root is None:
            raise ValueError("Factor YAML 输入缺少 factor_code_root")
        factor = load_factor(input_config.factor_config)
        return factor.factor_search_source(market_data)
    if input_config.parquet is None:
        raise ValueError("因子输入没有可读取的来源")
    return FactorSearchSource(values=load_factor_parquet(input_config.parquet))


def _validate_source_frequency(
    input_config: FactorSearchInput,
    factor_source: FactorSearchSource,
) -> None:
    if (
        factor_source.frequency is not None
        and factor_source.frequency != input_config.frequency
    ):
        raise ValueError(
            f"因子 {input_config.name} 的配置频率为 {input_config.frequency}，"
            f"实现声明为 {factor_source.frequency}"
        )


def _search_signature(
    config: FactorSearchConfig,
    market_data: MarketData,
) -> dict[str, Any]:
    factor_files = []
    for input_config in config.inputs:
        source_path = input_config.factor_config or input_config.parquet
        if source_path is not None:
            factor_files.append(_file_identity(source_path))
    code_inventory = []
    if config.factor_code_root is not None:
        code_inventory = [
            _file_identity(path, config.factor_code_root)
            for path in sorted(config.factor_code_root.rglob("*.py"))
        ]
    return {
        "search_state_version": SEARCH_STATE_VERSION,
        "config": config.raw,
        "resolved_paths": {
            "market_config": str(config.market_config),
            "factor_code_root": (
                str(config.factor_code_root)
                if config.factor_code_root is not None
                else None
            ),
            "output_root": str(config.output_root),
        },
        "market_revision": market_data.revision,
        "input_files": factor_files,
        "factor_code_files": code_inventory,
    }


def _manifest_row(
    input_config: FactorSearchInput,
    variant: FactorVariant,
    factor_values: pd.DataFrame,
    output_path: Path,
) -> dict[str, Any]:
    finite_count = int(np.isfinite(factor_values.to_numpy()).sum())
    total_count = int(factor_values.shape[0] * factor_values.shape[1])
    return {
        "factor_name": variant.name,
        "base_factor": input_config.name,
        "source_frequency": input_config.frequency,
        "target_frequency": variant.target_frequency,
        "operator_set": variant.operator.operator_set,
        "operator_id": variant.operator.operator_id,
        "source_type": (
            "factor_config"
            if input_config.factor_config is not None
            else "parquet"
        ),
        "source_path": _input_source_text(input_config),
        "rows": len(factor_values),
        "columns": len(factor_values.columns),
        "start_date": factor_values.index.min().strftime("%Y-%m-%d"),
        "end_date": factor_values.index.max().strftime("%Y-%m-%d"),
        "non_null_rate": finite_count / total_count if total_count else 0.0,
        "factor_path": str(output_path),
    }


def _write_factor_atomic(
    output_root: Path,
    factor_name: str,
    factor_values: pd.DataFrame,
) -> Path:
    output_path = _factor_output_path(output_root, factor_name)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = output_path.with_suffix(".parquet.tmp")
    factor_values.to_parquet(temporary_path)
    os.replace(temporary_path, output_path)
    return output_path


def _write_manifest(
    output_root: Path,
    manifest_rows: dict[str, dict[str, Any]],
) -> None:
    manifest_path = output_root / SEARCH_MANIFEST_NAME
    temporary_path = manifest_path.with_suffix(".csv.tmp")
    manifest = pd.DataFrame(
        [manifest_rows[name] for name in sorted(manifest_rows)]
    )
    manifest.to_csv(temporary_path, index=False, encoding="utf-8-sig")
    os.replace(temporary_path, manifest_path)


def _load_manifest_rows(output_root: Path) -> dict[str, dict[str, Any]]:
    manifest_path = output_root / SEARCH_MANIFEST_NAME
    if not manifest_path.is_file():
        return {}
    manifest = pd.read_csv(manifest_path)
    return {
        str(row["factor_name"]): row.to_dict()
        for _, row in manifest.iterrows()
    }


def _write_config_snapshot(config: FactorSearchConfig) -> None:
    output_path = config.output_root / CONFIG_SNAPSHOT_NAME
    temporary_path = output_path.with_suffix(".yaml.tmp")
    temporary_path.write_text(
        yaml.safe_dump(config.raw, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    os.replace(temporary_path, output_path)


def _clear_previous_outputs(output_root: Path) -> None:
    factors_root = output_root / "factors"
    if factors_root.exists():
        shutil.rmtree(factors_root)
    for file_name in (SEARCH_MANIFEST_NAME, CONFIG_SNAPSHOT_NAME):
        (output_root / file_name).unlink(missing_ok=True)


def _factor_output_path(output_root: Path, factor_name: str) -> Path:
    return output_root / "factors" / factor_name / FACTOR_FILE_NAME


def _enable_factor_imports(factor_code_root: Path | None) -> None:
    if factor_code_root is not None and str(factor_code_root) not in sys.path:
        sys.path.insert(0, str(factor_code_root))


def _resolve_path(config_path: Path, value: object) -> Path:
    path = Path(str(value)).expanduser()
    if not path.is_absolute():
        path = config_path.parent / path
    return path.resolve()


def _resolve_from_root(root: Path, value: object) -> Path:
    path = Path(str(value)).expanduser()
    if not path.is_absolute():
        path = root / path
    return path.resolve()


def _factor_name_from_yaml(path: Path) -> str:
    factor_config = yaml.safe_load(path.read_text(encoding="utf-8"))
    return str(factor_config["name"])


def _input_source_text(input_config: FactorSearchInput) -> str:
    source_path = input_config.factor_config or input_config.parquet
    return str(source_path)


def _file_identity(
    path: Path,
    relative_root: Path | None = None,
) -> dict[str, Any]:
    file_stat = path.stat()
    displayed_path = path.relative_to(relative_root) if relative_root else path
    return {
        "path": str(displayed_path),
        "size": file_stat.st_size,
        "mtime_ns": file_stat.st_mtime_ns,
    }


def report_json(report: dict[str, Any]) -> str:
    """以稳定中文 JSON 输出 CLI 运行报告。"""
    return json.dumps(report, ensure_ascii=False)
