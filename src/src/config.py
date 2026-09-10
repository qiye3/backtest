"""按运行模块校验配置；三项任务的分组、日期和周期均独立保存。"""
from __future__ import annotations
from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
import re
import numpy as np
import pandas as pd
import yaml

MODULES = ['factors', 'group_return', 'simple_backtest', 'account_backtest', 'plotting']
SCHEDULE = dict(weekday='FRI', every_n_weeks=1, anchor_date='2021-01-01', holiday_policy='previous_trading_day')
GROUPING = dict(quantile_edges=[[i/10, (i+1)/10] for i in range(10)], min_stocks=200,
                missing_factor_policy='exclude', weighting=dict(method='equal', field=None, lag_days=0))
EVALUATION = dict(start=None, end=None, factor_ids=[], universe_indices=['000906.SH','000852.SH'],
                  grouping=GROUPING, sampling=SCHEDULE, factor_lag_days=0, reference_price='close',
                  future_return_days=[5,20,60], group_return_agg='mean', time_return_agg='mean',
                  empty_group_policy='nan', insufficient_stocks_policy='nan',
                  missing_price_policy='previous_close', max_stale_days=None)
BACKTEST = dict(start=None, end=None, factor_ids=[], universe_indices=['000906.SH','000852.SH'],
                grouping=GROUPING, rebalance={**SCHEDULE, 'intervals_weeks':[1,2,4]}, factor_lag_days=0,
                trade_price='close', initial_entry='first_rebalance', initial_capital=1.0,
                transaction_cost_rate=0.0, charge_initial_cost=True, liquidate_at_end=False,
                empty_group_policy='cash', insufficient_stocks_policy='error',
                missing_price_policy='error', max_stale_days=None, curve_frequency='both',
                execution=dict(policy='ideal', block_suspended=True, block_buy_limit_up=True, block_sell_limit_down=True))
del BACKTEST['rebalance']['every_n_weeks']
PLOTS = dict(enabled=True, formats=['png','pdf'], dpi=160, width=13.0, row_height=3.4,
             font_family='DejaVu Sans', curve_frequency='daily', missing_results='skip', note='', legend_columns=4,
             distribution=dict(enabled=True, bins=60, density=True, kde=True, clip_quantiles=None, max_points=200000),
             evaluation=dict(enabled=True, group_panel='left', group_colors=['#A91E22','#A68B32','#137A3F'], ic_color='#D06A2D',rank_ic_color='#174A73'),
             simple=dict(enabled=True, layout='rows', group_colors=['#A91E22','#A68B32','#137A3F'],benchmark_color='#777777',
                         summary_quantile=[.9,1.],metric_columns=['annual_return','annual_volatility','sharpe','max_drawdown','annual_turnover']),
             account=dict(enabled=True, layout='rows', group_colors=['#CB3C3C','#198754'],benchmark_color='#888888'))
METRICS = dict(risk_free_rate=0.0, return_frequency='daily', annual_trading_days=252, annual_weeks=52,
               include_initial_turnover=True, simple_annual_return='linear', account_annual_return='compound',
               ic_horizons=[5,20,60])
PLOT_METRIC_FIELDS = {'annual_return','annual_volatility','sharpe','max_drawdown','annual_turnover',
                      'annual_cost_rate','total_cost_rate','net_total_return','gross_total_return',
                      'benchmark_total_return','excess_total_return','tracking_error','information_ratio'}


def check_keys(value, allowed, location):
    if not isinstance(value,dict): raise ValueError(f'{location} must be a mapping')
    unknown=set(value)-set(allowed)
    if unknown: raise ValueError(f'unknown {location} fields: {sorted(unknown)}')


def positive_int(value,name):
    if isinstance(value,bool) or not isinstance(value,int) or value<1: raise ValueError(f'{name} must be a positive integer')
    return value


def nonnegative_int(value,name):
    if isinstance(value,bool) or not isinstance(value,int) or value<0: raise ValueError(f'{name} must be a nonnegative integer')
    return value


def choice(value, choices, name):
    if value not in choices: raise ValueError(f'{name} must be one of {choices}, got {value!r}')


