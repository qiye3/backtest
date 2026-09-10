"""因子计算接口，声明可用数据、固定参数与允许变动的窗口。"""
from __future__ import annotations
from abc import ABC, abstractmethod


class Factor(ABC):
    """A fixed formula with an explicit set of variable aggregation windows."""
    window_keys: set[str] = set()
    param_keys: set[str] = set()
    data_keys: set[str] = set()

    @abstractmethod
    def compute(self, data, definition: dict, windows: dict):
        raise NotImplementedError
