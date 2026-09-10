"""独立分位区间：允许重叠、不补齐边界；调用者传入各模块自己的配置。"""
import numpy as np
import pandas as pd


def validate_ranges(ranges):
    if not isinstance(ranges,list) or not ranges:raise ValueError('quantile_edges must be a nonempty list of [lower, upper] pairs')
    out=[]
    for pair in ranges:
        if not isinstance(pair,(list,tuple)) or len(pair)!=2:raise ValueError('each quantile interval needs exactly two numbers')
        if any(isinstance(v,bool) or not isinstance(v,(int,float)) or not np.isfinite(v) for v in pair):raise ValueError('quantile intervals must contain finite numbers')
        lo,hi=map(float,pair)
        if not 0<=lo<hi<=1:raise ValueError('require 0 <= lower < upper <= 1')
        if [lo,hi] in out:raise ValueError('duplicate quantile interval')
        out.append([lo,hi])
    return out


def definitions(ranges):
    return pd.DataFrame([dict(group_id=f'G{i+1:02d}',quantile_lower=lo,quantile_upper=hi,
                              label=f'{lo*100:g}%–{hi*100:g}%',target_fraction=hi-lo)
                         for i,(lo,hi) in enumerate(ranges)])


def factor_at(panel,days,dt,lag,alignment='exact'):
    pos=days.get_indexer([dt])[0]-lag
    if pos<0:raise ValueError(f'factor lag needs more history before {dt}')
    at=days[pos]
    if alignment=='asof':
        n=panel.index.searchsorted(at,side='right')-1
        if n<0:raise ValueError(f'no factor available by {at}')
        at=panel.index[n]
    if at not in panel.index:raise ValueError(f'factor snapshot unavailable: {at}; use alignment=asof only when carrying whole snapshots is intended')
    return panel.loc[at],at


def cross_section(panel,data,dt,lag,grouping,alignment='exact'):
    row,source_date=factor_at(panel,data.trading_days,dt,lag,alignment)
    active=data.membership.loc[dt]
    x=row.reindex(active.index[active]).astype(float)
    finite=np.isfinite(x)
    if not finite.all() and grouping['missing_factor_policy']=='error':raise ValueError(f'missing factor values on {dt}: {list(x.index[~finite])[:5]}')
    x=x[finite]
    ranks=(x.rank(method='average')-.5)/len(x) if len(x) else x.copy()
    wcfg=grouping['weighting'];field_values=None
    if wcfg['method']=='field':
        p=data.trading_days.get_indexer([dt])[0]-wcfg['lag_days']
        if p<0:raise ValueError('insufficient weight-field history')
        field_values=data.quote[wcfg['field']].iloc[p]
    groups={}
    for rec in definitions(grouping['quantile_edges']).itertuples(index=False):
        member=x.index[(ranks>=rec.quantile_lower)&((ranks<rec.quantile_upper)|(rec.quantile_upper==1))]
        w=pd.Series(1.,index=member) if field_values is None else field_values.reindex(member)
        if len(w) and ((~np.isfinite(w))|(w<=0)).any():raise ValueError(f'nonpositive or missing grouping weight field on {dt}')
        groups[rec.group_id]=w/w.sum() if len(w) else w
    return x,ranks,groups,source_date
