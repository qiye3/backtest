"""用可手算案例检查收益、扣费、漂移、边界和独立分组。"""
from copy import deepcopy
import unittest
import numpy as np
import pandas as pd
from src.config import GROUPING,EVALUATION,BACKTEST,METRICS,fill,validate_stage
from src.data.io import MarketData
from src.data.prices import PriceBook
from src.data.calendar import sample_dates
from src.group_return.grouping import cross_section,validate_ranges,factor_at
from src.group_return.evaluator import evaluate
from src.backtest.targets import build_targets
from src.backtest.rebalance import rebalance_weights
from src.backtest.simple import run_simple
from src.backtest.account import run_account
from src.backtest.metrics import calculate


def market(end='2021-01-15',stocks=4):
    days=pd.bdate_range('2021-01-01',end);codes=[f'S{i}' for i in range(stocks)]
    prices=pd.DataFrame(100.,index=days,columns=codes)
    return MarketData({'S_DQ_ADJCLOSE':prices.copy(),'S_DQ_ADJOPEN':prices.copy(),
        'S_DQ_OPEN':prices.copy(),'S_DQ_CLOSE':prices.copy(),'S_DQ_LIMIT':prices*1.1,
        'S_DQ_STOPPING':prices*.9,'S_DQ_TRADESTATUS':pd.DataFrame('交易',index=days,columns=codes),
        'S_DQ_MV':prices*pd.Series(np.arange(stocks)+1,index=codes)},prices.astype(bool),
        benchmark_total_return=pd.Series(100.,index=days),benchmark_open=pd.Series(100.,index=days))


def spec(evaluation=False,**changes):
    s=deepcopy(EVALUATION if evaluation else BACKTEST)
    s.update(start='2021-01-01',end='2021-01-15',**changes)
    s['grouping'].update(min_stocks=2,quantile_edges=[[0,.5],[.5,1]])
    if evaluation:s['future_return_days']=[5,10]
    else:s['rebalance']['intervals_weeks']=[1]
    return s


def panel(data):
    return pd.DataFrame(np.tile(np.arange(len(data.stock_codes)),(len(data.trading_days),1)),index=data.trading_days,columns=data.stock_codes)


def targets(data,weights):
    return pd.DataFrame([weights]*3,index=data.trading_days[[0,5,10]],columns=data.stock_codes,dtype=float)


class GroupTests(unittest.TestCase):
    def test_overlapping_ranges_do_not_add_boundaries(self):
        d=market(stocks=100);s=spec(True);s['grouping']['quantile_edges']=[[.9,1],[.99,1]]
        x,r,g,_=cross_section(panel(d),d,d.trading_days[0],0,s['grouping'])
        self.assertEqual([len(v) for v in g.values()],[10,1]);self.assertTrue(set(g['G02'].index)<=set(g['G01'].index))
        self.assertEqual(validate_ranges([[.9,1],[.99,1]]),[[.9,1.],[.99,1.]])
        with self.assertRaises(ValueError):validate_ranges([[.9,1],[.9,1]])

    def test_ties_and_column_order(self):
        d=market();x=panel(d).astype(float);x.iloc[:]=[1,2,2,2]
        s=spec(True);s['grouping']['quantile_edges']=[[.5,1]]
        a=cross_section(x,d,d.trading_days[0],0,s['grouping'])[2]['G01']
        b=cross_section(x.iloc[:,::-1],d,d.trading_days[0],0,s['grouping'])[2]['G01']
        pd.testing.assert_series_equal(a,b);self.assertEqual(len(a),3)

    def test_ic_full_pool_and_future_cutoff(self):
        d=market();d.quote['S_DQ_ADJCLOSE'].iloc[5:]=[101,104,109,116]
        s=spec(True);a=evaluate(panel(d),d,s)
        s['grouping']['quantile_edges']=[[.9,1],[.99,1]];b=evaluate(panel(d),d,s)
        pd.testing.assert_frame_equal(a['ic'],b['ic'])
        first=a['ic'].iloc[0];self.assertAlmostEqual(first.ic,np.corrcoef([0,1,2,3],[.01,.04,.09,.16])[0,1])
        self.assertAlmostEqual(first.rank_ic,1)
        incomplete=a['detail'][a['detail'].status=='horizon_incomplete']
        self.assertTrue(incomplete.group_return.isna().all())

    def test_group_mean_median_and_date_aggregation(self):
        d=market();d.quote['S_DQ_ADJCLOSE'].iloc[5:]=[100,100,110,150]
        s=spec(True);s['grouping']['quantile_edges']=[[0,1]]
        a=evaluate(panel(d),d,s);s['group_return_agg']='median';s['time_return_agg']='median';b=evaluate(panel(d),d,s)
        self.assertAlmostEqual(a['detail'].iloc[0].group_return,.15)
        self.assertAlmostEqual(b['detail'].iloc[0].group_return,.05)
        valid=b['detail'].query('horizon_days == 5').group_return.dropna()
        self.assertAlmostEqual(b['summary'].query('horizon_days == 5').iloc[0].group_return,valid.median())

    def test_future_missing_price_does_not_remove_stock(self):
        d=market();d.quote['S_DQ_ADJCLOSE'].iloc[5,0]=np.nan
        s=spec(True);result=evaluate(panel(d),d,s)
        self.assertEqual(result['ic'].iloc[0].n_returns,4)
        self.assertEqual(result['ic'].iloc[0].n_price_filled,1)
        s['missing_price_policy']='error'
        with self.assertRaisesRegex(ValueError,'missing close'):evaluate(panel(d),d,s)

    def test_price_fallback_is_past_only_and_bounded(self):
        d=market();d.quote['S_DQ_ADJCLOSE'].iloc[1,0]=999;d.quote['S_DQ_ADJOPEN'].iloc[1:3,0]=np.nan
        p,source,_=PriceBook(d,'previous_close').row(d.trading_days[1],'open')
        self.assertEqual(p.iloc[0],100);self.assertEqual(source.iloc[0],'previous_close')
        with self.assertRaises(ValueError):PriceBook(d,'previous_close',0).required(d.trading_days[1],'open',['S0'])

    def test_holiday_schedule_and_factor_snapshot(self):
        days=pd.bdate_range('2021-01-01','2021-01-15').difference(pd.to_datetime(['2021-01-08']))
        schedule=spec(True)['sampling'];self.assertIn(pd.Timestamp('2021-01-07'),sample_dates(days,days[0],days[-1],schedule))
        schedule['holiday_policy']='skip';self.assertNotIn(pd.Timestamp('2021-01-07'),sample_dates(days,days[0],days[-1],schedule))
        d=market();x=panel(d).astype(float);x.iloc[5,0]=np.nan;sparse=x.iloc[[0,5]]
        row,at=factor_at(sparse,d.trading_days,d.trading_days[6],0,'asof')
        self.assertTrue(pd.isna(row.iloc[0]));self.assertEqual(at,d.trading_days[5])
        self.assertEqual(factor_at(x,d.trading_days,d.trading_days[6],1)[1],d.trading_days[5])

    def test_weighted_groups_and_independent_config(self):
        d=market();s=spec();s['grouping']['weighting'].update(method='field',field='S_DQ_MV')
        g=cross_section(panel(d),d,d.trading_days[0],0,s['grouping'])[2]
        np.testing.assert_allclose(g['G02'],[3/7,4/7])
        a=fill({},BACKTEST,'a');b=fill({},BACKTEST,'b');a['grouping']['quantile_edges'][0][0]=.01
        self.assertEqual(b['grouping']['quantile_edges'][0][0],0)


