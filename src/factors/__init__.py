"""
公开因子配置加载、单因子接口和批量计算入口。

本包通过 ``load_factor`` 或 ``load_factors`` 从 YAML 构造 Factor，通过
``calc_factors`` 计算一组实例，并提供 ``Factor`` 与 ``ExampleFactor`` 供具体公式继承
或参考。具体实现位于各自职责模块，本文件只定义稳定的包级导出，不包含业务计算和
文件写入。
"""

from src.factors.base import Factor
from src.factors.config import load_factor, load_factors
from src.factors.engine import calc_factors, iter_factor_panels
from src.factors.ExampleFactor import ExampleFactor

__all__ = [
    "ExampleFactor",
    "Factor",
    "calc_factors",
    "iter_factor_panels",
    "load_factor",
    "load_factors",
]
