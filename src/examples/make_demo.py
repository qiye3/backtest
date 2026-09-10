"""生成确定性的虚构行情、财务和外部因子，仅用于验证程序，不代表真实业绩。"""
from pathlib import Path
import argparse
import numpy as np
import pandas as pd
import yaml


def make_demo(directory, stocks=100):
    directory=Path(directory).resolve();root=directory/'data'
    for p in ['stock/daily_quote','stock/financial/indicators','stock/consensus/suntime',
              'index/members','index/prices','index/prices_total_return']:
        (root/p).mkdir(parents=True,exist_ok=True)
    days=pd.bdate_range('2016-01-01','2021-06-30');codes=[f'{i+1:06d}.SZ' for i in range(stocks)]
    rng=np.random.default_rng(508);t=np.arange(len(days))[:,None];j=np.arange(stocks)[None,:]
    signal=np.sin(t/38+j*.35)+.3*np.cos(t/13+j*.9)
    
    # 将可用的前一日信号植入虚构收益；此处用于让图中出现可辨认的差异。
    r=.00012+.0007*np.roll(signal,1,axis=0)+rng.normal(0,.009,(len(days),stocks))
    close=(10+j*.1)*np.cumprod(1+r,axis=0);opening=close/(1+r*.4)
    quotes=pd.DataFrame({'TRADE_DT':np.repeat(days.strftime('%Y%m%d'),stocks),
        'S_INFO_WINDCODE':np.tile(codes,len(days)),'S_DQ_ADJCLOSE':close.ravel(),
        'S_DQ_ADJOPEN':opening.ravel(),'S_DQ_CLOSE':close.ravel(),'S_DQ_OPEN':opening.ravel(),
        'S_DQ_LIMIT':(close*1.1).ravel(),'S_DQ_STOPPING':(close*.9).ravel(),
        'S_DQ_TRADESTATUS':'交易','S_DQ_MV':np.broadcast_to(1e6*(1+j),close.shape).ravel()})
    forecasts=pd.DataFrame({'con_date':quotes.TRADE_DT,'stock_code':quotes.S_INFO_WINDCODE,
        'con_year':np.repeat(days.year,stocks),'con_npgrate_13w':signal.ravel()})
    for frame,date_col,where,prefix in [(quotes,'TRADE_DT','stock/daily_quote','quote'),
                                        (forecasts,'con_date','stock/consensus/suntime','suntime')]:
        for year,g in frame.groupby(frame[date_col].str[:4]):g.to_csv(root/where/f'{prefix}_{year}.csv',index=False)
    records=[]
    for n,rp in enumerate(pd.period_range('2014Q1','2021Q1',freq='Q')):
        date=rp.end_time.normalize();ann=date+pd.Timedelta(days=30)
        for k,code in enumerate(codes):records.append(dict(S_INFO_WINDCODE=code,ANN_DT=ann.strftime('%Y%m%d'),
            ACTUAL_ANN_DT=ann.strftime('%Y%m%d'),REPORT_PERIOD=date.strftime('%Y%m%d'),
            S_QFA_ROE=5+k*.03+.1*n+np.sin(n*.7+k*.35),S_QFA_YOYNETPROFIT=k*.1+n*.5+np.sin(n+k*.35)))
    financial=pd.DataFrame(records)
    for year,g in financial.groupby(financial.REPORT_PERIOD.str[:4]):g.to_csv(root/'stock/financial/indicators'/f'indicators_{year}.csv',index=False)
    for idx,subset in [('000906.SH',codes[:stocks//2]),('000852.SH',codes[stocks//2:])]:
        pd.DataFrame({'s_con_windcode':subset,'s_con_indate':20160101,'s_con_outdate':np.nan}).to_csv(root/'index/members'/f'{idx}.csv',index=False)
    benchmark=100*np.cumprod(1+r[:,:stocks//2].mean(axis=1))
    for where,level in [('prices',benchmark),('prices_total_return',benchmark*np.exp(np.arange(len(days))*.00001))]:
        x=pd.DataFrame({'TRADE_DT':days.strftime('%Y%m%d'),'S_DQ_CLOSE':level,'S_DQ_OPEN':level/(1+r.mean(axis=1)*.4)})
        for year,g in x.groupby(x.TRADE_DT.str[:4]):g.to_csv(root/'index'/where/f'000906.SH_{year}.csv',index=False)
    
    # 示例日历是工作日序列；真实运行应使用交易所交易日历。
    pd.DataFrame({'date':days}).to_csv(root/'calendar.csv',index=False)
    inputs=directory/'inputs';inputs.mkdir(exist_ok=True)
    for name,values in [('my_factor_a',signal),('my_factor_b',-signal)]:
        pd.DataFrame(values,index=days,columns=codes).loc['2019':].to_csv(inputs/f'{name}.csv',index_label='date')
    repo=Path(__file__).resolve().parents[1]
    config=yaml.safe_load((repo/'configs/experiment_v5.yaml').read_text())
    config['experiment']['name']='synthetic_demo_v5';config['data'].update(root=str(root),calendar_path=str(root/'calendar.csv'))
    config['factors'].update(start='2019-01-01',end='2021-06-30',values_dir=str(directory/'factor_values'),
        configs=[str(repo/'configs/factors'/p) for p in ['roe_level.yaml','consensus_13w_revision.yaml']])
    config['factor_input'].update(values_dir=str(directory/'factor_values'),ids=['roe_level.smooth_1d','consensus_13w_revision.smooth_1d'])
    config['group_return'].update(start='2020-01-01',end='2020-12-31')
    for stage in ['group_return','simple_backtest','account_backtest']:
        config[stage]['grouping']['min_stocks']=max(2,stocks//2)
    for stage in ['simple_backtest','account_backtest']:
        config[stage].update(start='2021-01-01',end='2021-06-30',transaction_cost_rate=.001)
    config['parallel']['workers']=2;config['output']['root']=str(directory/'outputs')
    config['plots'].update(formats=['png'],note='SYNTHETIC DATA — program verification only')
    path=directory/'demo.yaml';path.write_text(yaml.safe_dump(config,allow_unicode=True,sort_keys=False),encoding='utf-8')
    
    return path


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--directory',required=True);parser.add_argument('--stocks',type=int,default=100)
    args=parser.parse_args();print(make_demo(args.directory,args.stocks))
