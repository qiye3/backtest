"""独立账户回测：现金与复权持仓数量连续滚动，支持理想或交易状态受限成交。"""
import numpy as np
import pandas as pd
from src.data.prices import PriceBook,benchmark_price
from src.backtest.rebalance import rebalance_weights,constrained_rebalance,EPS
from src.backtest.events import event_plan,timestamp,make_curve_frames,prepare_targets


def run_account(targets,data,s,need_daily=True):
    targets=prepare_targets(targets,data,s)
    codes=data.stock_codes;n=len(codes);qty=np.zeros(n);cash=float(s['initial_capital'])
    book=PriceBook(data,s['missing_price_policy'],s['max_stale_days'])
    rows=[];trades=[];turnover=[];holdings=[];first=True;benchmark_basis=None
    for dt,kind,is_rebalance,is_terminal in event_plan(targets,data,s,need_daily):
        prices,sources,price_dates=book.required(dt,kind,np.array(codes)[qty>EPS]);p=prices.to_numpy(float)
        values=np.where(qty>EPS,qty*np.nan_to_num(p),0.)
        before_nav=cash+values.sum()
        if before_nav<=0:raise ValueError('account assets must be positive')
        b=benchmark_price(data,dt,kind)
        if first:
            benchmark_basis=b
            rows.append(dict(date=dt,timestamp=timestamp(dt,kind),price_kind=kind,event='initial',is_rebalance=False,is_terminal=False,
                assets=before_nav,nav=1.,benchmark_nav=1.,cash=cash,cash_weight=1.))
        target=targets.loc[dt].to_numpy(float) if is_rebalance else None
        if is_terminal and s['liquidate_at_end']:target=np.zeros(n)
        traded=False
        if target is not None and not np.isnan(target).all():
            book.required(dt,kind,np.array(codes)[(qty>EPS)|(np.nan_to_num(target)>EPS)])
            rate=0. if first and not s['charge_initial_cost'] else s['transaction_cost_rate']
            before=values/before_nav
            if s['execution']['policy']=='ideal':
                after,cash_fraction,delta,k=rebalance_weights(before,target,rate);desired=delta;reasons=['']*n
            else:after,cash_fraction,delta,k,desired,reasons=constrained_rebalance(before,target,rate,codes,data,s,dt,kind,sources)
            cash=before_nav*cash_fraction
            qty=np.divide(before_nav*after,p,out=np.zeros(n),where=np.isfinite(p)&(p>0))
            buy=delta[delta>0].sum();sell=-delta[delta<0].sum()
            turnover.append(dict(date=dt,timestamp=timestamp(dt,kind),initial=first,buy_turnover=buy,sell_turnover=sell,turnover=(buy+sell)/2,
                cost_rate=k,cost_amount=before_nav*k,pretrade_assets=before_nav,
                estimated_trade_fraction=float(np.abs(delta)[sources.to_numpy()=='previous_close'].sum())))
            for j in np.flatnonzero((np.abs(delta)>EPS)|(np.abs(desired)>EPS)):
                amount=before_nav*delta[j];requested=before_nav*desired[j]
                status='rejected' if abs(amount)<=EPS else 'partial' if abs(amount-requested)>EPS else 'filled'
                trades.append(dict(date=dt,timestamp=timestamp(dt,kind),code=codes[j],side='buy' if desired[j]>0 else 'sell',status=status,reason=reasons[j],
                    requested_amount=abs(requested),amount=abs(amount),quantity=abs(amount)/p[j],price=p[j],cost=abs(amount)*rate,
                    weight_change=delta[j],price_source=sources.iloc[j],price_date=price_dates.iloc[j]))
            traded=True
        values=np.where(qty>EPS,qty*np.nan_to_num(p),0.);nav=cash+values.sum()
        if cash<-1e-9 or nav<=0:raise ValueError('invalid account balance')
        rows.append(dict(date=dt,timestamp=timestamp(dt,kind),price_kind=kind,event='rebalance' if traded else 'valuation',is_rebalance=is_rebalance,is_terminal=is_terminal,
            assets=nav,nav=nav/s['initial_capital'],benchmark_nav=b/benchmark_basis,cash=cash,cash_weight=cash/nav))
        for j in np.flatnonzero(qty>EPS):holdings.append(dict(date=dt,timestamp=timestamp(dt,kind),code=codes[j],quantity=qty[j],price=p[j],value=values[j],weight=values[j]/nav,price_source=sources.iloc[j]))
        first=False
    return dict(curves=make_curve_frames(rows),trades=pd.DataFrame(trades),turnover=pd.DataFrame(turnover),holdings=pd.DataFrame(holdings))
