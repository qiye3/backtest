"""提供基于日频复权收盘价、成交量和成交额的参数化价量因子。"""

from __future__ import annotations

from collections.abc import Callable

import numpy as np
import pandas as pd

from src.data.market_data import MarketData
from src.factors.base import Factor


class PriceVolumeFactor(Factor):
    """按照 YAML 指定的公式和窗口计算一个日频价量因子。"""

    def calc(self, market_data: MarketData) -> pd.DataFrame:
        """读取价量面板并执行配置点名的固定公式。"""
        adjusted_close = market_data.get_panel("stock_quote", "S_DQ_ADJCLOSE")
        volume = market_data.get_panel("stock_quote", "S_DQ_VOLUME")
        amount = market_data.get_panel("stock_quote", "S_DQ_AMOUNT")
        params = self.config["params"]
        formula = params["formula"]
        calculators: dict[str, Callable[[], pd.DataFrame]] = {
            "momentum": lambda: _momentum(adjusted_close, params["window"]),
            "reversal": lambda: -_momentum(adjusted_close, params["window"]),
            "volatility": lambda: _volatility(adjusted_close, params["window"]),
            "downside_volatility": lambda: _downside_volatility(
                adjusted_close,
                params["window"],
            ),
            "price_position": lambda: _price_position(
                adjusted_close,
                params["window"],
            ),
            "moving_average_deviation": lambda: _moving_average_deviation(
                adjusted_close,
                params["window"],
            ),
            "volume_ratio": lambda: _volume_ratio(
                volume,
                params["short_window"],
                params["long_window"],
            ),
            "volume_change": lambda: _volume_change(volume, params["window"]),
            "volume_zscore": lambda: _volume_zscore(volume, params["window"]),
            "amihud_illiquidity": lambda: _amihud_illiquidity(
                adjusted_close,
                amount,
                params["window"],
            ),
            "price_volume_correlation": lambda: _price_volume_correlation(
                adjusted_close,
                volume,
                params["window"],
            ),
        }
        if formula not in calculators:
            raise ValueError(f"不支持的价量因子公式: {formula}")
        return calculators[formula]().replace([np.inf, -np.inf], np.nan)


def _momentum(adjusted_close: pd.DataFrame, window: int) -> pd.DataFrame:
    """计算当前复权收盘价相对指定交易日前的区间收益。"""
    return adjusted_close.pct_change(periods=window, fill_method=None)


def _volatility(adjusted_close: pd.DataFrame, window: int) -> pd.DataFrame:
    """计算日收益在窗口内的样本标准差。"""
    daily_returns = adjusted_close.pct_change(fill_method=None)
    return daily_returns.rolling(window, min_periods=window).std()


def _downside_volatility(
    adjusted_close: pd.DataFrame,
    window: int,
) -> pd.DataFrame:
    """把正收益记为零，计算窗口内负收益相对零的均方根。"""
    daily_returns = adjusted_close.pct_change(fill_method=None)
    downside_returns = daily_returns.clip(upper=0)
    downside_variance = downside_returns.pow(2).rolling(
        window,
        min_periods=window,
    ).mean()
    return np.sqrt(downside_variance)


def _price_position(adjusted_close: pd.DataFrame, window: int) -> pd.DataFrame:
    """计算收盘价在窗口最高价与最低价之间的相对位置。"""
    rolling_minimum = adjusted_close.rolling(window, min_periods=window).min()
    rolling_maximum = adjusted_close.rolling(window, min_periods=window).max()
    return (adjusted_close - rolling_minimum) / (rolling_maximum - rolling_minimum)


def _moving_average_deviation(
    adjusted_close: pd.DataFrame,
    window: int,
) -> pd.DataFrame:
    """计算收盘价相对窗口简单移动均价的偏离比例。"""
    moving_average = adjusted_close.rolling(window, min_periods=window).mean()
    return adjusted_close / moving_average - 1


def _volume_ratio(
    volume: pd.DataFrame,
    short_window: int,
    long_window: int,
) -> pd.DataFrame:
    """计算短窗口平均成交量与长窗口平均成交量之比。"""
    short_average = volume.rolling(short_window, min_periods=short_window).mean()
    long_average = volume.rolling(long_window, min_periods=long_window).mean()
    return short_average / long_average - 1


def _volume_change(volume: pd.DataFrame, window: int) -> pd.DataFrame:
    """计算成交量相对指定交易日前的变化率。"""
    return volume.pct_change(periods=window, fill_method=None)


def _volume_zscore(volume: pd.DataFrame, window: int) -> pd.DataFrame:
    """计算当前成交量相对窗口历史分布的标准分。"""
    rolling_mean = volume.rolling(window, min_periods=window).mean()
    rolling_std = volume.rolling(window, min_periods=window).std()
    return (volume - rolling_mean) / rolling_std


def _amihud_illiquidity(
    adjusted_close: pd.DataFrame,
    amount: pd.DataFrame,
    window: int,
) -> pd.DataFrame:
    """计算窗口平均绝对日收益除以成交额，并缩放到亿元单位。"""
    absolute_returns = adjusted_close.pct_change(fill_method=None).abs()
    daily_illiquidity = absolute_returns / amount * 100_000_000
    return daily_illiquidity.rolling(window, min_periods=window).mean()


def _price_volume_correlation(
    adjusted_close: pd.DataFrame,
    volume: pd.DataFrame,
    window: int,
) -> pd.DataFrame:
    """计算日收益与成交量变化率的滚动相关系数。"""
    daily_returns = adjusted_close.pct_change(fill_method=None)
    volume_changes = volume.pct_change(fill_method=None)
    return daily_returns.rolling(window, min_periods=window).corr(volume_changes)
