"""计算相对指数收益并按历史波动率调整的动量信号。"""
import numpy as np
from src.factors.base import Factor


class ResidualMomentum(Factor):
    """Retains v1 volatility-ratio adjusted momentum; this is not regression beta."""
    param_keys = {'index_code', 'volatility_min_fraction'}
    data_keys = {'stock_price', 'index_price_codes'}
    window_keys = {'return_window', 'volatility_window'}

    def compute(self, data, definition, windows):
        p = definition['params']
        r, v = windows['return_window'], windows['volatility_window']
        minimum = max(2, int(np.ceil(v * p['volatility_min_fraction'])))
        stock = data.stock_field('S_DQ_ADJCLOSE')
        index = data.index_price[p['index_code']].reindex(stock.index)
        stock_vol = stock.pct_change(fill_method=None).rolling(v, min_periods=minimum).std()
        index_vol = index.pct_change(fill_method=None).rolling(v, min_periods=minimum).std().replace(0, np.nan)
        ratio = stock_vol.div(index_vol, axis=0)
        return stock.pct_change(r, fill_method=None).sub(ratio.mul(index.pct_change(r, fill_method=None), axis=0))
