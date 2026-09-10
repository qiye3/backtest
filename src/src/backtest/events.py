"""统一估值事件与输出频率；开盘交易和当日收盘估值保留为不同时间点。"""
import pandas as pd
import numpy as np


def prepare_targets(targets,data,s):
    """外部策略也可提供目标表：按股票代码对齐，严格检查日期、权重与hold行。"""
    if not isinstance(targets,pd.DataFrame) or targets.empty:raise ValueError('targets must be a nonempty DataFrame')
    targets=targets.copy();targets.index=pd.DatetimeIndex(targets.index)
    if targets.index.has_duplicates or not targets.index.is_monotonic_increasing or targets.columns.has_duplicates:raise ValueError('target dates/columns must be unique; dates must be sorted')
    if not targets.index.isin(data.trading_days).all():raise ValueError('target date absent from trading calendar')
    if targets.index.min()<pd.Timestamp(s['start']) or targets.index.max()>pd.Timestamp(s['end']):raise ValueError('target dates outside backtest interval')
    if set(targets.columns)-set(data.stock_codes):raise ValueError('unknown target stock codes')
    hold=targets.isna().all(axis=1);targets=targets.reindex(columns=data.stock_codes,fill_value=0.).astype(float)
    targets.loc[hold]=np.nan
    active=targets.loc[~hold]
    if not np.isfinite(active).all().all() or (active<0).any().any() or (active.sum(axis=1)>1+1e-8).any():raise ValueError('target weights must be finite, nonnegative, and sum <= 1; only entire NaN rows mean hold')
    return targets


def event_plan(targets,data,s,need_daily):
    dates=targets.index
    days=data.trading_days[(data.trading_days>=dates[0])&(data.trading_days<=pd.Timestamp(s['end']))]
    if days.empty:raise ValueError('empty account interval')
    events=[]
    for dt in days:
        is_rebalance=dt in dates
        if is_rebalance and s['trade_price']=='open':events.append((dt,'open',True,False))
        if need_daily or is_rebalance or dt==days[-1]:events.append((dt,'close',is_rebalance and s['trade_price']=='close',dt==days[-1]))
    return events


def timestamp(dt,kind):return pd.Timestamp(dt)+pd.Timedelta(hours=9,minutes=30) if kind=='open' else pd.Timestamp(dt)+pd.Timedelta(hours=15)


def make_curve_frames(rows):
    frame=pd.DataFrame(rows)
    frame['timestamp']=pd.to_datetime(frame.timestamp)
    seed=frame[frame.event=='initial']
    rest=frame[frame.event!='initial']
    daily=rest[rest.price_kind=='close'].groupby('date',sort=False).tail(1)
    rebal=rest[rest.is_rebalance|rest.is_terminal]
    return dict(all=frame,daily=pd.concat([seed,daily],ignore_index=True),rebalance=pd.concat([seed,rebal],ignore_index=True))
