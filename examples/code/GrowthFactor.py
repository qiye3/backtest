"""
提供一个可由 YAML 动态导入的季度成长因子示例。

本模块位于示例 Factor 实现层。``GrowthFactor`` 从 ``MarketData`` 读取财务指标及其
报告期，``_calc_stock_sue`` 在单只股票当时已知的季度历史上计算 SUE；输出仍交给
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
        - 对每只股票独立识别报告状态变化，再使用严格相邻的自然季度历史计算 SUE。
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

        stock_factor_values = {
            stock_code: _calc_stock_sue(
                values=financial_values[stock_code],
                report_periods=report_periods[stock_code],
                history_quarters=history_quarters,
            )
            for stock_code in financial_values.columns
        }
        return pd.DataFrame(
            stock_factor_values,
            index=financial_values.index,
        )


# 根据单只股票当时已知的季度记录更新并保持 SUE 状态。
def _calc_stock_sue(
    values: pd.Series,
    report_periods: pd.Series,
    history_quarters: int,
) -> pd.Series:
    """
    计算单只股票的日频季度 SUE。

    输入：
    - values：财务字段的日频 PIT 状态，索引为交易日。
    - report_periods：与 ``values`` 对齐的当前报告期状态。
    - history_quarters：当前季度必须比较的此前自然季度数量。

    输出：
    - 返回与输入同索引的浮点 Series；历史不完整、当前值缺失或历史标准差为零的
      报告状态为 ``NaN``。

    功能和用途：
    - 新报告出现或当前报告数值修订时，更新当时已知的报告期数值映射。
    - 当前值只与严格相邻的前 N 个自然季度比较，同报告修订不会被重复计为历史季度。
    - 每次事件算出的值保持到下一次报告状态变化，供日频回测直接使用。
    """
    previous_values = values.shift()
    values_both_missing = values.isna() & previous_values.isna()
    value_changed = values.ne(previous_values) & ~values_both_missing

    previous_report_periods = report_periods.shift()
    periods_both_missing = report_periods.isna() & previous_report_periods.isna()
    report_period_changed = (
        report_periods.ne(previous_report_periods) & ~periods_both_missing
    )
    state_changed = report_periods.notna() & (
        report_period_changed | value_changed
    )

    known_quarter_values: dict[pd.Period, float] = {}
    event_factor_values: list[float] = []
    for event_date in report_periods.index[state_changed]:
        current_quarter = pd.Timestamp(
            report_periods.at[event_date]
        ).to_period("Q")
        current_value = values.at[event_date]
        known_quarter_values[current_quarter] = current_value
        history_values = pd.Series(
            [
                known_quarter_values.get(
                    current_quarter - quarter_offset,
                    np.nan,
                )
                for quarter_offset in range(history_quarters, 0, -1)
            ],
            dtype="float64",
        )
        history_standard_deviation = history_values.std(ddof=1)

        if (
            pd.isna(current_value)
            or history_values.isna().any()
            or history_standard_deviation == 0
        ):
            factor_value = np.nan
        else:
            factor_value = (
                current_value - history_values.mean()
            ) / history_standard_deviation
        event_factor_values.append(factor_value)

    factor_values_by_state = pd.Series(
        event_factor_values,
        index=range(1, len(event_factor_values) + 1),
        dtype="float64",
    )
    state_ids = state_changed.cumsum()
    daily_factor_values = state_ids.map(factor_values_by_state)
    return daily_factor_values.where(report_periods.notna())