class EngineTests(unittest.TestCase):
    def test_external_targets_align_columns_and_reject_partial_nan(self):
        d=market();d.quote['S_DQ_ADJCLOSE'].iloc[5:,0]=120;s=spec();t=targets(d,[1,0,0,0])
        a=run_account(t,d,s)['curves']['all'];b=run_account(t.iloc[:,::-1],d,s)['curves']['all']
        np.testing.assert_allclose(a.nav,b.nav)
        t.iloc[1,0]=np.nan
        with self.assertRaises(ValueError):run_account(t,d,s)

    def test_daily_risk_does_not_count_initial_fee_as_extra_day(self):
        d=market();s=spec(transaction_cost_rate=.001);t=targets(d,[1,0,0,0]);r=run_account(t,d,s)
        m=calculate(r,r,'account',s,deepcopy(METRICS),1)
        self.assertEqual(m['risk_periods'],len(d.trading_days)-1)

    def test_arithmetic_vs_compound_and_daily_vs_rebalance(self):
        d=market();d.quote['S_DQ_ADJCLOSE'].iloc[5:10]=110;d.quote['S_DQ_ADJCLOSE'].iloc[10:]=99
        s=spec();t=targets(d,[1,0,0,0])
        simple=run_simple(t,d,s);account=run_account(t,d,s)
        self.assertAlmostEqual(simple['curves']['all'].cumulative_return.iloc[-1],0)
        self.assertAlmostEqual(account['curves']['all'].nav.iloc[-1],.99)
        for fn,col in [(run_simple,'cumulative_return'),(run_account,'nav')]:
            a=fn(t,d,s,True)['curves']['rebalance'];b=fn(t,d,s,False)['curves']['rebalance']
            np.testing.assert_allclose(a[col],b[col])

    def test_exact_fees_cash_balance_and_capital_scale(self):
        values,cash,delta,k=rebalance_weights([0,0],[.5,.5],.01)
        self.assertAlmostEqual(k,.01/1.01);self.assertAlmostEqual(values.sum()+cash+k,1)
        d=market();s=spec(transaction_cost_rate=.01);t=targets(d,[.5,.5,0,0])
        a=run_account(t,d,s);s['initial_capital']=1000000;b=run_account(t,d,s)
        np.testing.assert_allclose(a['curves']['all'].nav,b['curves']['all'].nav)
        self.assertAlmostEqual(a['curves']['all'].nav.iloc[-1],1/1.01)
        self.assertAlmostEqual(b['turnover'].cost_amount.sum(),1000000*.01/1.01)
        self.assertGreaterEqual(b['curves']['all'].cash.min(),0)

    def test_turnover_uses_drift_and_cost_both_sides(self):
        d=market();d.quote['S_DQ_ADJCLOSE'].iloc[5:,0]=200;s=spec();t=targets(d,[.5,.5,0,0])
        a=run_account(t,d,s);turn=a['turnover'].iloc[1]
        self.assertAlmostEqual(turn.buy_turnover,1/6);self.assertAlmostEqual(turn.sell_turnover,1/6)
        self.assertAlmostEqual(turn.turnover,1/6)
        v,cash,delta,k=rebalance_weights([1,0],[0,1],.01)
        self.assertAlmostEqual(k,.02/1.01);self.assertAlmostEqual(k,.01*abs(delta).sum())

    def test_simple_and_account_period_returns_match_with_fees(self):
        d=market();d.quote['S_DQ_ADJCLOSE'].iloc[5:10]=[120,90,105,100];d.quote['S_DQ_ADJCLOSE'].iloc[10:]=[99,108,103,102]
        t=targets(d,[.5,.5,0,0]);t.iloc[1]=[0,0,.5,.5];s=spec(transaction_cost_rate=.003)
        a=run_simple(t,d,s)['curves']['rebalance'];b=run_account(t,d,s)['curves']['rebalance']
        np.testing.assert_allclose(a.cumulative_return.diff().dropna(),b.nav.pct_change().dropna(),atol=1e-12)

    def test_hold_keeps_actual_positions(self):
        d=market();d.quote['S_DQ_ADJCLOSE'].iloc[5:,0]=200;t=targets(d,[.5,.5,0,0]);t.iloc[1:]=np.nan
        a=run_account(t,d,spec());self.assertEqual(len(a['turnover']),1)
        self.assertAlmostEqual(a['holdings'].iloc[-2].weight,2/3)

    def test_empty_groups_cash_hold_and_initial_entry(self):
        d=market();x=panel(d);s=spec();s['grouping']['quantile_edges']=[[.99,1]]
        b=build_targets(x,d,s,1);self.assertTrue((b['targets']['G01']==0).all().all())
        self.assertEqual(run_account(b['targets']['G01'],d,s)['curves']['all'].nav.iloc[-1],1)
        s['empty_group_policy']='hold';self.assertTrue(build_targets(x,d,s,1)['targets']['G01'].isna().all().all())
        s['start']='2021-01-04';s['initial_entry']='start'
        self.assertEqual(build_targets(x,d,s,1)['dates'][0],pd.Timestamp('2021-01-04'))
        s['initial_entry']='first_rebalance';self.assertEqual(build_targets(x,d,s,1)['dates'][0],pd.Timestamp('2021-01-08'))

    def test_open_execution_and_terminal_liquidation(self):
        d=market();d.quote['S_DQ_ADJCLOSE'].iloc[:]=110;s=spec(trade_price='open',transaction_cost_rate=.01,liquidate_at_end=True)
        a=run_account(targets(d,[1,0,0,0]),d,s)
        self.assertAlmostEqual(a['curves']['daily'].nav.iloc[1],1.1/1.01)
        self.assertAlmostEqual(a['curves']['all'].cash_weight.iloc[-1],1)
        self.assertTrue((a['trades'].side=='sell').any())

    def test_tradability_freezes_blocked_position(self):
        d=market();s=spec();s['execution']['policy']='tradability';t=targets(d,[1,0,0,0]);t.iloc[1:]=[0,1,0,0]
        d.quote['S_DQ_TRADESTATUS'].iloc[5:,0]='停牌'
        a=run_account(t,d,s);self.assertTrue((a['trades'].reason=='suspended').any())
        self.assertEqual(set(a['holdings'].code),{'S0'});self.assertGreaterEqual(a['curves']['all'].cash.min(),0)
        with self.assertRaises(ValueError):validate_stage(s,'simple_backtest')

    def test_metrics_gross_net_turnover_and_defined_drawdown(self):
        d=market();d.quote['S_DQ_ADJCLOSE'].iloc[5:10]=110;d.quote['S_DQ_ADJCLOSE'].iloc[10:]=99
        s=spec(transaction_cost_rate=.01);z=deepcopy(s);z['transaction_cost_rate']=0;t=targets(d,[1,0,0,0])
        for mode,fn in [('simple',run_simple),('account',run_account)]:
            m=calculate(fn(t,d,s),fn(t,d,z),mode,s,deepcopy(METRICS),1)
            self.assertGreater(m['gross_total_return'],m['net_total_return'])
            self.assertLess(m['max_drawdown'],0);self.assertEqual(m['total_return'],m['net_total_return'])
            self.assertEqual(m['drawdown_method'],'additive_return_points' if mode=='simple' else 'relative_nav')


if __name__=='__main__':unittest.main()
