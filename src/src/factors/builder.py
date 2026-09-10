"""校验固定因子定义、生成窗口变体，并保存可核对构造与内容的因子文件。"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re
import numpy as np
import pandas as pd
import yaml
from src.config import check_keys, positive_int
from src.data.io import load_market_data
from src.factors.registry import get_factor
from src.factors.operators import transform, smooth


def validate_definition(d):
    check_keys(d, ['name', 'implementation', 'direction', 'data', 'params', 'history', 'smoothing', 'time_transform', 'window_defaults', 'variants'], 'factor')
    if not re.fullmatch(r'[a-z][a-z0-9_]*', d['name']):
        raise ValueError('factor name must be descriptive snake_case')
    factor = get_factor(d['implementation'])
    check_keys(d['params'], factor.param_keys, f"{d['name']}.params")
    check_keys(d['data'], factor.data_keys, f"{d['name']}.data")
    if d['direction'] not in {-1, 1}:
        raise ValueError('direction must be 1 or -1')
    check_keys(d['history'], ['trading_days'], 'history')
    positive_int(d['history']['trading_days'], 'history.trading_days')
    check_keys(d['smoothing'], ['method', 'unit'], 'smoothing')
    if d['smoothing']['method'] not in {'mean', 'median'}:
        raise ValueError('smoothing.method must be mean or median')
    if d['smoothing']['unit'] not in {'trading_days', 'weekly_closes'}:
        raise ValueError('smoothing.unit must be trading_days or weekly_closes')
    allowed = factor.window_keys | {'smooth_window'}
    if d.get('time_transform'):
        t = d['time_transform']
        if t['method'] in {'zscore', 'quantile'}:
            check_keys(t, ['method', 'min_fraction'], 'time_transform')
            if not 0 < t['min_fraction'] <= 1:
                raise ValueError('min_fraction must be in (0,1]')
            allowed |= {'transform_window'}
        elif t['method'] in {'change', 'relative_change'}:
            check_keys(t, ['method', 'lag_days'], 'time_transform')
            positive_int(t['lag_days'], 'lag_days')
        else:
            raise ValueError('unknown time_transform method')
    if set(d['window_defaults']) != allowed:
        raise ValueError(f"{d['name']} requires exactly these window_defaults: {sorted(allowed)}")
    if not d['variants']:
        raise ValueError('at least one variant is required')
    names, signatures = set(), set()
    for v in d['variants']:
        check_keys(v, ['name', 'windows'], 'variant: only window overrides are allowed')
        if not re.fullmatch(r'[a-z][a-z0-9_]*', v['name']) or v['name'] in names:
            raise ValueError('invalid or duplicate variant name')
        names.add(v['name'])
        check_keys(v.get('windows', {}), allowed, 'variant.windows')
        windows = {**d['window_defaults'], **v.get('windows', {})}
        for k, value in windows.items():
            positive_int(value, k)
            if k in {'history_quarters', 'volatility_window', 'transform_window'} and value < 2:
                raise ValueError(f'{k} requires at least two observations')
        sig = tuple(sorted(windows.items()))
        if sig in signatures:
            raise ValueError('two variants have identical effective windows')
        signatures.add(sig)
    impl, p = d['implementation'], d['params']
    if impl in {'financial', 'financial_history'}:
        methods = {'level', 'yoy_difference', 'qoq_difference', 'yoy_relative', 'qoq_relative'} if impl == 'financial' else {'zscore', 'sue', 'quantile'}
        if p['method'] not in methods or p['value_field'] not in d['data']['financial_indicators']:
            raise ValueError('financial method/field does not match implementation/data')
    if impl in {'income', 'income_surprise'}:
        if p['method'] != ('level' if impl == 'income' else 'seasonal_sue') or p['value_field'] not in d['data']['income']:
            raise ValueError('income method/field does not match implementation/data')
    if impl == 'consensus':
        if p['source'] not in {'wind', 'suntime'}:
            raise ValueError('consensus source must be wind or suntime')
        if set(d['data']) != {f"consensus_{p['source']}"}:
            raise ValueError('consensus data must match the selected source')
        if p['source'] == 'suntime' and p.get('target_year_rule') != 'current_year':
            raise ValueError('suntime requires current_year rule')
        if p['source'] == 'wind' and 'target_year_rule' in p:
            raise ValueError('target_year_rule is not used for wind')
        if p['value_field'] not in next(iter(d['data'].values())):
            raise ValueError('value_field absent from data fields')
    if impl == 'residual_momentum':
        if not 0 < p['volatility_min_fraction'] <= 1:
            raise ValueError('invalid volatility_min_fraction')
        if p['index_code'] not in d['data']['index_price_codes'] or 'S_DQ_ADJCLOSE' not in d['data']['stock_price']:
            raise ValueError('residual momentum requires its index and adjusted closes')


def definition_hash(definition):
    return hashlib.sha256(json.dumps(definition, sort_keys=True, default=str).encode()).hexdigest()


def file_hash(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def factor_code_hash():
    """数据与因子代码共同参与内容校验；代码变更后需重新生成因子文件。"""
    root = Path(__file__).resolve().parents[1]
    h = hashlib.sha256()
    for folder in ['factors', 'data']:
        for p in sorted((root / folder).glob('*.py')):
            h.update(str(p.relative_to(root)).encode())
            h.update(p.read_bytes())
    return h.hexdigest()


def build_panels(data, definitions, start, end):
    panels = {}
    for d in definitions:
        validate_definition(d)
        factor = get_factor(d['implementation'])
        base_cache = {}
        for v in d['variants']:
            windows = {**d['window_defaults'], **v.get('windows', {})}
            # 仅平滑窗口不同时复用基础值；内部聚合窗口不同时重新计算基础值。
            key = tuple(sorted((k, windows[k]) for k in factor.window_keys))
            if key not in base_cache:
                base_cache[key] = factor.compute(data, d, windows)
            values = transform(base_cache[key], d, windows)
            values = smooth(values, d, windows, end) * d['direction']
            values = values.replace([np.inf, -np.inf], np.nan)
            panels[f"{d['name']}.{v['name']}"] = values.loc[pd.Timestamp(start):pd.Timestamp(end)].reindex(columns=data.stock_codes)
    return panels



def check_existing_factor_identity(folder, definitions):
    previous = Path(folder) / 'resolved_config.yaml'
    if not previous.exists():
        return
    old = {d['name']: d for d in yaml.safe_load(previous.read_text(encoding='utf-8'))}
    def fixed(d):
        return {k: v for k, v in d.items() if k not in {'history', 'window_defaults', 'variants'}}
    for d in definitions:
        if d['name'] in old and fixed(d) != fixed(old[d['name']]):
            raise ValueError(f"fixed formula/operator changed for {d['name']}; register a new factor name")

def save_panels(folder, panels, definitions, section):
    folder = Path(folder)
    check_existing_factor_identity(folder, definitions)
    folder.mkdir(parents=True, exist_ok=True)
    metadata = {'format_version': 2, 'code_hash': factor_code_hash(), 'start': str(section['start']),
                'end': str(section['end']), 'universe_indices': section['universe_indices'], 'entries': {}}
    defs = {d['name']: d for d in definitions}
    for variant_id, frame in panels.items():
        filename = f'{variant_id}.csv.gz'
        path = folder / filename
        frame.to_csv(path, compression={'method': 'gzip', 'mtime': 0}, index_label='date', float_format='%.17g')
        factor_name = variant_id.split('.', 1)[0]
        metadata['entries'][variant_id] = {'factor': factor_name, 'definition_hash': definition_hash(defs[factor_name]),
                                          'filename': filename, 'sha256': file_hash(path),
                                          'actual_start': str(frame.index.min()), 'actual_end': str(frame.index.max())}
    (folder / 'resolved_config.yaml').write_text(yaml.safe_dump(definitions, allow_unicode=True, sort_keys=False), encoding='utf-8')
    (folder / 'manifest.json').write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding='utf-8')
    return metadata


def load_panels(folder, definitions=()):
    folder = Path(folder)
    manifest = json.loads((folder / 'manifest.json').read_text(encoding='utf-8'))
    if manifest['format_version'] != 2 or manifest['code_hash'] != factor_code_hash():
        raise ValueError('factor implementation changed: regenerate factor values')
    expected = {d['name']: definition_hash(d) for d in definitions}
    panels = {}
    for variant_id, entry in manifest['entries'].items():
        if not re.fullmatch(r'[a-z][a-z0-9_]*\.[a-z][a-z0-9_]*', variant_id) or entry['filename'] != f'{variant_id}.csv.gz':
            raise ValueError('invalid factor manifest filename')
        if definitions and entry['factor'] not in expected:
            continue
        if entry['factor'] in expected and expected[entry['factor']] != entry['definition_hash']:
            raise ValueError(f'factor definition changed: {entry["factor"]}; regenerate values')
        path = folder / entry['filename']
        if file_hash(path) != entry['sha256']:
            raise ValueError(f'factor file checksum mismatch: {variant_id}')
        frame = pd.read_csv(path, index_col=0, parse_dates=True, float_precision='round_trip')
        frame.index = pd.DatetimeIndex(frame.index, name='date')
        if frame.index.has_duplicates or not frame.index.is_monotonic_increasing or frame.columns.has_duplicates:
            raise ValueError(f'invalid factor panel: {variant_id}')
        panels[variant_id] = frame
    wanted = {f"{d['name']}.{v['name']}" for d in definitions for v in d['variants']}
    if wanted - set(panels):
        raise ValueError(f'factor artifacts missing: {sorted(wanted - set(panels))}')
    if not panels:
        raise ValueError('no factor panels found')
    return panels, manifest


def generate_factors(root, section, definitions):
    check_existing_factor_identity(section['values_dir'], definitions)
    start, end = pd.Timestamp(section['start']), pd.Timestamp(section['end'])
    history = max(d['history']['trading_days'] for d in definitions)
    # 先扩大加载范围，再精确截取所需的历史交易日，检查预热数据是否足够。
    market = load_market_data(root, start - pd.Timedelta(days=history * 2 + 30), end,
                              section['universe_indices'],
                              fields=set().union(*(set(d['data'].get('stock_price', [])) for d in definitions)),
                              index_codes=set().union(*(set(d['data'].get('index_price_codes', [])) for d in definitions)))
    prior = market.trading_days[market.trading_days < start]
    if len(prior) < history:
        raise ValueError(f'factor warmup requires {history} prior trading days; only {len(prior)} available')
    keep = market.trading_days[market.trading_days >= prior[-history]]
    market.quote = {k: v.reindex(keep) for k, v in market.quote.items()}
    market.membership = market.membership.reindex(keep)
    market.membership_by_index = {k: v.reindex(keep) for k, v in market.membership_by_index.items()}
    market.index_price = {k: v.reindex(keep) for k, v in market.index_price.items()}
    panels = build_panels(market, definitions, start, end)
    save_panels(section['values_dir'], panels, definitions, section)
    return panels
