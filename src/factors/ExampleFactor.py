"""
提供一个可运行的区间收益示例因子。

本模块位于具体因子实现层，只包含 ``ExampleFactor``。它从 ``MarketData`` 读取个股
复权收盘价，并使用 YAML 中的回看交易日数计算区间收益；输出交给批量引擎统一对齐，
本模块不读取配置文件、不保存结果，也不包含其他因子公式。
"""

from __future__ import annotations

import pandas as pd

from src.data.market_data import MarketData
from src.factors.base import Factor


class ExampleFactor(Factor):
    """
    根据复权收盘价计算可配置周期的区间收益。

    输入：
    - 构造时继承 ``Factor`` 的完整配置，``params`` 必须包含 ``lookback_days``。
    - 计算时接收包含 ``stock_quote/S_DQ_ADJCLOSE`` 面板的 ``MarketData``。

    输出：
    - ``calc`` 返回日期乘股票的区间收益面板。

    功能和用途：
    - 展示一个因子一个类、配置参数读取和市场面板访问的标准写法。
    - 使用真实收益公式，使示例可以直接参与批量计算和下游评价。
    """

    # 按配置的交易日跨度计算个股复权价格收益率。
    def calc(self, market_data: MarketData) -> pd.DataFrame:
        """
        计算复权收盘价的多期收益率。

        输入：
        - market_data：提供个股复权收盘价的市场数据对象。
        - ``self.config["params"]["lookback_days"]``：收益回看交易日数。

        输出：
        - 返回与复权价格面板同索引、同列的收益率 DataFrame；回看期不足的位置为空。

        功能和用途：
        - 使用 pandas ``pct_change`` 比较当前价格和指定交易日前价格。
        - 明确关闭缺失价格的隐式填充，停牌或数据缺口不会被自动补价。
        """
        adjusted_close = market_data.get_panel(
            "stock_quote",
            "S_DQ_ADJCLOSE",
        )
        lookback_days = self.config["params"]["lookback_days"]
        return adjusted_close.pct_change(
            periods=lookback_days,
            fill_method=None,
        )
