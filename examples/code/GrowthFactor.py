"""
提供一个可由 YAML 动态导入的季度成长因子示例。

本模块位于示例 Factor 实现层。``GrowthFactor`` 从 ``MarketData`` 读取财务指标及其
报告期，先构造季度乘股票矩阵并计算历史统计量，再映射回日频 SUE 面板；输出仍交给
Factors 引擎统一对齐和应用股票池，本模块不读取 YAML、不扫描配置，也不保存结果。
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from src.data.market_data import MarketData
from src.factors.base import Factor


class GrowthFactor(Factor):
    """
    计算财务指标相对历史自然季度的标准化偏离。

    输入：
    - 构造时接收完整 Factor 配置；``params`` 必须包含 ``value_field`` 和
      ``history_quarters``。
    - 计算时接收包含 ``financial_indicators`` 来源的 ``MarketData``。

    输出：
    - ``calc`` 返回索引为交易日、列为股票代码的 SUE 因子面板。

    功能和用途：
    - 展示项目外部 Factor 类如何继承公共基类、读取面板并由 YAML 动态导入。
    - 当前示例配置使用单季度归母净利润同比，并与此前八个自然季度比较。
    """

    # 对每只股票的财务报告历史计算日频 SUE 面板。
    def calc(self, market_data: MarketData) -> pd.DataFrame:
        """
        计算配置财务字段的季度 SUE。

        输入：
        - market_data：提供财务指标值和 ``REPORT_PERIOD`` 日频 PIT 面板的数据对象。
        - ``self.config["params"]``：包含字段名和要求的历史季度数。

        输出：
        - 返回与财务指标面板同索引、同股票列的浮点 DataFrame。

        功能和用途：
        - 使用季度乘股票矩阵统一计算严格相邻自然季度的历史均值和标准差。
        - 这里只实现公式；最终交易日、股票列和历史成员资格由批量引擎统一处理。
        """
        factor_params = self.config["params"]
        value_field = factor_params["value_field"]
        history_quarters = factor_params["history_quarters"]
        financial_values = market_data.get_panel(
            "financial_indicators",
            value_field,
        )
        report_periods = market_data.get_panel(
            "financial_indicators",
            "REPORT_PERIOD",
        )

        quarterly_values = _build_quarterly_value_panel(
            financial_values,
            report_periods,
        )
        prior_quarter_values = quarterly_values.shift(1)
        rolling_history = prior_quarter_values.rolling(
            window=history_quarters,
            min_periods=history_quarters,
        )
        quarterly_history_means = rolling_history.mean()
        quarterly_history_standard_deviations = rolling_history.std(ddof=1)
        (
            daily_history_means,
            daily_history_standard_deviations,
        ) = _map_quarter_statistics_to_daily(
            quarterly_history_means,
            quarterly_history_standard_deviations,
            report_periods,
        )

        financial_value_array = financial_values.to_numpy(
            dtype="float64",
            na_value=np.nan,
        )
        valid_factor_values = (
            np.isfinite(financial_value_array)
            & np.isfinite(daily_history_means)
            & np.isfinite(daily_history_standard_deviations)
            & (daily_history_standard_deviations > 0)
        )
        factor_value_array = np.full(
            financial_value_array.shape,
            np.nan,
            dtype="float64",
        )
        np.divide(
            financial_value_array - daily_history_means,
            daily_history_standard_deviations,
            out=factor_value_array,
            where=valid_factor_values,
        )
        return pd.DataFrame(
            factor_value_array,
            index=financial_values.index,
            columns=financial_values.columns,
        )


# 从日频 PIT 状态提取每个报告季度最终已知的股票值。
def _build_quarterly_value_panel(
    financial_values: pd.DataFrame,
    report_periods: pd.DataFrame,
) -> pd.DataFrame:
    """
    构造报告季度乘股票的财务值矩阵。

    输入：
    - financial_values：日期乘股票的财务字段 PIT 面板。
    - report_periods：与财务值完全对齐的当前报告期面板。

    输出：
    - 返回索引为连续自然季度、列为股票代码的浮点 DataFrame。
    - 股票缺少某个自然季度或该季度最终状态为空时，对应位置为 ``NaN``。

    功能和用途：
    - 使用矩阵运算识别报告期或财务值发生变化的日频状态，只保留稀疏事件记录。
    - 同一股票同一报告季度存在修订时保留最后状态，使它成为后续季度当时已知的历史值。
    - 连续季度索引确保 rolling 窗口表示自然季度，而不是已有记录的行数。
    """
    previous_values = financial_values.shift()
    values_both_missing = financial_values.isna() & previous_values.isna()
    value_changed = financial_values.ne(previous_values) & ~values_both_missing

    previous_report_periods = report_periods.shift()
    periods_both_missing = report_periods.isna() & previous_report_periods.isna()
    report_period_changed = (
        report_periods.ne(previous_report_periods) & ~periods_both_missing
    )
    state_changed = report_periods.notna() & (
        report_period_changed | value_changed
    )

    event_date_positions, event_stock_positions = np.nonzero(
        state_changed.to_numpy()
    )
    report_period_array = report_periods.to_numpy(dtype="datetime64[ns]")
    financial_value_array = financial_values.to_numpy(
        dtype="float64",
        na_value=np.nan,
    )
    event_records = pd.DataFrame(
        {
            "report_quarter": pd.DatetimeIndex(
                report_period_array[
                    event_date_positions,
                    event_stock_positions,
                ]
            ).to_period("Q"),
            "stock_code": financial_values.columns.take(
                event_stock_positions
            ),
            "value": financial_value_array[
                event_date_positions,
                event_stock_positions,
            ],
        }
    )
    latest_quarter_records = event_records.drop_duplicates(
        ["report_quarter", "stock_code"],
        keep="last",
    )
    quarter_index = pd.period_range(
        latest_quarter_records["report_quarter"].min(),
        latest_quarter_records["report_quarter"].max(),
        freq="Q",
        name="report_quarter",
    )
    return latest_quarter_records.pivot(
        index="report_quarter",
        columns="stock_code",
        values="value",
    ).reindex(
        index=quarter_index,
        columns=financial_values.columns,
    )


# 按每日当前报告季度一次性取回历史均值和标准差。
def _map_quarter_statistics_to_daily(
    quarterly_means: pd.DataFrame,
    quarterly_standard_deviations: pd.DataFrame,
    report_periods: pd.DataFrame,
) -> tuple[np.ndarray, np.ndarray]:
    """
    将季度历史统计量映射到日频股票面板。

    输入：
    - quarterly_means：连续自然季度乘股票的历史均值矩阵。
    - quarterly_standard_deviations：与均值矩阵对齐的历史标准差矩阵。
    - report_periods：日期乘股票的当前报告期面板，股票列顺序必须与两个季度矩阵一致。

    输出：
    - 返回 ``(日频历史均值, 日频历史标准差)``，两个浮点数组均与报告期面板同形状。
    - 没有报告期的位置在两个数组中均为 ``NaN``。

    功能和用途：
    - 把报告期月份编码为季度行位置，再用 NumPy 高级索引一次性选择所有日股数据。
    - 均值与标准差共享同一位置矩阵，避免重复转换大型日频报告期面板。
    - 该映射不逐股票调用 reindex，使季度 rolling 结果可高效恢复为日频状态。
    """
    report_months = report_periods.to_numpy(dtype="datetime64[M]")
    valid_report_periods = ~np.isnat(report_months)
    report_quarter_ordinals = np.floor_divide(
        report_months.astype("int64"),
        3,
    )
    first_quarter_ordinal = quarterly_means.index[0].ordinal
    report_quarter_positions = (
        report_quarter_ordinals - first_quarter_ordinal
    )
    safe_quarter_positions = np.where(
        valid_report_periods,
        report_quarter_positions,
        0,
    )
    stock_positions = np.arange(report_periods.shape[1])
    daily_means = quarterly_means.to_numpy(dtype="float64")[
        safe_quarter_positions,
        stock_positions,
    ]
    daily_standard_deviations = quarterly_standard_deviations.to_numpy(
        dtype="float64"
    )[
        safe_quarter_positions,
        stock_positions,
    ]
    daily_means[~valid_report_periods] = np.nan
    daily_standard_deviations[~valid_report_periods] = np.nan
    return daily_means, daily_standard_deviations
