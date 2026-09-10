"""共用交易计算：漂移后权重、精确比例费用，以及账户模式的可选成交限制。"""
import numpy as np
import pandas as pd
from scipy.optimize import brentq
EPS=1e-12


def rebalance_weights(before,target,cost_rate):
    """按调仓前资产归一：扣费后目标值=(1-k)*target，求解k=c*总买卖比例。"""
    before=np.asarray(before,float);target=np.asarray(target,float)
    if not np.isfinite(before).all() or (before<-EPS).any() or before.sum()>1+1e-8:raise ValueError('invalid pretrade stock weights')
    if not np.isfinite(target).all() or (target<-EPS).any() or target.sum()>1+1e-8:raise ValueError('target weights must be nonnegative and sum to at most one')
    if not 0<=cost_rate<1:raise ValueError('cost_rate must be in [0,1)')
    fun=lambda k:k-cost_rate*np.abs((1-k)*target-before).sum()
    k=0. if cost_rate==0 else float(brentq(fun,0.,1.,xtol=1e-14))
    after_value=(1-k)*target
    trades=after_value-before
    cash=1-k-after_value.sum()
    if cash<-1e-10:raise ValueError('negative cash after cost adjustment')
    return after_value,max(0.,cash),trades,k


def drift(weights,prices_before,prices_after):
    """现金不变，股票数量不变，仅按行情更新归一化持仓权重。"""
    held=weights>EPS
    if ((~np.isfinite(prices_before[held]))|(~np.isfinite(prices_after[held]))|(prices_before[held]<=0)|(prices_after[held]<=0)).any():raise ValueError('cannot value held stocks')
    relative=np.ones(len(weights));relative[held]=prices_after[held]/prices_before[held]
    values=weights*relative;growth=1-weights.sum()+values.sum()
    if growth<=0:raise ValueError('nonpositive normalized assets')
    return values/growth,float(growth)


def blocked_reason(data,s,dt,kind,code,side,source):
    if source=='previous_close':return 'missing_reference_price'
    e=s['execution']
    if e['block_suspended']:
        state=data.quote['S_DQ_TRADESTATUS'].at[dt,code]
        if pd.isna(state):return 'unknown_trade_status'
        if '停' in str(state):return 'suspended'
    enabled=e['block_buy_limit_up'] if side=='buy' else e['block_sell_limit_down']
    if enabled:
        field='S_DQ_OPEN' if kind=='open' else 'S_DQ_CLOSE'
        p=data.quote[field].at[dt,code]
        limit=data.quote['S_DQ_LIMIT' if side=='buy' else 'S_DQ_STOPPING'].at[dt,code]
        if not np.isfinite(p) or not np.isfinite(limit) or p<=0 or limit<=0:return 'unknown_price_limit'
        if side=='buy' and p>=limit*(1-1e-10):return 'limit_up'
        if side=='sell' and p<=limit*(1+1e-10):return 'limit_down'
    return ''


def constrained_rebalance(before,target,cost_rate,codes,data,s,dt,kind,sources):
    """受限账户先卖后买，冻结被拒绝订单；现金不足时等比例缩减可成交买入。"""
    intended,_,desired,_=rebalance_weights(before,target,cost_rate)
    actual=before.copy();cash=1-before.sum();trades=np.zeros(len(codes));reasons=['']*len(codes)
    for j in np.flatnonzero(desired<-EPS):
        reasons[j]=blocked_reason(data,s,dt,kind,codes[j],'sell',sources.iloc[j])
        if not reasons[j]:
            sold=-desired[j];actual[j]-=sold;trades[j]-=sold;cash+=sold*(1-cost_rate)
    wants=np.zeros(len(codes))
    for j in np.flatnonzero(desired>EPS):
        reasons[j]=blocked_reason(data,s,dt,kind,codes[j],'buy',sources.iloc[j])
        if not reasons[j]:wants[j]=desired[j]
    required=wants.sum()*(1+cost_rate);scale=min(1.,max(0.,cash)/required) if required else 0.
    for j in np.flatnonzero(wants>EPS):
        bought=wants[j]*scale;actual[j]+=bought;trades[j]+=bought;cash-=bought*(1+cost_rate)
        if scale<1-1e-10:reasons[j]='cash_constraint'
    cost=cost_rate*np.abs(trades).sum()
    return actual,max(0.,cash),trades,cost,desired,reasons
