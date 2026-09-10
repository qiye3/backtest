"""一致预期及评级因子；取值、方向与窗口由因子定义明确指定。"""
import pandas as pd
from src.data.consensus import load_consensus, consensus_panel
from src.data.ratings import load_ratings
from src.factors.base import Factor


class ConsensusFactor(Factor):
    param_keys = {'value_field', 'source', 'target_year_rule'}
    data_keys = {'consensus_suntime', 'consensus_wind'}

    def compute(self, data, definition, windows):
        p = definition['params']
        source = p['source']
        fields = definition['data'][f'consensus_{source}']
        key = (source, tuple(fields), p.get('target_year_rule'))
        if key not in data.event_cache:
            data.event_cache[key] = load_consensus(data.root, data.trading_days[-1], fields, source, p.get('target_year_rule'))
        return consensus_panel(data.event_cache[key], data.trading_days, data.stock_codes, p['value_field'])


class RatingFactor(Factor):
    param_keys = {'upgrade_field', 'downgrade_field', 'maintain_field', 'rating_cycle'}
    data_keys = {'ratings'}

    def compute(self, data, definition, windows):
        p = definition['params']
        raw = load_ratings(data.root, data.trading_days[-1], definition['data']['ratings'], p['rating_cycle'])
        up, down, maintain = [pd.to_numeric(raw[p[k]], errors='coerce') for k in ['upgrade_field', 'downgrade_field', 'maintain_field']]
        raw['value'] = (up - down) / (up + down + maintain).replace(0, float('nan'))
        return consensus_panel(raw, data.trading_days, data.stock_codes, 'value')