def fill(value, defaults, name):
    """逐级深拷贝默认值，禁止一个模块修改另一个模块的列表或分组配置。"""
    value={} if value is None else value
    check_keys(value,defaults,name)
    out=deepcopy(defaults)
    for key,v in value.items(): out[key]=fill(v,defaults[key],f'{name}.{key}') if isinstance(defaults[key],dict) else deepcopy(v)
    return out


def interval(s,name):
    if s['start'] is None or s['end'] is None: raise ValueError(f'{name}.start/end are required')
    a,b=pd.Timestamp(s['start']),pd.Timestamp(s['end'])
    if pd.isna(a) or pd.isna(b) or a>b: raise ValueError(f'invalid {name} interval')
    s['start'],s['end']=str(a.date()),str(b.date())


def validate_schedule(s,multiple=False):
    choice(s['weekday'],['MON','TUE','WED','THU','FRI'],'weekday')
    choice(s['holiday_policy'],['previous_trading_day','skip'],'holiday_policy')
    if pd.isna(pd.Timestamp(s['anchor_date'])): raise ValueError('invalid anchor_date')
    values=s['intervals_weeks'] if multiple else [s['every_n_weeks']]
    if not isinstance(values,list) or not values or len(values)!=len(set(values)): raise ValueError('rebalance/sampling intervals must be nonempty and unique')
    for n in values: positive_int(n,'weeks')


def validate_grouping(s):
    from src.group_return.grouping import validate_ranges
    s['quantile_edges']=validate_ranges(s['quantile_edges'])
    positive_int(s['min_stocks'],'min_stocks')
    choice(s['missing_factor_policy'],['exclude','error'],'missing_factor_policy')
    w=s['weighting'];choice(w['method'],['equal','field'],'weighting.method')
    nonnegative_int(w['lag_days'],'weighting.lag_days')
    if w['method']=='field' and not w['field']:raise ValueError('field weighting requires a positive historical field, e.g. S_DQ_MV')
    if w['method']=='equal' and (w['field'] is not None or w['lag_days']!=0):raise ValueError('equal weighting does not use field/lag_days')


def validate_stage(s,name):
    interval(s,name);validate_grouping(s['grouping'])
    if not isinstance(s['factor_ids'],list):raise ValueError('factor_ids must be a list')
    if not isinstance(s['universe_indices'],list) or not s['universe_indices']:raise ValueError('universe_indices must be nonempty')
    nonnegative_int(s['factor_lag_days'],'factor_lag_days')
    choice(s['missing_price_policy'],['error','previous_close'],'missing_price_policy')
    if s['max_stale_days'] is not None:nonnegative_int(s['max_stale_days'],'max_stale_days')
    if name=='group_return':
        validate_schedule(s['sampling']);choice(s['reference_price'],['open','close'],'reference_price')
        if not isinstance(s['future_return_days'],list) or not s['future_return_days'] or len(set(s['future_return_days']))!=len(s['future_return_days']):raise ValueError('future_return_days must be nonempty and unique')
        for n in s['future_return_days']:positive_int(n,'future_return_days')
        for k in ['group_return_agg','time_return_agg']:choice(s[k],['mean','median'],k)
        for k in ['empty_group_policy','insufficient_stocks_policy']:choice(s[k],['nan','error'],k)
    else:
        validate_schedule(s['rebalance'],True);choice(s['trade_price'],['open','close'],'trade_price')
        choice(s['initial_entry'],['first_rebalance','start'],'initial_entry')
        choice(s['curve_frequency'],['daily','rebalance','both'],'curve_frequency')
        choice(s['empty_group_policy'],['cash','hold','error'],'empty_group_policy')
        choice(s['insufficient_stocks_policy'],['cash','hold','error'],'insufficient_stocks_policy')
        if not np.isfinite(s['initial_capital']) or s['initial_capital']<=0:raise ValueError('initial_capital must be positive')
        if not np.isfinite(s['transaction_cost_rate']) or not 0<=s['transaction_cost_rate']<1:raise ValueError('transaction_cost_rate must be in [0,1)')
        for k in ['charge_initial_cost','liquidate_at_end']:
            if not isinstance(s[k],bool):raise ValueError(f'{k} must be boolean')
        e=s['execution'];choice(e['policy'],['ideal','tradability'],'execution.policy')
        if name=='simple_backtest' and e['policy']!='ideal':raise ValueError('tradability execution requires account_backtest')
        for k in ['block_suspended','block_buy_limit_up','block_sell_limit_down']:
            if not isinstance(e[k],bool):raise ValueError(f'{k} must be boolean')
        # 简易回测按单位资金计算；initial_capital只影响账户，避免伪装成简易账户本金。
        if name=='simple_backtest' and s['initial_capital']!=1:raise ValueError('simple_backtest uses unit capital; initial_capital must be 1')


