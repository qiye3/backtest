"""
统一具体因子输出口径，并提供横截面风险暴露中性化。

本模块位于单因子公式和批量引擎之间。``neutralize_factor_values`` 使用逐日横截面
OLS 残差剔除数值风险暴露，``align_factor_values`` 再统一交易日、股票列和动态成员
范围；本模块不读取市场数据、不实现具体因子公式，也不填充因子缺失值。
"""

from __future__ import annotations

from collections.abc import Sequence

import numpy as np
import pandas as pd


# 用逐日横截面 OLS 残差剔除一个或多个数值风险暴露。
def neutralize_factor_values(
    factor_values: pd.DataFrame,
    exposure_panels: Sequence[pd.DataFrame],
) -> pd.DataFrame:
    """
    对因子面板执行横截面风险暴露中性化。

    输入：
    - factor_values：日期乘股票的原始因子面板。
    - exposure_panels：非空的数值暴露面板序列，例如对数市值、Beta 或行业哑变量；
      各面板会按 ``factor_values`` 的日期和股票顺序对齐。

    输出：
    - 返回与 ``factor_values`` 同索引、同列的 OLS 残差面板。
    - 某日某股票的因子或任一暴露缺失时，该位置输出 ``NaN``。

    功能和用途：
    - 每个交易日独立回归 ``factor = 截距 + 暴露项 + 残差``，以残差作为中性化因子。
    - 暴露先在当日有效股票内中心化和缩放，改善市值等量纲差异较大时的数值稳定性；
      该线性变换不改变包含截距的回归残差。
    - 所有日期通过批量矩阵乘法和伪逆一次计算，不逐股票或逐日期拟合模型。
    """
    factor_array = factor_values.to_numpy(dtype="float64", na_value=np.nan)
    exposure_array = np.stack(
        [
            exposure_panel.reindex_like(factor_values).to_numpy(
                dtype="float64",
                na_value=np.nan,
            )
            for exposure_panel in exposure_panels
        ],
        axis=2,
    )
    valid_observations = np.isfinite(factor_array) & np.isfinite(
        exposure_array
    ).all(axis=2)
    valid_counts = valid_observations.sum(axis=1, keepdims=True)

    masked_exposures = np.where(
        valid_observations[:, :, None],
        exposure_array,
        0.0,
    )
    exposure_means = np.divide(
        masked_exposures.sum(axis=1),
        valid_counts,
        out=np.zeros_like(masked_exposures[:, 0, :]),
        where=valid_counts > 0,
    )
    centered_exposures = np.where(
        valid_observations[:, :, None],
        exposure_array - exposure_means[:, None, :],
        0.0,
    )
    exposure_scales = np.sqrt(
        np.divide(
            np.square(centered_exposures).sum(axis=1),
            valid_counts,
            out=np.zeros_like(exposure_means),
            where=valid_counts > 0,
        )
    )
    scaled_exposures = np.divide(
        centered_exposures,
        exposure_scales[:, None, :],
        out=np.zeros_like(centered_exposures),
        where=exposure_scales[:, None, :] > 0,
    )

    intercept = valid_observations[:, :, None].astype("float64")
    design_matrix = np.concatenate([intercept, scaled_exposures], axis=2)
    regression_targets = np.where(valid_observations, factor_array, 0.0)
    gram_matrices = np.einsum(
        "dsi,dsj->dij",
        design_matrix,
        design_matrix,
    )
    target_products = np.einsum(
        "dsi,ds->di",
        design_matrix,
        regression_targets,
    )
    coefficients = np.einsum(
        "dij,dj->di",
        np.linalg.pinv(gram_matrices),
        target_products,
    )
    fitted_values = np.einsum(
        "dsi,di->ds",
        design_matrix,
        coefficients,
    )
    neutralized_values = np.where(
        valid_observations,
        factor_array - fitted_values,
        np.nan,
    )
    return pd.DataFrame(
        neutralized_values,
        index=factor_values.index,
        columns=factor_values.columns,
    )


# 将原始因子值对齐到标准时间和股票范围，并清空非成员位置。
def align_factor_values(
    factor_values: pd.DataFrame,
    trading_calendar: pd.DatetimeIndex,
    membership: pd.DataFrame,
) -> pd.DataFrame:
    """
    生成符合下游输入口径的标准因子面板。

    输入：
    - factor_values：具体因子计算得到的日期乘股票面板。
    - trading_calendar：``MarketData.calendar`` 提供的标准交易日日历。
    - membership：``MarketData.membership`` 提供的日期乘股票布尔成员面板；其股票列
      定义最终输出列顺序。

    输出：
    - 返回索引严格等于 ``trading_calendar``、列严格等于 ``membership.columns`` 的
      DataFrame，股票不在当日研究池时对应值为缺失。

    功能和用途：
    - 统一不同因子可能返回的日期范围和股票列范围。
    - 只执行标签对齐和成员掩码，不填补原始缺失，也不改变有效因子数值。
    """
    aligned_values = factor_values.reindex(
        index=trading_calendar,
        columns=membership.columns,
    )
    return aligned_values.where(membership)
