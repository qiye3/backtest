"""
公开因子配置加载、单因子接口和批量计算入口。

本包通过 ``load_factor`` 从一个 YAML 构造一个 Factor，通过 ``calc_factors`` 计算一组
实例，并提供 ``Factor`` 与 ``ExampleFactor`` 供具体公式继承或参考。具体实现位于各自
职责模块，本文件只定义稳定的包级导出，不包含业务计算和文件写入。
"""

from src.factors.base import Factor
from src.factors.ExampleFactor import ExampleFactor
from src.factors.config import load_factor
from src.factors.engine import calc_factors


__all__ = [
    "ExampleFactor",
    "Factor",
    "calc_factors",
    "load_factor",
]
