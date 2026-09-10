"""简易回测仅维护归一化权重；净收益以调仓期为单位相加，每日曲线展开期内路径。"""
import numpy as np
import pandas as pd
from src.data.prices import PriceBook,benchmark_price
from src.backtest.rebalance import drift,rebalance_weights,EPS
from src.backtest.events import event_plan,timestamp,make_curve_frames,prepare_targets


def run_simple(targets,data,s,need_daily=True):
    if s['execution']['policy']!='ideal':raise ValueError('simple backtest requires ideal execution')
    targets=prepare_targets(targets,data,s)
    codes=data.stock_codes;n=len(codes);w=np.zeros(n);last_prices=None
    book=PriceBook(data,s['missing_price_policy'],s['max_stale_days'])
    events=event_plan(targets,data,s,need_daily);rows=[];trades=[];turnover=[]
    base=0.;growth=1.;benchmark_base=0.;benchmark_growth=1.;last_benchmark=None;first=True
    for dt,kind,is_rebalance,is_terminal in events:
        prices,sources,price_dates=book.required(dt,kind,np.array(codes)[w>EPS]);p=prices.to_numpy(float)
        if last_prices is not None:w,step=drift(w,last_prices,p);growth*=step
        b=benchmark_price(data,dt,kind)
        if last_benchmark is not None:benchmark_growth*=b/last_benchmark
        if first:
            rows.append(dict(date=dt,timestamp=timestamp(dt,kind),price_kind=kind,event='initial',is_rebalance=False,is_terminal=False,
                cumulative_return=0.,benchmark_cumulative_return=0.,cash_weight=1.))
        traded=False
        target=targets.loc[dt].to_numpy(float) if is_rebalance else None
        if is_terminal and s['liquidate_at_end']:target=np.zeros(n)
        if target is not None and not np.isnan(target).all():
            # 目标与原持仓的并集需要价格，离开股票池的旧股票也必须估值和卖出。
            book.required(dt,kind,np.array(codes)[(w>EPS)|(np.nan_to_num(target)>EPS)])
            rate=0. if first and not s['charge_initial_cost'] else s['transaction_cost_rate']
            values,cash,delta,cost=rebalance_weights(w,target,rate)
            scale_before=growth
            buy=delta[delta>0].sum();sell=-delta[delta<0].sum()
            turnover.append(dict(date=dt,timestamp=timestamp(dt,kind),initial=first,buy_turnover=buy,sell_turnover=sell,
                turnover=(buy+sell)/2,cost_rate=cost,cost_contribution=scale_before*cost,
                estimated_trade_fraction=float(np.abs(delta)[sources.to_numpy()=='previous_close'].sum())))
            for j in np.flatnonzero(np.abs(delta)>EPS):
                trades.append(dict(date=dt,timestamp=timestamp(dt,kind),code=codes[j],side='buy' if delta[j]>0 else 'sell',
                    weight_change=delta[j],cost_rate=abs(delta[j])*rate,price=p[j],price_source=sources.iloc[j],price_date=price_dates.iloc[j]))
            w=values/(1-cost);growth*=1-cost;traded=True
        curve=base+growth-1;bench=benchmark_base+benchmark_growth-1
        rows.append(dict(date=dt,timestamp=timestamp(dt,kind),price_kind=kind,event='rebalance' if traded else 'valuation',
            is_rebalance=is_rebalance,is_terminal=is_terminal,cumulative_return=curve,benchmark_cumulative_return=bench,cash_weight=1-w.sum()))
        # 每个约定调仓点结束一个收益段；即使hold，也不能改变累加周期。
        if is_rebalance:
            base=curve;growth=1.;benchmark_base=bench;benchmark_growth=1.
        last_prices=p;last_benchmark=b;first=False
    return dict(curves=make_curve_frames(rows),trades=pd.DataFrame(trades),turnover=pd.DataFrame(turnover))
