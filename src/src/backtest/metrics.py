"""按模式与频率明确计算绩效：简易曲线线性累计，账户曲线按资产比率。"""
import numpy as np
import pandas as pd


def _returns(curve,mode,benchmark=False):
    key=('benchmark_cumulative_return' if benchmark else 'cumulative_return') if mode=='simple' else ('benchmark_nav' if benchmark else 'nav')
    return curve[key].diff() if mode=='simple' else curve[key].pct_change(fill_method=None)


def calculate(result,gross,mode,s,settings,weeks):
    freq=settings['return_frequency'];frame=result['curves'][freq].copy()
    full=result['curves']['all'];gross_full=gross['curves']['all']
    a,b=full.timestamp.iloc[0],full.timestamp.iloc[-1];years=(b-a).total_seconds()/(365.25*86400)
    if mode=='simple':
        value=full.cumulative_return;total=float(value.iloc[-1]);gross_total=float(gross_full.cumulative_return.iloc[-1])
        bench=float(full.benchmark_cumulative_return.iloc[-1]);excess=total-bench
        drawdown=float((value-value.cummax()).min());dd_method='additive_return_points'
        method=settings['simple_annual_return']
    else:
        value=full.nav;total=float(value.iloc[-1]-1);gross_total=float(gross_full.nav.iloc[-1]-1)
        bench=float(full.benchmark_nav.iloc[-1]-1);excess=float(value.iloc[-1]/full.benchmark_nav.iloc[-1]-1)
        drawdown=float((value/value.cummax()-1).min());dd_method='relative_nav'
        method=settings['account_annual_return']
    def annual(total_value):
        if years<=0:return np.nan
        if method=='linear':return total_value/years
        return np.expm1(np.log1p(total_value)/years) if total_value>-1 else np.nan
    # 简易模式若显式选择复合年化，则按调仓期净收益构造对照的复合路径。
    if mode=='simple' and method=='compound':
        net_period=_returns(result['curves']['rebalance'],mode).dropna()
        gross_period=_returns(gross['curves']['rebalance'],mode).dropna()
        annual_net=annual(float(np.prod(1+net_period)-1));annual_gross=annual(float(np.prod(1+gross_period)-1))
    else:annual_net=annual(total);annual_gross=annual(gross_total)
    if freq=='daily':
        # 同收盘的建仓前/后两行是瞬时扣费，不多算一个交易日；费用并入下一日收益。
        first_time=frame.timestamp.iloc[0]
        frame=frame.loc[(frame.event=='initial')|frame.timestamp.gt(first_time)].reset_index(drop=True)
    r=_returns(frame,mode);br=_returns(frame,mode,True)
    valid=r.notna()
    if freq=='rebalance':
        # 初始瞬时费用和最后不足一个调仓周期的尾段保留总收益，但不混入等周期风险统计。
        valid &= frame.is_rebalance & frame.timestamp.diff().gt(pd.Timedelta(0))
    r=r[valid];br=br[valid];periods=settings['annual_trading_days'] if freq=='daily' else settings['annual_weeks']/weeks
    rf=np.expm1(np.log1p(settings['risk_free_rate'])/periods);ex=r-rf
    sd=r.std(ddof=1);active=r-br;te=active.std(ddof=1)*np.sqrt(periods)
    turns=result['turnover'];chosen=turns if settings['include_initial_turnover'] or turns.empty else turns[~turns.initial]
    total_cost=float(turns.cost_amount.sum()) if mode=='account' and len(turns) else (0. if mode=='account' else np.nan)
    return dict(actual_start=str(a),actual_end=str(b),years=years,metric_frequency=freq,risk_periods=len(r),risk_periods_per_year=periods,
        gross_total_return=gross_total,net_total_return=total,total_return=total,
        annual_return=annual_net,gross_annual_return=annual_gross,annual_return_method=method,
        sharpe=float(ex.mean()/ex.std(ddof=1)*np.sqrt(periods)) if ex.std(ddof=1)>0 else np.nan,
        max_drawdown=drawdown,drawdown_method=dd_method,annual_volatility=float(sd*np.sqrt(periods)),
        mean_turnover=float(chosen.turnover.mean()) if len(chosen) else 0.,
        annual_turnover=float(chosen.turnover.sum()/years) if len(chosen) and years>0 else 0.,
        buy_turnover=float(chosen.buy_turnover.sum()) if len(chosen) else 0.,sell_turnover=float(chosen.sell_turnover.sum()) if len(chosen) else 0.,
        total_cost=total_cost,total_cost_rate=float(turns.cost_rate.sum()) if len(turns) else 0.,
        annual_cost_rate=float(turns.cost_rate.sum()/years) if len(turns) and years>0 else 0.,
        estimated_trade_fraction=float(turns.estimated_trade_fraction.sum()) if len(turns) else 0.,
        benchmark_total_return=bench,excess_total_return=excess,tracking_error=float(te),
        information_ratio=float(active.mean()*periods/te) if te>0 else np.nan)
