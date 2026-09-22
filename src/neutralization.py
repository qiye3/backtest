"""横截面变换与分类中性化的共享实现。"""

from __future__ import annotations

import numpy as np
import pandas as pd


def transform_cross_sections(
    values: pd.DataFrame,
    method: str,
    min_quantile: float | None = None,
    max_quantile: float | None = None,
) -> pd.DataFrame:
    """逐日执行缩尾或百分位排名，并保留缺失位置。"""
    if method == "rank":
        return values.rank(axis=1, method="average", pct=True)
    if method != "winsorize":
        raise ValueError(f"不支持的横截面后处理方法: {method}")
    if min_quantile is None or max_quantile is None:
        raise ValueError("winsorize 必须配置 min_quantile 和 max_quantile")
    if not 0 <= min_quantile < max_quantile <= 1:
        raise ValueError("winsorize 分位点必须满足 0 <= min < max <= 1")
    lower = values.quantile(min_quantile, axis=1)
    upper = values.quantile(max_quantile, axis=1)
    return values.clip(lower=lower, upper=upper, axis=0)


def demean_by_category(
    values: pd.DataFrame,
    categories: pd.DataFrame,
    eligibility: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """逐日减去等权分类均值；缺失分类与非资格样本输出 NaN。"""
    aligned_categories = categories.reindex(index=values.index, columns=values.columns)
    eligible = (
        pd.DataFrame(True, index=values.index, columns=values.columns)
        if eligibility is None
        else eligibility.reindex(index=values.index, columns=values.columns).fillna(False)
    )
    output = pd.DataFrame(np.nan, index=values.index, columns=values.columns)
    for date in values.index:
        row = values.loc[date]
        category_row = aligned_categories.loc[date]
        valid = eligible.loc[date].astype(bool) & row.notna() & category_row.notna()
        if not valid.any():
            continue
        valid_values = row.loc[valid]
        valid_categories = category_row.loc[valid]
        category_means = valid_values.groupby(valid_categories, sort=False).transform("mean")
        output.loc[date, valid_values.index] = valid_values - category_means
    return output


def demean_return_cube_by_category(
    returns: np.ndarray,
    categories: pd.DataFrame,
    eligibility: pd.DataFrame,
) -> np.ndarray:
    """对 horizon×date×stock 收益按评价日行业做等权去均值。"""
    output = np.full_like(returns, np.nan, dtype=float)
    category_values = categories.to_numpy(dtype=object)
    eligible_values = eligibility.to_numpy(dtype=bool)
    for date_position in range(returns.shape[1]):
        category_row = category_values[date_position]
        category_present = pd.notna(category_row)
        for horizon_position in range(returns.shape[0]):
            return_row = returns[horizon_position, date_position]
            valid = eligible_values[date_position] & category_present & np.isfinite(return_row)
            if not valid.any():
                continue
            codes, _ = pd.factorize(category_row[valid], sort=False)
            counts = np.bincount(codes)
            sums = np.bincount(codes, weights=return_row[valid])
            means = sums / counts
            output[horizon_position, date_position, valid] = (
                return_row[valid] - means[codes]
            )
    return output
