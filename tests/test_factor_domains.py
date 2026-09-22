"""验证基础因子共享计算后的同级 domain variants。"""

from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory

import numpy as np
import pandas as pd
import yaml

from src.cli import _factor_output_sort_key
from src.data.market_data import MarketData
from src.factors import Factor, calc_factors
from src.factors.domains import (
    build_domain_masks,
    load_domain_config,
    parse_factor_output_name,
)


class _CountingFactor(Factor):
    """返回固定面板并记录公式调用次数。"""

    def __init__(self, config: dict, values: pd.DataFrame) -> None:
        super().__init__(config)
        self.values = values
        self.call_count = 0

    def calc(self, market_data: MarketData) -> pd.DataFrame:
        self.call_count += 1
        return self.values


def _source_panel(values: pd.DataFrame, field_name: str) -> pd.DataFrame:
    panel = values.copy()
    panel.columns = pd.MultiIndex.from_product(
        [[field_name], panel.columns],
        names=["field", "asset_code"],
    )
    return panel


def _index_membership_panel(
    values: pd.DataFrame,
    index_code: str,
) -> pd.DataFrame:
    panel = values.copy()
    panel.columns = pd.MultiIndex.from_tuples(
        [
            ("membership", index_code, stock_code)
            for stock_code in panel.columns
        ],
        names=["field", "index_code", "asset_code"],
    )
    return panel


def _market_data() -> MarketData:
    calendar = pd.bdate_range("2024-01-02", periods=3, name="date")
    stock_codes = pd.Index(
        ["000001.SZ", "000002.SZ", "000003.SZ", "000004.SZ"],
        name="asset_code",
    )
    membership = pd.DataFrame(True, index=calendar, columns=stock_codes)
    index_membership = pd.DataFrame(
        [
            [True, True, False, False],
            [True, True, False, False],
            [True, False, True, False],
        ],
        index=calendar,
        columns=stock_codes,
    )
    industries = pd.DataFrame(
        [["bank", "tech", "bank", "tech"]] * len(calendar),
        index=calendar,
        columns=stock_codes,
    )
    market_values = pd.DataFrame(
        [
            [1.0, 2.0, 3.0, 4.0],
            [2.0, 3.0, 4.0, 5.0],
            [3.0, 4.0, 5.0, 6.0],
        ],
        index=calendar,
        columns=stock_codes,
    )
    return MarketData(
        source_panels={
            "index_membership": _index_membership_panel(
                index_membership,
                "000906.SH",
            ),
            "industry_history": _source_panel(
                industries,
                "ind_class_code",
            ),
            "stock_valuation": _source_panel(market_values, "S_VAL_MV"),
        },
        calendar=calendar,
        membership=membership,
        benchmark_index="000906.SH",
    )


def _market_config() -> dict:
    return {
        "universe_indices": ["000906.SH", "000852.SH"],
        "sources": {
            "industry_history": {"fields": ["ind_class_code"]},
            "stock_valuation": {"fields": ["S_VAL_MV"]},
        },
    }


def _load_test_domains() -> tuple:
    configured_domains = {
        "factor_names": ["factor_a"],
        "domains": [
            {
                "name": "csi800",
                "rule": {
                    "type": "index_membership",
                    "index_code": "000906.SH",
                },
            },
            {
                "name": "bank",
                "rule": {
                    "type": "category",
                    "source": "industry_history",
                    "field": "ind_class_code",
                    "values": ["bank"],
                },
            },
            {
                "name": "large_half",
                "rule": {
                    "type": "percentile",
                    "source": "stock_valuation",
                    "field": "S_VAL_MV",
                    "range": [0.5, 1.0],
                    "transform": {
                        "method": "rolling_mean",
                        "window": 2,
                    },
                },
            },
        ],
    }
    with TemporaryDirectory() as temporary_directory:
        config_path = Path(temporary_directory) / "domains.yaml"
        config_path.write_text(
            yaml.safe_dump(configured_domains, sort_keys=False),
            encoding="utf-8",
        )
        domain_config = load_domain_config(config_path, _market_config())
    return domain_config.domains


def test_three_domain_rules_build_expected_membership() -> None:
    """指数、分类和滚动数值分位域应使用统一日频坐标。"""
    market_data = _market_data()
    masks = build_domain_masks(_load_test_domains(), market_data)

    assert masks["csi800"].iloc[0].tolist() == [True, True, False, False]
    assert masks["bank"].iloc[0].tolist() == [True, False, True, False]
    assert not masks["large_half"].iloc[0].any()
    assert masks["large_half"].iloc[1].tolist() == [False, False, True, True]


