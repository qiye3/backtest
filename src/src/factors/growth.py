"""在每只股票当时已知的报告期历史上计算财务水平、变化和历史统计。"""
from __future__ import annotations
import numpy as np
import pandas as pd
from src.data.fundamentals import load_financial, report_snapshots, events_to_pit
from src.factors.base import Factor


def report_lag(rp, n):
    return (rp.to_period('Q') - n).end_time.normalize()


def history_value(history, method, window=8):
    rp = max(history)
    current = history[rp]
    if method == 'level':
        return current
    if method in {'yoy_difference', 'qoq_difference', 'yoy_relative', 'qoq_relative'}:
        lag = history.get(report_lag(rp, 4 if method.startswith('yoy') else 1), np.nan)
        difference = current - lag
        return difference if method.endswith('difference') else (difference / abs(lag) if lag != 0 else np.nan)
    # 按精确自然季度取滞后报告，不按全市场公告日期序列做 shift。
    prior = np.array([history.get(report_lag(rp, k), np.nan) for k in range(window, 0, -1)])
    if not np.isfinite(current) or not np.isfinite(prior).all():
        return np.nan
    if method in {'zscore', 'sue'}:
        sd = np.std(prior, ddof=1)
        return (current - prior.mean()) / sd if sd > 0 else np.nan
    if method == 'quantile':
        return float((prior <= current).mean())
    raise ValueError(f'unknown financial method: {method}')


def financial_panel(raw, field, method, calendar, codes, window=8):
    rows = []
    for code, dt, history in report_snapshots(raw, field):
        rows.append({'date': dt, 'code': code, 'value': history_value(history, method, window)})
    return events_to_pit(pd.DataFrame(rows, columns=['date', 'code', 'value']), calendar, codes)


class FinancialFactor(Factor):
    param_keys = {'value_field', 'method'}
    data_keys = {'financial_indicators'}

    def compute(self, data, definition, windows):
        field = definition['params']['value_field']
        fields = definition['data']['financial_indicators']
        key = ('financial', tuple(fields))
        if key not in data.event_cache:
            data.event_cache[key] = load_financial(data.root, data.trading_days[-1], fields)
        raw = data.event_cache[key]
        return financial_panel(raw, field, definition['params']['method'], data.trading_days,
                               data.stock_codes, windows.get('history_quarters', 8))


class FinancialHistoryFactor(FinancialFactor):
    window_keys = {'history_quarters'}
