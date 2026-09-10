"""将本模块的区间配置转换为目标权重；未来增强策略可直接提供同样的权重表。"""
import numpy as np
import pandas as pd
from src.data.calendar import sample_dates
from src.group_return.grouping import definitions,cross_section


def build_targets(panel,data,s,weeks,alignment='exact'):
    schedule={k:v for k,v in s['rebalance'].items() if k!='intervals_weeks'};schedule['every_n_weeks']=weeks
    dates=sample_dates(data.trading_days,s['start'],s['end'],schedule)
    available=data.trading_days[(data.trading_days>=pd.Timestamp(s['start']))&(data.trading_days<=pd.Timestamp(s['end']))]
    if available.empty:raise ValueError('no backtest dates')
    if s['initial_entry']=='start':dates=pd.DatetimeIndex([available[0]]).union(dates)
    if dates.empty:raise ValueError('no rebalance dates; extend date interval or use initial_entry=start')
    defs=definitions(s['grouping']['quantile_edges']);rows={g:[] for g in defs.group_id};members=[];actions=[]
    for dt in dates:
        x,ranks,groups,source=cross_section(panel,data,dt,s['factor_lag_days'],s['grouping'],alignment)
        enough=len(x)>=s['grouping']['min_stocks']
        for gid,w in groups.items():
            reason='' if enough and len(w) else 'insufficient_stocks' if not enough else 'empty_group'
            policy=s['insufficient_stocks_policy'] if not enough else s['empty_group_policy']
            if reason and policy=='error':raise ValueError(f'{reason} {gid} on {dt}')
            # 全NaN行表示保持真实旧持仓，不能把上次目标权重再平衡当作hold。
            target=pd.Series(np.nan if reason and policy=='hold' else 0.,index=data.stock_codes,name=dt)
            if not reason:target.loc[w.index]=w
            rows[gid].append(target)
            actions.append(dict(date=dt,group_id=gid,factor_date=source,action=policy if reason else 'rebalance',reason=reason,n_stocks=len(x)))
            for code,weight in w.items():
                if enough:members.append(dict(date=dt,group_id=gid,code=code,factor_date=source,factor_value=x[code],percentile=ranks[code],target_weight=weight))
    return dict(targets={g:pd.DataFrame(r) for g,r in rows.items()},definitions=defs,members=pd.DataFrame(members),actions=pd.DataFrame(actions),dates=dates)


def target_table(targets,factor_id,weeks):
    records=[]
    for gid,frame in targets.items():
        for dt,row in frame.iterrows():
            for code,w in row.items():records.append(dict(date=dt,portfolio_id=f'{factor_id}:{gid}:W{weeks}',code=code,target_weight=w,group_id=gid,rebalance_weeks=weeks))
    return pd.DataFrame(records)
