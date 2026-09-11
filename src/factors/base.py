"""
定义所有市场因子的统一计算接口。

本模块位于 Factor YAML 加载和具体因子计算之间，只包含 ``Factor`` 抽象基类。
基类接收完整因子配置并保存实例名称，具体子类通过 ``calc`` 消费 ``MarketData``，
输出日期乘股票的数值面板；本模块不读取文件、不选择市场字段，也不处理因子结果。
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Mapping

import pandas as pd

from src.data.market_data import MarketData


class Factor(ABC):
    """
    保存单个因子的完整配置并约束计算接口。

    输入：
    - config：单个 Factor YAML 解析后的完整映射，必须包含唯一的 ``name``；其余配置
      由具体因子类按照固定公式读取。

    输出：
    - 该类自身不生成因子值；子类实例公开 ``name``、``config`` 和 ``calc``。

    功能和用途：
    - 让 YAML 加载器、批量引擎和所有具体因子共享同一个最小调用契约。
    - 基类只保存公共状态，不猜测子类参数，也不承担结果对齐或股票池过滤。
    """

    # 保存完整因子配置和批量结果使用的实例名称。
    def __init__(self, config: Mapping[str, Any]) -> None:
        """
        初始化单个因子实例。

        输入：
        - config：完整因子配置；``name`` 用作批量结果键，其他分区供子类计算使用。

        输出：
        - 无返回值；配置副本保存在 ``self.config``，名称保存在 ``self.name``。

        功能和用途：
        - 每个 YAML 对应一个独立实例，避免多个因子共享可变配置。
        - 具体子类无需重复实现配置保存和名称提取。
        """
        self.config = dict(config)
        self.name = self.config["name"]

    # 使用已经物化的市场数据计算具体因子值。
    @abstractmethod
    def calc(self, market_data: MarketData) -> pd.DataFrame:
        """
        计算单个因子的原始数值面板。

        输入：
        - market_data：已经完成交易日、证券列和 PIT 对齐的 ``MarketData``。

        输出：
        - 返回索引为交易日、列为股票代码的 ``pandas.DataFrame``。

        功能和用途：
        - 子类在此实现固定经济含义的公式，并从 ``self.config`` 读取自身参数。
        - 输出对齐和动态股票池掩码由批量引擎统一完成，子类不重复处理。
        """
        raise NotImplementedError
