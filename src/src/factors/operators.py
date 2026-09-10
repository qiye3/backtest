"""因子自身的固定时序加工和平滑；评价与回测读取最终生成的值。"""
import numpy as np
from src.data.calendar import sample_dates


def transform(panel, definition, windows):
    spec = definition.get('time_transform')
    if not spec:
        return panel
    method = spec['method']
    if method in {'change', 'relative_change'}:
        lag = panel.shift(spec['lag_days'])
        return panel - lag if method == 'change' else (panel - lag) / lag.abs().replace(0, np.nan)
    n = windows['transform_window']
    minimum = max(2, int(np.ceil(n * spec['min_fraction'])))
    rolling = panel.rolling(n, min_periods=minimum)
    if method == 'zscore':
        return (panel - rolling.mean()) / rolling.std().replace(0, np.nan)
    if method == 'quantile':
        return rolling.rank(pct=True)
    raise ValueError(f'unknown transform: {method}')


def smooth(panel, definition, windows, end):
    spec = definition['smoothing']
    n = windows['smooth_window']
    if spec['unit'] == 'weekly_closes':
        schedule = {'weekday': 'FRI', 'every_n_weeks': 1, 'anchor_date': '2000-01-03',
                    'holiday_policy': 'previous_trading_day'}
        dates = sample_dates(panel.index, panel.index[0], end, schedule)
        values = panel.reindex(dates)
    else:
        values = panel
    result = getattr(values.rolling(n, min_periods=n), spec['method'])()
    # 延续最近已完成周的因子值；该周明确缺失时保留 NaN。
    return result.reindex(panel.index, method='ffill') if spec['unit'] == 'weekly_closes' else result
