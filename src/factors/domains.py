"""读取分域研究配置，并由 MarketData 构造日频域成员面板。"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

import numpy as np
import pandas as pd
import yaml

from src.data.load_data import DATA_SOURCE_SPECS
from src.data.market_data import MarketData

DOMAIN_NAME_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]*")


@dataclass(frozen=True)
class DomainDefinition:
    """保存一个域的名称及其成员判断规则。"""

    name: str
    rule: Mapping[str, Any]


@dataclass(frozen=True)
class DomainResearchConfig:
    """保存本次需要分域的基础因子和共享域定义。"""

    path: Path
    factor_names: tuple[str, ...]
    domains: tuple[DomainDefinition, ...]


def load_domain_config(
    config_path: str | Path,
    market_data_config: Mapping[str, Any],
) -> DomainResearchConfig:
    """读取 domains YAML，并在加载市场数据前校验全部来源依赖。"""
    resolved_path = Path(config_path).expanduser().resolve()
    configured_values = yaml.safe_load(resolved_path.read_text(encoding="utf-8"))
    if set(configured_values) != {"factor_names", "domains"}:
        raise ValueError("domains YAML 只能包含 factor_names 和 domains")

    factor_names = tuple(configured_values["factor_names"])
    invalid_factor_names = [
        factor_name
        for factor_name in factor_names
        if not isinstance(factor_name, str)
        or not factor_name
        or "__domain_" in factor_name
    ]
    if invalid_factor_names:
        raise ValueError(f"domain factor_names 含无效名称: {invalid_factor_names}")
    if not factor_names or len(factor_names) != len(set(factor_names)):
        raise ValueError("domain factor_names 必须非空且不能重复")

    domains = tuple(
        _validate_domain_definition(domain, market_data_config)
        for domain in configured_values["domains"]
    )
    domain_names = [domain.name for domain in domains]
    if not domains or len(domain_names) != len(set(domain_names)):
        raise ValueError("domains 必须非空且名称不能重复")

    return DomainResearchConfig(
        path=resolved_path,
        factor_names=factor_names,
        domains=domains,
    )


def build_domain_masks(
    definitions: tuple[DomainDefinition, ...],
    market_data: MarketData,
) -> dict[str, pd.DataFrame]:
    """按配置顺序构造域名到日期乘股票布尔面板的映射。"""
    masks = {}
    for definition in definitions:
        rule = definition.rule
        rule_type = rule["type"]
        if rule_type == "index_membership":
            domain_mask = market_data.get_panel(
                "index_membership",
                "membership",
                index_code=rule["index_code"],
            ).fillna(False).astype(bool)
        else:
            source_values = market_data.get_panel(
                rule["source"],
                rule["field"],
            ).reindex(
                index=market_data.calendar,
                columns=market_data.membership.columns,
            )
            if rule_type == "category":
                domain_mask = source_values.isin(rule["values"])
            else:
                domain_mask = _percentile_mask(
                    source_values,
                    market_data.membership,
                    rule,
                )

        masks[definition.name] = domain_mask.reindex(
            index=market_data.calendar,
            columns=market_data.membership.columns,
            fill_value=False,
        ) & market_data.membership
    return masks


def parse_factor_output_name(factor_name: str) -> tuple[str, str, str]:
    """把稳定输出名称拆成基础因子、variant 和研究域。"""
    domain_marker = "__domain_"
    if domain_marker in factor_name:
        base_factor_name, domain_name = factor_name.rsplit(domain_marker, 1)
        return base_factor_name, f"domain_{domain_name}", domain_name
    for variant in ("industry_neutral", "raw"):
        suffix = f"__{variant}"
        if factor_name.endswith(suffix):
            return factor_name[: -len(suffix)], variant, "full_universe"
    return factor_name, "raw", "full_universe"


def domain_config_snapshot(config: DomainResearchConfig) -> dict[str, Any]:
    """将已校验的域配置转换为可复现的 YAML 内容。"""
    return {
        "factor_names": list(config.factor_names),
        "domains": [
            {
                "name": definition.name,
                "rule": dict(definition.rule),
            }
            for definition in config.domains
        ],
    }


def _validate_domain_definition(
    configured_domain: Mapping[str, Any],
    market_data_config: Mapping[str, Any],
) -> DomainDefinition:
    """校验并规范化一个明确类型的域规则。"""
    if set(configured_domain) != {"name", "rule"}:
        raise ValueError("每个 domain 只能包含 name 和 rule")
    domain_name = configured_domain["name"]
    if not isinstance(domain_name, str) or DOMAIN_NAME_PATTERN.fullmatch(domain_name) is None:
        raise ValueError(f"domain 名称不能用于结果目录: {domain_name}")

    rule = dict(configured_domain["rule"])
    rule_type = rule["type"]
    if rule_type == "index_membership":
        _validate_index_membership_rule(rule, market_data_config)
    elif rule_type == "category":
        _validate_category_rule(rule, market_data_config)
    elif rule_type == "percentile":
        rule = _validate_percentile_rule(rule, market_data_config)
    else:
        raise ValueError(f"不支持的 domain rule.type: {rule_type}")
    return DomainDefinition(name=domain_name, rule=rule)


def _validate_index_membership_rule(
    rule: Mapping[str, Any],
    market_data_config: Mapping[str, Any],
) -> None:
    """校验指数成员域只引用已经加载的历史成员。"""
    if set(rule) != {"type", "index_code"}:
        raise ValueError("index_membership rule 只能包含 type 和 index_code")
    if rule["index_code"] not in market_data_config["universe_indices"]:
        raise ValueError(f"domain 指数未加载历史成员: {rule['index_code']}")


def _validate_category_rule(
    rule: Mapping[str, Any],
    market_data_config: Mapping[str, Any],
) -> None:
    """校验分类域的数据字段和显式分类值。"""
    if set(rule) != {"type", "source", "field", "values"}:
        raise ValueError("category rule 必须包含 type、source、field 和 values")
    _validate_panel_field(rule, market_data_config)
    if not rule["values"]:
        raise ValueError("category rule.values 不能为空")


def _validate_percentile_rule(
    rule: dict[str, Any],
    market_data_config: Mapping[str, Any],
) -> dict[str, Any]:
    """校验数值分位域，并补全滚动均值的最小观测期。"""
    allowed_keys = {"type", "source", "field", "range", "transform"}
    required_keys = {"type", "source", "field", "range"}
    if not required_keys <= rule.keys() or not rule.keys() <= allowed_keys:
        raise ValueError("percentile rule 必须包含 type、source、field 和 range")
    _validate_panel_field(rule, market_data_config)

    lower_bound, upper_bound = map(float, rule["range"])
    if not 0 <= lower_bound < upper_bound <= 1:
        raise ValueError("domain percentile range 必须满足 0 <= lower < upper <= 1")
    rule["range"] = [lower_bound, upper_bound]

    if "transform" in rule:
        transform = dict(rule["transform"])
        if not {"method", "window"} <= transform.keys() or not transform.keys() <= {
            "method",
            "window",
            "min_periods",
        }:
            raise ValueError("rolling_mean 必须配置 method 和 window")
        if transform["method"] != "rolling_mean":
            raise ValueError("domain percentile 只支持 rolling_mean")
        window = int(transform["window"])
        min_periods = int(transform.get("min_periods", window))
        if not 1 <= min_periods <= window:
            raise ValueError("rolling_mean 必须满足 1 <= min_periods <= window")
        rule["transform"] = {
            "method": "rolling_mean",
            "window": window,
            "min_periods": min_periods,
        }
    return rule


def _validate_panel_field(
    rule: Mapping[str, Any],
    market_data_config: Mapping[str, Any],
) -> None:
    """确认域规则引用的是主配置已经声明的二维面板字段。"""
    source_name = rule["source"]
    field_name = rule["field"]
    source_configs = market_data_config["sources"]
    if source_name not in source_configs:
        raise ValueError(f"domain 数据源未配置: {source_name}")
    if DATA_SOURCE_SPECS[source_name].kind == "records":
        raise ValueError(f"domain 不能直接使用明细来源: {source_name}")
    if field_name not in source_configs[source_name]["fields"]:
        raise ValueError(f"domain 字段未配置: {source_name}.{field_name}")


def _percentile_mask(
    source_values: pd.DataFrame,
    membership: pd.DataFrame,
    rule: Mapping[str, Any],
) -> pd.DataFrame:
    """按日计算有效研究股票的截面分位域。"""
    transformed_values = source_values
    if "transform" in rule:
        transform = rule["transform"]
        transformed_values = source_values.rolling(
            window=transform["window"],
            min_periods=transform["min_periods"],
        ).mean()

    finite_values = np.isfinite(transformed_values.to_numpy(dtype=float))
    valid_values = membership & finite_values
    valid_counts = valid_values.sum(axis=1)
    percentiles = transformed_values.where(valid_values).rank(
        axis=1,
        method="average",
    )
    percentiles = percentiles.sub(0.5).div(valid_counts, axis=0)

    lower_bound, upper_bound = rule["range"]
    return (percentiles >= lower_bound) & (
        (percentiles < upper_bound) | (upper_bound == 1.0)
    )
