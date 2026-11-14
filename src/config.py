"""读取主 YAML，补全代码默认值并校验启用阶段的配置。"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from copy import deepcopy
from dataclasses import dataclass
from numbers import Real
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import yaml

from src.factors.domains import (
    DomainResearchConfig,
    domain_config_snapshot,
    load_domain_config,
)
from src.group_return.grouping import validate_ranges
from src.output_layout import factor_output_root

STAGE_NAMES = ["factors", "group_return", "strategies", "plotter", "overall_evaluation"]
CALCULATION_STAGES = ["factors", "group_return", "strategies", "overall_evaluation"]
RUN_KEYS = {*STAGE_NAMES, "max_workers", "refresh_market_data"}
ROOT_KEYS = {
    "run", "factors", "strategies", "strategy_analysis", "output",
    "market_data", "group_return", "plots", "external_returns",
}
DEFAULT_QUANTILE_EDGES = [
    [0.0, 0.01],
    [0.0, 0.1],
    [0.1, 0.2],
    [0.2, 0.3],
    [0.3, 0.4],
    [0.4, 0.5],
    [0.5, 0.6],
    [0.6, 0.7],
    [0.7, 0.8],
    [0.8, 0.9],
    [0.9, 1.0],
    [0.99, 1.0],
]
DEFAULT_GROUP_ALIASES = [
    "G0.1",
    "G1",
    "G2",
    "G3",
    "G4",
    "G5",
    "G6",
    "G7",
    "G8",
    "G9",
    "G10",
    "G9.9",
]
DEFAULT_BACKTEST_GROUP_COLORS = [
    "#006837",
    "#1A9850",
    "#66BD63",
    "#A6D96A",
    "#D9EF8B",
    "#FEE08B",
    "#FDAE61",
    "#F46D43",
    "#D73027",
    "#A50026",
]
DEFAULT_EVALUATION_GROUP_COLORS = list(reversed(DEFAULT_BACKTEST_GROUP_COLORS))
DEFAULT_PARQUET_RETENTION = {
    "factor": True,
    "group_return": False,
    "strategy_weights": True,
}
FACTOR_VARIANTS = {"raw", "industry_neutral"}
DEFAULT_GROUPING = {
    "quantile_edges": DEFAULT_QUANTILE_EDGES,
    "group_aliases": DEFAULT_GROUP_ALIASES,
    "min_stocks": 20,
    "missing_factor_policy": "exclude",
    "weighting": {
        "method": "equal",
        "field": None,
        "lag_days": 0,
    },
}
CONFIG_DEFAULTS = {
    "run": {
        "overall_evaluation": False,
        "strategies": False,
    },
    "output": {
        "save_parquet": dict(DEFAULT_PARQUET_RETENTION),
    },
    "strategy_analysis": {
        "enabled": False,
        "minimum_style_coverage": 0.95,
    },
    "group_return": {
        "factor_lag_days": 0,
        "grouping": deepcopy(DEFAULT_GROUPING),
        "target": {
            "type": "stock_return",
        },
    },
    "plots": {
        "formats": ["png"],
        "dpi": 100,
        "width": 13.0,
        "row_height": 3.4,
        "font_family": "DejaVu Sans",
        "missing_results": "error",
        "note": "",
        "legend_columns": 4,
        "distribution": {
            "enabled": True,
            "bins": 300,
            "overall_bins": 50,
            "density": True,
            "kde": True,
            "clip_quantiles": None,
            "max_points": 100_000,
        },
        "evaluation": {
            "enabled": True,
            "group_panel": "left",
            "group_colors": list(DEFAULT_EVALUATION_GROUP_COLORS),
            "ic_color": "#D06A2D",
            "rank_ic_color": "#174A73",
            "rank_ic_view": "monthly",
        },
        "overall": {
            "factor_distribution_grid": {
                "enabled": False,
                "columns": 5,
            },
            "group_return_grid": {
                "enabled": False,
                "columns": 5,
                "share_y_axis": True,
            },
        },
        "strategy": {
            "enabled": True,
        },
    },
}


@dataclass(frozen=True)
class RunConfig:
    """保存主配置以及各阶段使用的已解析目录。"""

    path: Path
    raw: dict[str, Any]
    output_root: Path
    factor_config_directory: Path | None
    factor_domains: DomainResearchConfig | None
    selected_factor_variants: tuple[str, ...] | None
    factor_result_root: Path
    factor_parquet_files: dict[str, Path] | None
    strategy_config_directory: Path | None
    external_return_path: Path | None


def save_config_snapshot(
    config: RunConfig,
    output_root: str | Path | None = None,
) -> Path:
    """把本次实际使用且已补全默认值的完整配置保存到输出根目录。"""
    snapshot_root = config.output_root if output_root is None else Path(output_root)
    snapshot_config = deepcopy(config.raw)
    if config.factor_domains is not None:
        domain_snapshot_name = "domain_config_snapshot.yaml"
        snapshot_config["factors"]["domain_config"] = domain_snapshot_name
        (snapshot_root / domain_snapshot_name).parent.mkdir(
            parents=True,
            exist_ok=True,
        )
        (snapshot_root / domain_snapshot_name).write_text(
            yaml.safe_dump(
                domain_config_snapshot(config.factor_domains),
                allow_unicode=True,
                sort_keys=False,
            ),
            encoding="utf-8",
        )
    if config.factor_parquet_files is not None:
        snapshot_config["factors"]["parquet_files"] = {
            factor_name: str(factor_path)
            for factor_name, factor_path in config.factor_parquet_files.items()
        }
    output_path = snapshot_root / "config_snapshot.yaml"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        yaml.safe_dump(snapshot_config, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    return output_path


def load_config(config_path: str | Path) -> RunConfig:
    """读取主 YAML，并只校验配置中已经启用的运行阶段。"""
    resolved_path = Path(config_path).expanduser().resolve()
    configured_values = yaml.safe_load(resolved_path.read_text(encoding="utf-8"))
    _check_keys(configured_values, {"run", "output"}, ROOT_KEYS, "root")
    raw_config = _merge_config_defaults(configured_values)
    _validate_run(raw_config["run"])
    _check_keys(
        raw_config["output"],
        {"root", "save_parquet"},
        {"root", "save_parquet"},
        "output",
    )
    parquet_settings = raw_config["output"]["save_parquet"]
    parquet_names = set(DEFAULT_PARQUET_RETENTION)
    _check_keys(
        parquet_settings,
        parquet_names,
        parquet_names,
        "output.save_parquet",
    )
    for parquet_name in parquet_names:
        _boolean(
            parquet_settings[parquet_name],
            f"output.save_parquet.{parquet_name}",
        )

    run_settings = raw_config["run"]
    if (
        any(run_settings[stage] for stage in CALCULATION_STAGES)
        or raw_config.get("strategy_analysis", {}).get("enabled", False)
    ):
        _section(raw_config, "market_data")

    external_return_path = None
    if "external_returns" in raw_config:
        external_return_config = _section(raw_config, "external_returns")
        _check_keys(
            external_return_config,
            {"path"},
            {"path"},
            "external_returns",
        )
        external_return_path = _resolve_path(
            resolved_path,
            external_return_config["path"],
        )

    output_root = _resolve_path(resolved_path, raw_config["output"]["root"])
    factor_config_directory = None
    factor_domains = None
    selected_factor_variants = None
    factor_result_root = factor_output_root(output_root)
    factor_parquet_files = None
    if "factors" in raw_config:
        factors_config = _section(raw_config, "factors")
        _check_keys(
            factors_config,
            {"config_directory"} if run_settings["factors"] else set(),
            {
                "config_directory",
                "domain_config",
                "parquet_files",
                "result_root",
                "selected_variants",
            },
            "factors",
        )
        if "parquet_files" in factors_config:
            if run_settings["factors"]:
                raise ValueError(
                    "factors.parquet_files 只允许在 run.factors=false 时使用"
                )
            if "result_root" in factors_config:
                raise ValueError(
                    "factors.parquet_files 与 factors.result_root 不能同时配置"
                )
            incompatible_keys = {
                "domain_config",
                "selected_variants",
            } & set(factors_config)
            if incompatible_keys:
                raise ValueError(
                    "直接读取 factor.parquet 时不支持以下配置: "
                    f"{sorted(incompatible_keys)}"
                )
            factor_parquet_files = _resolve_factor_parquet_files(
                resolved_path,
                factors_config["parquet_files"],
            )
        if "selected_variants" in factors_config:
            selected_factor_variants = _validate_factor_variants(
                factors_config["selected_variants"]
            )
        if run_settings["factors"]:
            factor_config_directory = _resolve_path(
                resolved_path,
                factors_config["config_directory"],
            )
        if "domain_config" in factors_config:
            domain_config_path = _resolve_path(
                resolved_path,
                factors_config["domain_config"],
            )
            factor_domains = load_domain_config(
                domain_config_path,
                _section(raw_config, "market_data"),
            )
            if selected_factor_variants != ("raw",):
                raise ValueError(
                    "factors.domain_config 要求 selected_variants 只选择 raw"
                )
        if "result_root" in factors_config:
            factor_result_root = _resolve_path(
                resolved_path,
                factors_config["result_root"],
            )
    elif run_settings["factors"]:
        _section(raw_config, "factors")
    strategy_config_directory = None
    if run_settings["strategies"]:
        strategies_config = _section(raw_config, "strategies")
        _check_keys(
            strategies_config,
            {"config_directory", "start", "end"},
            {"config_directory", "start", "end"},
            "strategies",
        )
        _date_interval(strategies_config, "strategies")
        strategy_config_directory = _resolve_path(
            resolved_path,
            strategies_config["config_directory"],
        )
    _complete_strategy_market_data_sources(
        raw_config,
        strategy_config_directory,
        output_root,
    )
    if run_settings["group_return"] or run_settings["overall_evaluation"]:
        _validate_group_return(_section(raw_config, "group_return"))
    if run_settings["plotter"] or run_settings["overall_evaluation"]:
        _validate_plots(_section(raw_config, "plots"))
    _validate_strategy_analysis(raw_config["strategy_analysis"])

    return RunConfig(
        path=resolved_path,
        raw=raw_config,
        output_root=output_root,
        factor_config_directory=factor_config_directory,
        factor_domains=factor_domains,
        selected_factor_variants=selected_factor_variants,
        factor_result_root=factor_result_root,
        factor_parquet_files=factor_parquet_files,
        strategy_config_directory=strategy_config_directory,
        external_return_path=external_return_path,
    )


def _resolve_factor_parquet_files(
    config_path: Path,
    configured_files: Any,
) -> dict[str, Path]:
    """校验因子名到原生日频 Parquet 的映射并解析文件路径。"""
    if not isinstance(configured_files, Mapping) or not configured_files:
        raise ValueError("factors.parquet_files 必须是非空映射")

    resolved_files = {}
    for factor_name, configured_path in configured_files.items():
        if not isinstance(factor_name, str) or not re.fullmatch(
            r"[A-Za-z0-9][A-Za-z0-9_.-]*",
            factor_name,
        ):
            raise ValueError(
                f"factors.parquet_files 包含无效因子名称: {factor_name!r}"
            )
        if not isinstance(configured_path, (str, Path)) or not str(
            configured_path
        ).strip():
            raise ValueError(
                f"factors.parquet_files.{factor_name} 必须是非空路径"
            )
        resolved_path = _resolve_path(config_path, configured_path)
        if resolved_path.suffix.lower() != ".parquet":
            raise ValueError(
                f"factors.parquet_files.{factor_name} 必须指向 Parquet 文件"
            )
        if not resolved_path.is_file():
            raise FileNotFoundError(
                f"因子 Parquet 不存在: {resolved_path}"
            )
        resolved_files[factor_name] = resolved_path
    return {
        factor_name: resolved_files[factor_name]
        for factor_name in sorted(resolved_files)
    }


def _validate_factor_variants(configured_variants: Any) -> tuple[str, ...]:
    """校验本次实验需要计算的因子 variant。"""
    if not isinstance(configured_variants, list) or not configured_variants:
        raise ValueError("factors.selected_variants 必须是非空列表")
    if len(configured_variants) != len(set(configured_variants)):
        raise ValueError("factors.selected_variants 不能重复")
    invalid_variants = set(configured_variants) - FACTOR_VARIANTS
    if invalid_variants:
        raise ValueError(
            "factors.selected_variants 只支持 raw 和 industry_neutral: "
            f"{sorted(invalid_variants)}"
        )
    return tuple(configured_variants)


def _complete_strategy_market_data_sources(
    raw_config: dict[str, Any],
    strategy_config_directory: Path | None,
    output_root: Path,
) -> None:
    """把策略基准权重依赖补入本次实际运行配置。"""
    run_settings = raw_config["run"]
    strategy_calculation_enabled = (
        run_settings["strategies"]
        or raw_config.get("strategy_analysis", {}).get("enabled", False)
    )
    if not strategy_calculation_enabled:
        return

    benchmark_indices = set()
    if strategy_config_directory is not None:
        for strategy_path in sorted(strategy_config_directory.glob("*.yaml")):
            strategy_config = yaml.safe_load(strategy_path.read_text(encoding="utf-8"))
            benchmark_indices.add(str(strategy_config["benchmark_index"]))
    else:
        target_root = output_root / "strategies"
        for target_path in sorted(target_root.glob("*/target_weights.parquet")):
            benchmark_values = pd.read_parquet(
                target_path,
                columns=["benchmark_index"],
            )["benchmark_index"]
            benchmark_indices.update(benchmark_values.astype(str).unique())
    if not benchmark_indices:
        return

    sources = raw_config["market_data"]["sources"]
    weight_source = sources.setdefault(
        "index_weights_monthly",
        {"codes": [], "fields": []},
    )
    weight_source["codes"] = _append_unique(
        weight_source.get("codes", []),
        benchmark_indices,
    )
    weight_source["fields"] = _append_unique(
        weight_source.get("fields", []),
        {"I_WEIGHT"},
    )
    index_price_source = sources["index_price"]
    index_price_source["codes"] = _append_unique(
        index_price_source["codes"],
        benchmark_indices,
    )


def _append_unique(values: Iterable[Any], additions: Iterable[Any]) -> list[Any]:
    """按原有顺序追加尚未配置的值。"""
    completed = list(values)
    completed.extend(value for value in sorted(additions) if value not in completed)
    return completed


def _merge_config_defaults(
    configured_values: Mapping[str, Any],
) -> dict[str, Any]:
    """递归合并因子滞后、默认分组和绘图展示设置。"""
    merged_config = deepcopy(CONFIG_DEFAULTS)
    pending_sections = [(merged_config, configured_values)]
    while pending_sections:
        target_section, configured_section = pending_sections.pop()
        for key, value in configured_section.items():
            default_value = target_section.get(key)
            if isinstance(default_value, dict) and isinstance(value, Mapping):
                pending_sections.append((default_value, value))
            else:
                target_section[key] = deepcopy(value)
    for section_name in ["group_return"]:
        configured_grouping = configured_values.get(section_name, {}).get("grouping")
        if (
            configured_grouping is not None
            and "quantile_edges" in configured_grouping
            and "group_aliases" not in configured_grouping
        ):
            merged_config[section_name]["grouping"]["group_aliases"] = None
    return merged_config


def _validate_run(settings: Mapping[str, Any]) -> None:
    """校验阶段开关、线程数和市场缓存刷新设置。"""
    _check_keys(settings, RUN_KEYS, RUN_KEYS, "run")
    for stage in STAGE_NAMES:
        _boolean(settings[stage], f"run.{stage}")
    if not any(settings[stage] for stage in STAGE_NAMES):
        raise ValueError("run 至少需要启用一个阶段")
    _positive_integer(settings["max_workers"], "run.max_workers")
    _boolean(settings["refresh_market_data"], "run.refresh_market_data")


def _validate_group_return(settings: Mapping[str, Any]) -> None:
    """校验分组收益评价的日期、采样、价格和聚合口径。"""
    expected_keys = {
        "start",
        "end",
        "universe_indices",
        "grouping",
        "sampling",
        "factor_lag_days",
        "reference_price",
        "future_return_days",
        "future_return_weeks",
        "group_return_agg",
        "time_return_agg",
        "empty_group_policy",
        "insufficient_stocks_policy",
        "missing_price_policy",
        "max_stale_days",
        "target",
    }
    required_keys = expected_keys - {
        "future_return_days",
        "future_return_weeks",
    }
    _check_keys(settings, required_keys, expected_keys, "group_return")
    _date_interval(settings, "group_return")
    _universe(settings["universe_indices"], "group_return")
    _validate_grouping(settings["grouping"], "group_return.grouping")
    _validate_sampling_schedule(
        settings["sampling"],
        "group_return.sampling",
    )
    _nonnegative_integer(
        settings["factor_lag_days"],
        "group_return.factor_lag_days",
    )
    _validate_future_return_periods(settings)
    _validate_evaluation_target(settings["target"])
    choices = {
        "reference_price": {"open", "close"},
        "group_return_agg": {"mean", "median"},
        "time_return_agg": {"mean", "median"},
        "empty_group_policy": {"nan", "error"},
        "insufficient_stocks_policy": {"nan", "error"},
    }
    for field_name, allowed_values in choices.items():
        _choice(
            settings[field_name],
            allowed_values,
            f"group_return.{field_name}",
        )
    _validate_missing_price(settings, "group_return")


def _validate_evaluation_target(settings: Mapping[str, Any]) -> None:
    """校验个股收益或相对基准超额收益评价目标。"""
    target_type = settings["type"]
    _choice(
        target_type,
        {
            "stock_return",
            "benchmark_excess_return",
            "factor_variant_excess_return",
        },
        "group_return.target.type",
    )
    expected_keys = {"type"}
    if target_type in {"benchmark_excess_return", "factor_variant_excess_return"}:
        expected_keys.add("benchmark_source")
    if target_type == "factor_variant_excess_return":
        expected_keys.update(
            {
                "industry_neutral_suffix",
                "industry_source",
                "industry_field",
            }
        )
    _check_keys(
        settings,
        expected_keys,
        expected_keys,
        "group_return.target",
    )
    if target_type in {"benchmark_excess_return", "factor_variant_excess_return"}:
        _choice(
            settings["benchmark_source"],
            {"index_price", "index_total_return"},
            "group_return.target.benchmark_source",
        )
    if target_type == "factor_variant_excess_return":
        for field_name in [
            "industry_neutral_suffix",
            "industry_source",
            "industry_field",
        ]:
            if not isinstance(settings[field_name], str) or not settings[field_name]:
                raise ValueError(f"group_return.target.{field_name} 必须是非空字符串")


def _validate_grouping(
    settings: Mapping[str, Any],
    location: str,
) -> None:
    """校验横截面分组和组内权重设置。"""
    expected_keys = {
        "quantile_edges",
        "group_aliases",
        "min_stocks",
        "missing_factor_policy",
        "weighting",
    }
    _check_keys(settings, expected_keys, expected_keys, location)
    ranges = validate_ranges(settings["quantile_edges"])
    aliases = settings["group_aliases"]
    if aliases is not None:
        if not isinstance(aliases, list):
            raise TypeError(f"{location}.group_aliases 必须是列表或 null")
        if len(aliases) != len(ranges):
            raise ValueError(f"{location}.group_aliases 必须与 quantile_edges 数量一致")
        if any(not isinstance(alias, str) or not alias.strip() for alias in aliases):
            raise ValueError(f"{location}.group_aliases 只能包含非空字符串")
        if len(aliases) != len(set(aliases)):
            raise ValueError(f"{location}.group_aliases 不能重复")
    _positive_integer(settings["min_stocks"], f"{location}.min_stocks")
    _choice(
        settings["missing_factor_policy"],
        {"exclude", "error"},
        f"{location}.missing_factor_policy",
    )

    weighting = settings["weighting"]
    _check_keys(
        weighting,
        {"method", "field", "lag_days"},
        {"method", "source", "field", "lag_days"},
        f"{location}.weighting",
    )
    _choice(
        weighting["method"],
        {"equal", "field"},
        f"{location}.weighting.method",
    )
    _nonnegative_integer(
        weighting["lag_days"],
        f"{location}.weighting.lag_days",
    )
    if weighting["method"] == "field" and (not weighting.get("source") or not weighting["field"]):
        raise ValueError(f"{location}.weighting.field 需要 source 和 field")
    if weighting["method"] == "equal" and (
        "source" in weighting or weighting["field"] is not None or weighting["lag_days"] != 0
    ):
        raise ValueError(f"{location}.weighting.equal 包含无效字段")


def _validate_sampling_schedule(
    settings: Mapping[str, Any],
    location: str,
) -> None:
    """校验分组收益评价使用的自然周采样计划。"""
    expected_keys = {
        "weekday",
        "anchor_date",
        "holiday_policy",
        "every_n_weeks",
    }
    _check_keys(settings, expected_keys, expected_keys, location)
    _choice(
        settings["weekday"],
        {"MON", "TUE", "WED", "THU", "FRI"},
        f"{location}.weekday",
    )
    _choice(
        settings["holiday_policy"],
        {"previous_trading_day", "skip"},
        f"{location}.holiday_policy",
    )
    if pd.isna(pd.Timestamp(settings["anchor_date"])):
        raise ValueError(f"{location}.anchor_date 不是有效日期")
    _positive_integer(
        settings["every_n_weeks"],
        f"{location}.every_n_weeks",
    )


def _validate_plots(settings: Mapping[str, Any]) -> None:
    """校验绘图公共设置和四类图的必要字段。"""
    expected_keys = {
        "formats",
        "dpi",
        "width",
        "row_height",
        "font_family",
        "missing_results",
        "note",
        "legend_columns",
        "distribution",
        "evaluation",
        "overall",
        "strategy",
    }
    _check_keys(settings, expected_keys, expected_keys, "plots")
    formats = settings["formats"]
    if (
        not isinstance(formats, list)
        or not formats
        or set(formats)
        - {
            "png",
            "pdf",
            "svg",
        }
    ):
        raise ValueError("plots.formats 只能包含 png、pdf、svg")
    _positive_integer(settings["dpi"], "plots.dpi")
    _positive_integer(settings["legend_columns"], "plots.legend_columns")
    for field_name in ["width", "row_height"]:
        if _finite_number(settings[field_name], f"plots.{field_name}") <= 0:
            raise ValueError(f"plots.{field_name} 必须为正数")
    _choice(
        settings["missing_results"],
        {"skip", "error"},
        "plots.missing_results",
    )
    _validate_distribution_plot(settings["distribution"])
    _validate_evaluation_plot(settings["evaluation"])
    _validate_overall_plot(settings["overall"])
    _plot_keys(settings["strategy"], {"enabled"}, "strategy")


def _validate_strategy_analysis(settings: Mapping[str, Any]) -> None:
    """校验策略风险暴露分析开关和风格覆盖率阈值。"""
    expected_keys = {"enabled", "minimum_style_coverage"}
    _check_keys(
        settings,
        expected_keys,
        expected_keys,
        "strategy_analysis",
    )
    _boolean(settings["enabled"], "strategy_analysis.enabled")
    coverage = _finite_number(
        settings["minimum_style_coverage"],
        "strategy_analysis.minimum_style_coverage",
    )
    if not 0 <= coverage <= 1:
        raise ValueError("strategy_analysis.minimum_style_coverage 必须在 [0, 1]")


def _validate_distribution_plot(settings: Mapping[str, Any]) -> None:
    """校验因子分布图设置。"""
    fields = {
        "enabled",
        "bins",
        "overall_bins",
        "density",
        "kde",
        "clip_quantiles",
        "max_points",
    }
    _plot_keys(settings, fields, "distribution")
    if not settings["enabled"]:
        return
    _positive_integer(settings["bins"], "plots.distribution.bins")
    _positive_integer(
        settings["overall_bins"],
        "plots.distribution.overall_bins",
    )
    _positive_integer(settings["max_points"], "plots.distribution.max_points")
    _boolean(settings["density"], "plots.distribution.density")
    _boolean(settings["kde"], "plots.distribution.kde")
    if settings["clip_quantiles"] is not None:
        _quantile_pair(
            settings["clip_quantiles"],
            "plots.distribution.clip_quantiles",
        )


def _validate_evaluation_plot(settings: Mapping[str, Any]) -> None:
    """校验分组收益与 IC 图设置。"""
    fields = {
        "enabled",
        "group_panel",
        "group_colors",
        "ic_color",
        "rank_ic_color",
        "rank_ic_view",
    }
    _plot_keys(settings, fields, "evaluation")
    if settings["enabled"]:
        _choice(
            settings["group_panel"],
            {"left", "right"},
            "plots.evaluation.group_panel",
        )
        _colors(settings["group_colors"], "plots.evaluation.group_colors")
        _choice(
            settings["rank_ic_view"],
            {"monthly", "sampling"},
            "plots.evaluation.rank_ic_view",
        )


def _validate_overall_plot(settings: Mapping[str, Any]) -> None:
    """校验跨因子分布与四周分组收益汇总图设置。"""
    _check_keys(
        settings,
        {"factor_distribution_grid", "group_return_grid"},
        {"factor_distribution_grid", "group_return_grid"},
        "plots.overall",
    )
    distribution_grid_settings = settings["factor_distribution_grid"]
    _plot_keys(
        distribution_grid_settings,
        {"enabled", "columns"},
        "overall.factor_distribution_grid",
    )
    if distribution_grid_settings["enabled"]:
        _positive_integer(
            distribution_grid_settings["columns"],
            "plots.overall.factor_distribution_grid.columns",
        )

    grid_settings = settings["group_return_grid"]
    _plot_keys(
        grid_settings,
        {"enabled", "columns", "share_y_axis"},
        "overall.group_return_grid",
    )
    if grid_settings["enabled"]:
        _positive_integer(
            grid_settings["columns"],
            "plots.overall.group_return_grid.columns",
        )
        _boolean(
            grid_settings["share_y_axis"],
            "plots.overall.group_return_grid.share_y_axis",
        )


def _plot_keys(
    settings: Mapping[str, Any],
    fields: set[str],
    section_name: str,
) -> None:
    """按子图开关决定是否要求其完整字段。"""
    location = f"plots.{section_name}"
    required_fields = fields if settings["enabled"] else {"enabled"}
    _check_keys(settings, required_fields, fields, location)
    _boolean(settings["enabled"], f"{location}.enabled")


def _validate_missing_price(
    settings: Mapping[str, Any],
    section_name: str,
) -> None:
    """校验缺价策略和历史收盘陈旧度。"""
    _choice(
        settings["missing_price_policy"],
        {"error", "previous_close"},
        f"{section_name}.missing_price_policy",
    )
    if settings["max_stale_days"] is not None:
        _nonnegative_integer(
            settings["max_stale_days"],
            f"{section_name}.max_stale_days",
        )


def _date_interval(settings: Mapping[str, Any], location: str) -> None:
    """检查阶段起止日期有效且顺序正确。"""
    start_date = pd.Timestamp(settings["start"])
    end_date = pd.Timestamp(settings["end"])
    if pd.isna(start_date) or pd.isna(end_date) or start_date > end_date:
        raise ValueError(f"{location} 日期区间无效")


def _positive_integer_list(value: Any, location: str) -> None:
    """检查非空、无重复的正整数列表。"""
    if not isinstance(value, list) or not value or len(value) != len(set(value)):
        raise ValueError(f"{location} 必须是非空且不重复的列表")
    for item in value:
        _positive_integer(item, location)


def _validate_future_return_periods(settings: Mapping[str, Any]) -> None:
    """校验日、周未来收益周期，至少要求配置一种周期。"""
    future_return_days = settings.get("future_return_days", [])
    future_return_weeks = settings.get("future_return_weeks", [])
    for field_name, periods in [
        ("future_return_days", future_return_days),
        ("future_return_weeks", future_return_weeks),
    ]:
        location = f"group_return.{field_name}"
        if not isinstance(periods, list) or len(periods) != len(set(periods)):
            raise ValueError(f"{location} 必须是不重复的列表")
        for period in periods:
            _positive_integer(period, location)

    if not future_return_days and not future_return_weeks:
        raise ValueError("group_return 至少需要一个未来收益周期")


def _quantile_pair(value: Any, location: str) -> None:
    """检查用于裁剪或摘要选择的单个分位区间。"""
    if not isinstance(value, list) or len(value) != 2:
        raise ValueError(f"{location} 必须是 [lower, upper]")
    lower = _finite_number(value[0], location)
    upper = _finite_number(value[1], location)
    if not 0 <= lower < upper <= 1:
        raise ValueError(f"{location} 必须满足 0 <= lower < upper <= 1")


def _section(config: Mapping[str, Any], name: str) -> Mapping[str, Any]:
    """取得启用阶段必需的映射配置。"""
    if name not in config:
        raise KeyError(f"缺少配置分区: {name}")
    section = config[name]
    if not isinstance(section, Mapping):
        raise ValueError(f"{name} 必须是映射")
    return section


def _check_keys(
    value: Any,
    required: set[str],
    allowed: set[str],
    location: str,
) -> None:
    """检查必要字段并拒绝当前代码不会消费的字段。"""
    if not isinstance(value, Mapping):
        raise ValueError(f"{location} 必须是映射")
    missing = required - value.keys()
    unknown = value.keys() - allowed
    if missing:
        raise KeyError(f"{location} 缺少字段: {sorted(missing)}")
    if unknown:
        raise KeyError(f"{location} 包含未知字段: {sorted(unknown)}")


def _choice(value: Any, choices: set[Any], location: str) -> None:
    """检查配置值属于明确支持的有限集合。"""
    if value not in choices:
        raise ValueError(f"{location} 必须是 {sorted(choices)}，实际为 {value!r}")


def _boolean(value: Any, location: str) -> None:
    """检查配置开关确实为布尔值。"""
    if not isinstance(value, bool):
        raise ValueError(f"{location} 必须是布尔值")


def _positive_integer(value: Any, location: str) -> None:
    """检查不接受布尔值的正整数。"""
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ValueError(f"{location} 必须是正整数")


def _nonnegative_integer(value: Any, location: str) -> None:
    """检查不接受布尔值的非负整数。"""
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"{location} 必须是非负整数")


def _finite_number(value: Any, location: str) -> float:
    """检查普通有限数值并返回浮点表示。"""
    is_finite_number = (
        not isinstance(value, bool) and isinstance(value, Real) and np.isfinite(value)
    )
    if not is_finite_number:
        raise ValueError(f"{location} 必须是有限数值")
    return float(value)


def _universe(value: Any, location: str) -> None:
    """检查计算阶段至少选择一个历史指数成员集合。"""
    if not isinstance(value, list) or not value:
        raise ValueError(f"{location}.universe_indices 不能为空")


def _colors(value: Any, location: str) -> None:
    """检查渐变分组至少配置两个颜色端点。"""
    if not isinstance(value, list) or len(value) < 2:
        raise ValueError(f"{location} 至少需要两个颜色")


def _resolve_path(config_path: Path, value: str | Path) -> Path:
    """相对主 YAML 所在目录解析配置路径。"""
    path = Path(value).expanduser()
    if path.is_absolute():
        return path.resolve()
    return (config_path.parent / path).resolve()
