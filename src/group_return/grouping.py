"""
构造因子横截面的独立分位区间。

本模块只负责截面有效值、百分位和组成员计算。分位区间允许重叠且不会
自动补齐。所有评价日期通过矩阵运算同时处理；未来收益、时间聚合和文件保存
不属于本模块。
"""

from __future__ import annotations

from collections.abc import Sequence

import numpy as np
import pandas as pd


# 校验独立分位区间并统一为浮点边界。
def validate_ranges(ranges: Sequence[Sequence[float]]) -> list[list[float]]:
    """
    校验分组使用的独立分位区间。

    输入：
    - ranges：由 ``[下界, 上界]`` 组成的非空序列。

    输出：
    - 返回保持输入顺序的浮点区间列表。

    功能和用途：
    - 确保每个区间满足 ``0 <= lower < upper <= 1`` 且没有重复项。
    - 区间可以重叠、不等宽或只覆盖部分分位范围。
    """
    if not ranges:
        raise ValueError("quantile_edges 不能为空")

    validated_ranges: list[list[float]] = []
    for pair in ranges:
        if len(pair) != 2:
            raise ValueError("每个分位区间必须包含下界和上界")
        lower, upper = map(float, pair)
        if not np.isfinite([lower, upper]).all() or not 0 <= lower < upper <= 1:
            raise ValueError("分位区间必须满足 0 <= lower < upper <= 1")
        if [lower, upper] in validated_ranges:
            raise ValueError("分位区间不能重复")
        validated_ranges.append([lower, upper])
    return validated_ranges


# 按配置顺序生成稳定的分组编号和展示信息。
def build_group_definitions(ranges: Sequence[Sequence[float]]) -> pd.DataFrame:
    """
    构造分组定义表。

    输入：
    - ranges：独立分位区间序列。

    输出：
    - 返回包含组编号、上下界、标签和名义比例的 DataFrame。

    功能和用途：
    - 为评价明细、汇总和成员表提供一致的 ``G01``、``G02`` 等稳定标识。
    """
    validated_ranges = validate_ranges(ranges)
    records = []
    for group_position, (lower, upper) in enumerate(validated_ranges, start=1):
        records.append(
            {
                "group_id": f"G{group_position:02d}",
                "quantile_lower": lower,
                "quantile_upper": upper,
                "label": f"{lower * 100:g}%–{upper * 100:g}%",
                "target_fraction": upper - lower,
            }
        )
    return pd.DataFrame(records)


# 同时完成全部评价日期的有效值筛选、百分位排名和独立分组。
def group_cross_sections(
    factor_values: pd.DataFrame,
    membership: pd.DataFrame,
    group_definitions: pd.DataFrame,
    missing_factor_policy: str,
    weight_values: pd.DataFrame | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame, np.ndarray, np.ndarray]:
    """
    对一组因子横截面执行矩阵化分组。

    输入：
    - factor_values：评价日乘股票的因子值。
    - membership：相同形状的逐日历史股票池。
    - group_definitions：``build_group_definitions`` 生成的定义表。
    - missing_factor_policy：``exclude`` 剔除缺失值，``error`` 遇到缺失即报错。
    - weight_values：可选的正字段权重矩阵；为空时使用等权。

    输出：
    - 返回有效因子值、截面百分位、组成员布尔数组和逐组逐日权重分母。
    - 组成员数组形状为 ``分组数 × 日期数 × 股票数``。

    功能和用途：
    - 百分位采用 ``(平均名次 - 0.5) / 有效股票数``，并列值同进同出。
    - 所有区间独立判断，因此自然支持重叠分组。
    """
    factor_array = factor_values.to_numpy(dtype=float)
    membership_array = membership.to_numpy(dtype=bool)
    finite_factor = np.isfinite(factor_array)
    missing_active_factor = membership_array & ~finite_factor
    if missing_factor_policy == "error" and missing_active_factor.any():
        date_position, stock_position = np.argwhere(missing_active_factor)[0]
        raise ValueError(
            "股票池内因子值缺失: "
            f"{factor_values.index[date_position].date()} "
            f"{factor_values.columns[stock_position]}"
        )

    valid_factor = membership_array & finite_factor
    masked_factor_values = factor_values.where(valid_factor)
    valid_stock_counts = valid_factor.sum(axis=1)
    factor_percentiles = masked_factor_values.rank(axis=1, method="average")
    factor_percentiles = factor_percentiles.sub(0.5).div(valid_stock_counts, axis=0)

    percentile_array = factor_percentiles.to_numpy(dtype=float)
    lower_bounds = group_definitions["quantile_lower"].to_numpy()[:, None, None]
    upper_bounds = group_definitions["quantile_upper"].to_numpy()[:, None, None]
    group_membership = (percentile_array[None, :, :] >= lower_bounds) & (
        (percentile_array[None, :, :] < upper_bounds) | (upper_bounds == 1.0)
    )

    if weight_values is None:
        base_weights = np.ones_like(factor_array)
    else:
        base_weights = weight_values.to_numpy(dtype=float)
        invalid_weights = group_membership.any(axis=0) & (
            ~np.isfinite(base_weights) | (base_weights <= 0)
        )
        if invalid_weights.any():
            date_position, stock_position = np.argwhere(invalid_weights)[0]
            raise ValueError(
                "入组股票的权重字段不是正数: "
                f"{factor_values.index[date_position].date()} "
                f"{factor_values.columns[stock_position]}"
            )

    # 未被任何区间选中的股票先置零，避免缺失权重在矩阵乘法中传播。
    base_weights = np.where(group_membership.any(axis=0), base_weights, 0.0)
    group_weight_denominators = np.einsum(
        "gds,ds->gd",
        group_membership,
        base_weights,
        optimize=True,
    )
    return (
        masked_factor_values,
        factor_percentiles,
        group_membership,
        group_weight_denominators,
    )