def test_domain_variants_are_siblings_and_factor_calculates_once() -> None:
    """域输出应与 raw 同级，且域内值逐点等于 raw。"""
    market_data = _market_data()
    values = pd.DataFrame(
        np.arange(12, dtype=float).reshape(3, 4),
        index=market_data.calendar,
        columns=market_data.membership.columns,
    )
    factor_config = {
        "name": "factor_a",
        "postprocess": {"cross_section": {"method": "rank"}},
        "variants": [
            {
                "suffix": "raw",
                "neutralization": {"method": "none"},
            },
            {
                "suffix": "industry_neutral",
                "neutralization": {
                    "method": "industry_demean",
                    "source": "industry_history",
                    "field": "ind_class_code",
                },
            },
        ],
    }
    selected_factor = _CountingFactor(factor_config, values)
    unselected_factor = _CountingFactor(
        {**factor_config, "name": "factor_b"},
        values,
    )
    masks = build_domain_masks(_load_test_domains(), market_data)

    panels = calc_factors(
        [selected_factor, unselected_factor],
        market_data,
        max_workers=2,
        domain_masks=masks,
        domain_factor_names=["factor_a"],
    )

    assert selected_factor.call_count == 1
    assert unselected_factor.call_count == 1
    assert list(panels) == [
        "factor_a__raw",
        "factor_a__industry_neutral",
        "factor_a__domain_csi800",
        "factor_a__domain_bank",
        "factor_a__domain_large_half",
        "factor_b__raw",
        "factor_b__industry_neutral",
    ]
    raw_values = panels["factor_a__raw"]
    domain_values = panels["factor_a__domain_bank"]
    pd.testing.assert_frame_equal(
        domain_values,
        raw_values.where(masks["bank"]),
    )


def test_factor_output_identity_uses_sibling_domain_variant() -> None:
    """域输出名称应直接关联基础因子，不嵌套 raw variant。"""
    assert parse_factor_output_name("roe_q__domain_csi800") == (
        "roe_q",
        "domain_csi800",
        "csi800",
    )
    assert parse_factor_output_name("roe_q__raw") == (
        "roe_q",
        "raw",
        "full_universe",
    )
    assert parse_factor_output_name(
        "consensus_eps__qtile_M12__domain_csi800"
    ) == (
        "consensus_eps__qtile_M12",
        "domain_csi800",
        "csi800",
    )


def test_selected_variant_avoids_unrequested_neutralization() -> None:
    """raw 实验只应产出 raw 与 domains，不计算行业中性结果。"""
    market_data = _market_data()
    values = pd.DataFrame(
        np.arange(12, dtype=float).reshape(3, 4),
        index=market_data.calendar,
        columns=market_data.membership.columns,
    )
    factor = _CountingFactor(
        {
            "name": "factor_a",
            "postprocess": {"cross_section": {"method": "rank"}},
            "variants": [
                {
                    "suffix": "raw",
                    "neutralization": {"method": "none"},
                },
                {
                    "suffix": "industry_neutral",
                    "neutralization": {
                        "method": "industry_demean",
                        "source": "industry_history",
                        "field": "ind_class_code",
                    },
                },
            ],
        },
        values,
    )
    masks = build_domain_masks(_load_test_domains(), market_data)

    panels = calc_factors(
        [factor],
        market_data,
        domain_masks=masks,
        domain_factor_names=["factor_a"],
        selected_variants=["raw"],
    )

    assert list(panels) == [
        "factor_a__raw",
        "factor_a__domain_csi800",
        "factor_a__domain_bank",
        "factor_a__domain_large_half",
    ]
    assert factor.call_count == 1


def test_factor_output_order_is_stable_for_domain_research() -> None:
    """基础因子按字母排序，同一因子内 raw 在字母序 domains 之前。"""
    unordered_names = [
        "beta__domain_small",
        "alpha__domain_value",
        "alpha__raw",
        "beta__raw",
        "alpha__domain_large",
    ]

    assert sorted(unordered_names, key=_factor_output_sort_key) == [
        "alpha__raw",
        "alpha__domain_large",
        "alpha__domain_value",
        "beta__raw",
        "beta__domain_small",
    ]
