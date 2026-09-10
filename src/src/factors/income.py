"""利润表累计值转单季，再按固定定义计算收入水平或季节性超预期。"""
from __future__ import annotations
import numpy as np
import pandas as pd
from src.data.income import load_income
from src.data.fundamentals import report_snapshots, events_to_pit
from src.factors.base import Factor
from src.factors.growth import report_lag


def single_quarter_history(cumulative):
    result = {}
    for rp, value in cumulative.items():
        result[rp] = value if rp.quarter == 1 else value - cumulative.get(report_lag(rp, 1), np.nan)
    return result


def seasonal_surprise(history, n):
    rp = max(history)
    surprise = history[rp] - history.get(report_lag(rp, 4), np.nan)
    past = np.array([history.get(report_lag(rp, k), np.nan) - history.get(report_lag(rp, k + 4), np.nan)
                     for k in range(n, 0, -1)])
    if not np.isfinite(surprise) or not np.isfinite(past).all():
        return np.nan
    sd = past.std(ddof=1)
    return (surprise - past.mean()) / sd if sd > 0 else np.nan


class IncomeFactor(Factor):
    param_keys = {'value_field', 'method'}
    data_keys = {'income'}

    def compute(self, data, definition, windows):
        fields = definition['data']['income']
        field = definition['params']['value_field']
        key = ('income', tuple(fields))
        if key not in data.event_cache:
            data.event_cache[key] = load_income(data.root, data.trading_days[-1], fields)
        rows = []
        for code, dt, cumulative in report_snapshots(data.event_cache[key], field):
            history = single_quarter_history(cumulative)
            value = history[max(history)] if definition['params']['method'] == 'level' else seasonal_surprise(history, windows['history_quarters'])
            rows.append({'date': dt, 'code': code, 'value': value})
        return events_to_pit(pd.DataFrame(rows, columns=['date', 'code', 'value']), data.trading_days, data.stock_codes)


class IncomeSurpriseFactor(IncomeFactor):
    window_keys = {'history_quarters'}
