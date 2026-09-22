"""构建并复用全周期股票风格暴露缓存。"""

from __future__ import annotations

import numpy as np
import pandas as pd

from src.data.market_data import MarketData

STYLE_EXPOSURE_CACHE_FILE = "style_exposure_v1.parquet"


def load_or_build_style_exposures(
    market_data: MarketData,
    refresh: bool = False,
) -> pd.DataFrame:
    """优先读取固定版本缓存，刷新时重算并覆盖。"""
    cache_directory = market_data.cache_directory
    cache_path = (
        cache_directory / STYLE_EXPOSURE_CACHE_FILE
        if cache_directory is not None
        else None
    )
    if cache_path is not None and cache_path.exists() and not refresh:
        return pd.read_parquet(cache_path)

    style_exposures = build_style_exposures(market_data)
    if cache_path is not None:
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        style_exposures.to_parquet(cache_path)
    return style_exposures


def build_style_exposures(market_data: MarketData) -> pd.DataFrame:
    """计算 Size、Beta、Momentum、Volatility 和 Liquidity 横截面暴露。"""
    adjusted_close = market_data.get_panel("stock_quote", "S_DQ_ADJCLOSE")
    trading_amount = market_data.get_panel("stock_quote", "S_DQ_AMOUNT")
    market_value = market_data.get_panel("stock_valuation", "S_VAL_MV")
    benchmark_close = market_data.get_panel("index_price", "S_DQ_CLOSE")

    stock_returns = adjusted_close.pct_change(fill_method=None)
    benchmark_returns = benchmark_close[market_data.benchmark_index].pct_change(
        fill_method=None
    )
    benchmark_variance = benchmark_returns.rolling(
        window=252,
        min_periods=120,
    ).var()

    raw_styles = {
        "Size": np.log(market_value.where(market_value > 0)),
        "Beta": stock_returns.rolling(
            window=252,
            min_periods=120,
        ).cov(benchmark_returns).div(benchmark_variance, axis=0),
        # 动量跳过最近 21 个交易日，避免短期反转污染中期趋势。
        "Momentum": adjusted_close.shift(21).div(adjusted_close.shift(252)) - 1,
        "Volatility": stock_returns.rolling(
            window=60,
            min_periods=40,
        ).std(),
        "Liquidity": np.log(
            trading_amount.rolling(window=20, min_periods=15).mean().where(
                lambda values: values > 0
            )
        ),
    }
    standardized_styles = {
        style_name: _standardize_cross_sections(
            style_panel.reindex_like(market_data.membership),
            market_data.membership,
        )
        for style_name, style_panel in raw_styles.items()
    }
    style_exposures = pd.concat(
        standardized_styles,
        axis=1,
        names=["style_name", "asset_code"],
    )
    style_exposures.index = style_exposures.index.rename("date")
    return style_exposures.astype("float32")


def _standardize_cross_sections(
    raw_values: pd.DataFrame,
    membership: pd.DataFrame,
) -> pd.DataFrame:
    """在当日股票池内缩尾并标准化，不填补原始缺失值。"""
    eligible_values = raw_values.where(membership)

    def standardize_row(cross_section: pd.Series) -> pd.Series:
        valid_values = cross_section.dropna()
        if valid_values.empty:
            return cross_section
        lower_bound = valid_values.quantile(0.01)
        upper_bound = valid_values.quantile(0.99)
        winsorized = valid_values.clip(lower_bound, upper_bound)
        standard_deviation = winsorized.std(ddof=0)
        if standard_deviation == 0:
            cross_section.loc[valid_values.index] = 0.0
            return cross_section
        cross_section.loc[valid_values.index] = (
            winsorized - winsorized.mean()
        ) / standard_deviation
        return cross_section

    return eligible_values.apply(standardize_row, axis=1)