@dataclass
class Config:
    path: Path
    raw: dict
    modules: list
    factor_configs: list

    def resolve(self,p):
        p=Path(p).expanduser()
        return p.resolve() if p.is_absolute() else (self.path.parent/p).resolve()

    @property
    def output_dir(self):return self.resolve(self.raw['output']['root'])/self.raw['experiment']['name']


def load_config(path,modules=None):
    path=Path(path).expanduser().resolve();raw=yaml.safe_load(path.read_text(encoding='utf-8'))
    allowed=['experiment','run','data','factors','factor_input','parallel','group_return','simple_backtest','account_backtest','metrics','plots','output']
    check_keys(raw,allowed,'root')
    raw['experiment']=fill(raw.get('experiment'),dict(name='single_factor_v5'),'experiment')
    if not re.fullmatch(r'[A-Za-z0-9_-]+',raw['experiment']['name']):raise ValueError('unsafe experiment.name')
    raw['run']=fill(raw.get('run'),dict(modules=['group_return','simple_backtest','account_backtest','plotting']),'run')
    modules=raw['run']['modules'] if modules is None or modules==['all'] else modules
    if isinstance(modules,str):modules=modules.split(',')
    if not modules or len(modules)!=len(set(modules)) or set(modules)-set(MODULES):raise ValueError(f'modules must be selected from {MODULES}')
    modules=[m for m in MODULES if m in modules]
    raw['data']=fill(raw.get('data'),dict(root='../data',calendar_path=None,benchmark='000906.SH',benchmark_return='total_return'),'data')
    choice(raw['data']['benchmark_return'],['total_return','price'],'benchmark_return')
    raw['parallel']=fill(raw.get('parallel'),dict(enabled=True,backend='process',workers=4,on_error='continue'),'parallel')
    positive_int(raw['parallel']['workers'],'workers');choice(raw['parallel']['backend'],['process','thread'],'backend');choice(raw['parallel']['on_error'],['continue','stop'],'on_error')
    if not isinstance(raw['parallel']['enabled'],bool):raise ValueError('parallel.enabled must be bool')
    raw['output']=fill(raw.get('output'),dict(root='../outputs',save_group_members=True,save_target_weights=True,save_holdings=True,save_trades=True),'output')
    for k,v in raw['output'].items():
        if k!='root' and not isinstance(v,bool):raise ValueError(f'{k} must be boolean')
    definitions=[]
    if 'factors' in modules:
        f=raw.get('factors',{});check_keys(f,['start','end','universe_indices','values_dir','configs'],'factors');interval(f,'factors')
        if not f.get('configs') or not f.get('universe_indices') or not f.get('values_dir'):raise ValueError('factors requires configs, universe_indices, values_dir')
        from src.factors.builder import validate_definition
        for p in f['configs']:
            d=yaml.safe_load((path.parent/p).resolve().read_text(encoding='utf-8'));validate_definition(d);definitions.append(d)
        if len({d['name'] for d in definitions})!=len(definitions):raise ValueError('duplicate factor names')
    if set(modules)&{'group_return','simple_backtest','account_backtest'}:
        i=fill(raw.get('factor_input'),dict(source='generated',values_dir='../outputs/factor_values',ids=[],files=[],layout='wide',date_column='date',alignment='exact'),'factor_input')
        choice(i['source'],['generated','external'],'factor_input.source');choice(i['layout'],['wide'],'layout');choice(i['alignment'],['exact','asof'],'alignment')
        if not isinstance(i['ids'],list) or len(i['ids'])!=len(set(i['ids'])):raise ValueError('factor_input.ids must be unique list')
        if i['source']=='external':
            if not i['files']:raise ValueError('external factor_input requires files')
            for item in i['files']:
                check_keys(item,['id','path'],'factor_input.files')
                if not item.get('id') or not item.get('path'):raise ValueError('factor file needs id and path')
            if len({x['id'] for x in i['files']})!=len(i['files']):raise ValueError('duplicate external factor ids')
        raw['factor_input']=i
    for name in ['group_return','simple_backtest','account_backtest']:
        if name in modules:
            raw[name]=fill(raw.get(name),EVALUATION if name=='group_return' else BACKTEST,name);validate_stage(raw[name],name)
    raw['metrics']=fill(raw.get('metrics'),METRICS,'metrics')
    m=raw['metrics'];choice(m['return_frequency'],['daily','rebalance'],'metrics.return_frequency')
    for k in ['annual_trading_days','annual_weeks']:positive_int(m[k],k)
    if not np.isfinite(m['risk_free_rate']) or m['risk_free_rate']<=-1:raise ValueError('invalid risk_free_rate')
    choice(m['simple_annual_return'],['linear','compound'],'simple_annual_return');choice(m['account_annual_return'],['linear','compound'],'account_annual_return')
    if not isinstance(m['include_initial_turnover'],bool):raise ValueError('include_initial_turnover must be boolean')
    for h in m['ic_horizons']:positive_int(h,'ic_horizons')
    raw['plots']=fill(raw.get('plots'),PLOTS,'plots');p=raw['plots']
    for v in [p['enabled'],*[p[k]['enabled'] for k in ['distribution','evaluation','simple','account']],p['distribution']['kde'],p['distribution']['density']]:
        if not isinstance(v,bool):raise ValueError('plot switches must be boolean')
    positive_int(p['legend_columns'],'legend_columns')
    choice(p['evaluation']['group_panel'],['left','right'],'group_panel')
    choice(p['simple']['layout'],['rows'],'plots.simple.layout')
    choice(p['account']['layout'],['rows','columns'],'plots.account.layout')
    summary_quantile=p['simple']['summary_quantile']
    if (not isinstance(summary_quantile,list) or len(summary_quantile)!=2 or
            any(isinstance(v,bool) or not isinstance(v,(int,float)) or not np.isfinite(v) for v in summary_quantile) or
            not 0<=summary_quantile[0]<summary_quantile[1]<=1):
        raise ValueError('plots.simple.summary_quantile must be [lower, upper] within [0,1]')
    metric_columns=p['simple']['metric_columns']
    if (not isinstance(metric_columns,list) or not metric_columns or len(metric_columns)!=len(set(metric_columns)) or
            set(metric_columns)-PLOT_METRIC_FIELDS):
        raise ValueError(f'plots.simple.metric_columns must be unique values from {sorted(PLOT_METRIC_FIELDS)}')
    choice(p['curve_frequency'],['daily','rebalance'],'plots.curve_frequency');choice(p['missing_results'],['skip','error'],'plots.missing_results')
    if not p['formats'] or set(p['formats'])-{'png','pdf','svg'}:raise ValueError('plot formats: png/pdf/svg')
    positive_int(p['dpi'],'dpi');positive_int(p['distribution']['bins'],'bins');positive_int(p['distribution']['max_points'],'max_points')
    if p['width']<=0 or p['row_height']<=0:raise ValueError('plot dimensions must be positive')
    clip=p['distribution']['clip_quantiles']
    if clip is not None and (len(clip)!=2 or not 0<=clip[0]<clip[1]<=1):raise ValueError('invalid clip_quantiles')
    for q in ['evaluation','simple','account']:
        if len(p[q]['group_colors'])<2:raise ValueError('group_colors requires at least two colors')
    return Config(path,raw,modules,definitions)
