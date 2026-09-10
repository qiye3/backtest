"""多未来周期评估：总体IC/RankIC、独立区间收益以及两层聚合。"""
import numpy as np
import pandas as pd
from src.data.calendar import sample_dates
from src.data.prices import PriceBook
from src.group_return.grouping import cross_section,definitions


def correlation(x,y,rank=False):
    if len(x)<2 or x.nunique()<2 or y.nunique()<2:return np.nan
    return float(x.rank(method='average').corr(y.rank(method='average')) if rank else x.corr(y))


def evaluate(panel,data,s,alignment='exact'):
    dates=sample_dates(data.trading_days,s['start'],s['end'],s['sampling'])
    if dates.empty:raise ValueError('no evaluation dates')
    defs=definitions(s['grouping']['quantile_edges']);book=PriceBook(data,s['missing_price_policy'],s['max_stale_days'])
    rows=[];ics=[];members=[];labels=[]
    for dt in dates:
        x,ranks,groups,factor_date=cross_section(panel,data,dt,s['factor_lag_days'],s['grouping'],alignment)
        enough=len(x)>=s['grouping']['min_stocks']
        if not enough and s['insufficient_stocks_policy']=='error':raise ValueError(f'insufficient factor stocks on {dt}')
        for gid,w in groups.items():
            for code,weight in w.items():members.append(dict(date=dt,factor_date=factor_date,group_id=gid,code=code,factor_value=x[code],percentile=ranks[code],weight=weight))
        for horizon in s['future_return_days']:
            endpos=data.trading_days.get_indexer([dt])[0]+horizon
            mature=endpos<len(data.trading_days) and data.trading_days[endpos]<=pd.Timestamp(s['end'])
            end=data.trading_days[endpos] if endpos<len(data.trading_days) else pd.NaT
            status='horizon_incomplete' if not mature else 'insufficient_stocks' if not enough else 'complete'
            base=dict(date=dt,factor_date=factor_date,return_end_date=end,horizon_days=horizon,n_stocks=len(x),status=status)
            returns=pd.Series(dtype=float);filled=pd.Series(dtype=bool)
            ic=rank_ic=np.nan
            if status=='complete':
                p0,src0,pd0=book.required(dt,s['reference_price'],x.index)
                p1,src1,pd1=book.required(end,s['reference_price'],x.index)
                returns=p1.reindex(x.index)/p0.reindex(x.index)-1
                filled=((src0=='previous_close')|(src1=='previous_close')).reindex(x.index)
                # IC基于完整有效截面；改变或重叠区间，不会改变总体IC。
                ic=correlation(x,returns);rank_ic=correlation(x,returns,True)
                for code in x.index:labels.append(dict(date=dt,code=code,horizon_days=horizon,return_end_date=end,
                    stock_return=returns[code],start_price=p0[code],end_price=p1[code],start_price_date=pd0[code],end_price_date=pd1[code],
                    start_price_source=src0[code],end_price_source=src1[code]))
            ics.append(dict(**base,ic=ic,rank_ic=rank_ic,n_returns=len(returns),n_price_filled=int(filled.sum())))
            for rec in defs.itertuples(index=False):
                w=groups[rec.group_id];group_status=status;value=np.nan
                if status=='complete':
                    if w.empty:
                        if s['empty_group_policy']=='error':raise ValueError(f'empty evaluation group {rec.group_id} on {dt}')
                        group_status='empty_group'
                    else:
                        r=returns.reindex(w.index)
                        value=float(r.median() if s['group_return_agg']=='median' else r@w)
                rows.append(dict(**{k:v for k,v in base.items() if k!='status'},group_id=rec.group_id,
                    quantile_lower=rec.quantile_lower,quantile_upper=rec.quantile_upper,label=rec.label,
                    group_return=value,n_group_stocks=len(w),n_group_price_filled=int(filled.reindex(w.index,fill_value=False).sum()),status=group_status))
    detail=pd.DataFrame(rows);ic_series=pd.DataFrame(ics);summary=[];ic_summary=[]
    for h,g in ic_series.groupby('horizon_days',sort=False):
        row=dict(horizon_days=h,start=s['start'],end=s['end'],ic_scope='full_universe',n_dates=len(g),n_complete_dates=int((g.status=='complete').sum()))
        for name in ['ic','rank_ic']:
            seq=g[name].dropna();sd=seq.std(ddof=1)
            row[name+'_mean']=seq.mean();row[name+'_std']=sd;row['icir' if name=='ic' else 'rank_icir']=seq.mean()/sd if sd>0 else np.nan
            row[name+'_n_dates']=len(seq)
        ic_summary.append(row)
    for (h,gid),g in detail.groupby(['horizon_days','group_id'],sort=False):
        first=g.iloc[0];valid=g.group_return.dropna()
        summary.append(dict(horizon_days=h,group_id=gid,quantile_lower=first.quantile_lower,quantile_upper=first.quantile_upper,label=first.label,
            start=s['start'],end=s['end'],group_return_agg=s['group_return_agg'],time_return_agg=s['time_return_agg'],
            group_return=getattr(valid,s['time_return_agg'])(),n_dates=len(g),n_valid_dates=len(valid),mean_group_size=g.n_group_stocks.mean()))
    return dict(definitions=defs,detail=detail,ic=ic_series,summary=pd.DataFrame(summary),ic_summary=pd.DataFrame(ic_summary),
                members=pd.DataFrame(members),labels=pd.DataFrame(labels),sample_dates=dates)
