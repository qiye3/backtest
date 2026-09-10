"""选择模块运行；按因子分配并行任务，每个模块保存自己的分组与配置结果。"""
from __future__ import annotations
from concurrent.futures import ProcessPoolExecutor,ThreadPoolExecutor,as_completed
from copy import deepcopy
from pathlib import Path
import hashlib
import json
import re
import shutil
import traceback
import numpy as np
import pandas as pd
import yaml
from src.config import load_config,Config
from src.data.factor_input import sources,read_panel,panel_from_frame
from src.data.market import load_stage_market

_MARKET_CACHE={}


def _market(cfg,stage):
    # 每个工作进程复用阶段行情，不在每个区间/调仓周期重新读CSV。
    key=json.dumps([str(cfg.path),cfg.raw['data'],cfg.raw[stage]],sort_keys=True,default=str)
    if key not in _MARKET_CACHE:_MARKET_CACHE[key]=load_stage_market(cfg,stage,stage!='group_return')
    return _MARKET_CACHE[key]


def _save_table(frame,path,index=False):
    if len(frame.columns)==0:frame=pd.DataFrame(columns=['date'])
    frame.to_csv(path,index=index,compression='gzip' if str(path).endswith('.gz') else None)


def _stage_dir(folder,stage):
    out=folder/stage
    if out.exists():shutil.rmtree(out)
    out.mkdir(parents=True)
    return out


def _metadata(out,cfg,stage,input_hash):
    meta=dict(format_version=5,module=stage,input_sha256=input_hash,data=cfg.raw['data'],config=cfg.raw[stage])
    (out/'meta.json').write_text(json.dumps(meta,ensure_ascii=False,indent=2,default=str),encoding='utf-8')
    (out/'resolved_config.yaml').write_text(yaml.safe_dump(cfg.raw[stage],allow_unicode=True,sort_keys=False),encoding='utf-8')


def run_one_factor(cfg,factor_id,panel,input_hash='in_memory'):
    """公共Python入口：panel为日期×股票，不要求知道Factor来源或构造方法。"""
    from src.group_return.evaluator import evaluate
    from src.backtest.targets import build_targets,target_table
    from src.backtest.simple import run_simple
    from src.backtest.account import run_account
    from src.backtest.metrics import calculate
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]*',factor_id):raise ValueError('unsafe factor id')
    panel=panel_from_frame(panel)
    if input_hash=='in_memory':input_hash=hashlib.sha256(panel.to_csv().encode()).hexdigest()
    folder=cfg.output_dir/factor_id;folder.mkdir(parents=True,exist_ok=True)
    (folder/'error.txt').unlink(missing_ok=True)
    selected_dates=pd.DatetimeIndex([]);executed=[]
    alignment=cfg.raw['factor_input']['alignment']
    for stage in ['group_return','simple_backtest','account_backtest']:
        if stage not in cfg.modules:continue
        s=cfg.raw[stage]
        if s['factor_ids'] and factor_id not in s['factor_ids']:continue
        data=_market(cfg,stage)
        if stage=='group_return':
            result=evaluate(panel,data,s,alignment);out=_stage_dir(folder,stage)
            for key in ['summary','ic_summary','definitions']:_save_table(result[key],out/f'{key}.csv')
            for key in ['detail','ic','labels']:_save_table(result[key],out/f'{key}.csv.gz')
            if cfg.raw['output']['save_group_members']:_save_table(result['members'],out/'members.csv.gz')
            selected_dates=selected_dates.union(pd.DatetimeIndex(result['ic'].factor_date.unique()))
        else:
            out=_stage_dir(folder,stage);metrics=[];runners={'simple_backtest':run_simple,'account_backtest':run_account};runner=runners[stage]
            mode='simple' if stage=='simple_backtest' else 'account'
            need_daily=s['curve_frequency'] in {'daily','both'} or cfg.raw['metrics']['return_frequency']=='daily'
            # 绘图是可选模块；单独运行回测不会隐式调用绘图，也不因绘图选项改变估值频率。
            if 'plotting' in cfg.modules and cfg.raw['plots']['enabled'] and cfg.raw['plots']['curve_frequency']=='daily':need_daily=True
            for weeks in s['rebalance']['intervals_weeks']:
                targets=build_targets(panel,data,s,weeks,alignment);selected_dates=selected_dates.union(pd.DatetimeIndex(targets['actions'].factor_date.unique()))
                wd=out/f'W{weeks}';wd.mkdir()
                _save_table(targets['definitions'],wd/'definitions.csv');_save_table(targets['actions'],wd/'actions.csv.gz')
                if cfg.raw['output']['save_group_members']:_save_table(targets['members'],wd/'members.csv.gz')
                if cfg.raw['output']['save_target_weights']:_save_table(target_table(targets['targets'],factor_id,weeks),wd/'target_weights.csv.gz')
                for rec in targets['definitions'].itertuples(index=False):
                    result=runner(targets['targets'][rec.group_id],data,s,need_daily)
                    if s['transaction_cost_rate']==0:gross=result
                    else:
                        zero=deepcopy(s);zero['transaction_cost_rate']=0.;gross=runner(targets['targets'][rec.group_id],data,zero,need_daily)
                    gd=wd/rec.group_id;gd.mkdir()
                    for freq in ['daily','rebalance']:
                        if freq=='daily' and not need_daily:continue
                        frame=result['curves'][freq].copy();other=gross['curves'][freq]
                        if mode=='simple':frame['gross_cumulative_return']=other.cumulative_return.to_numpy()
                        else:frame['gross_nav']=other.nav.to_numpy()
                        _save_table(frame,gd/f'curves_{freq}.csv.gz')
                    _save_table(result['turnover'],gd/'turnover.csv.gz')
                    if cfg.raw['output']['save_trades']:_save_table(result['trades'],gd/'trades.csv.gz')
                    if mode=='account' and cfg.raw['output']['save_holdings']:_save_table(result['holdings'],gd/'holdings.csv.gz')
                    metric=calculate(result,gross,mode,s,cfg.raw['metrics'],weeks)
                    metric.update(factor_id=factor_id,group_id=rec.group_id,quantile_lower=rec.quantile_lower,quantile_upper=rec.quantile_upper,
                        label=rec.label,rebalance_weeks=weeks,mode=mode,transaction_cost_rate=s['transaction_cost_rate'])
                    metrics.append(metric)
            frame=pd.DataFrame(metrics)
            evidence=folder/'group_return/ic_summary.csv';meta=folder/'group_return/meta.json'
            # 附带IC时保留评价区间与总体范围；禁止沿用另一个因子文件的旧IC。
            if evidence.exists() and meta.exists() and json.loads(meta.read_text())['input_sha256']==input_hash:
                for row in pd.read_csv(evidence).itertuples(index=False):
                    if row.horizon_days not in cfg.raw['metrics']['ic_horizons']:continue
                    for name in ['ic_mean','ic_std','icir','rank_ic_mean','rank_ic_std','rank_icir','start','end','ic_scope']:
                        frame[f'{name}_{row.horizon_days}d']=getattr(row,name)
            _save_table(frame,out/'metrics.csv')
        _metadata(out,cfg,stage,input_hash);executed.append(stage)
    if len(selected_dates):
        # 分布样本只取运行日期并集，每日每只股票至多一次；显示抽样不改变计算数据。
        sample=panel.reindex(selected_dates if alignment=='exact' else panel.index.intersection(selected_dates))
        if alignment=='asof':sample=panel.reindex(selected_dates,method='ffill')
        sample.to_csv(folder/'factor_sample.csv.gz',index_label='date',compression='gzip')
    (folder/'factor_input.json').write_text(json.dumps(dict(factor_id=factor_id,input_sha256=input_hash,modules=executed),indent=2))
    if 'plotting' in cfg.modules and cfg.raw['plots']['enabled']:
        from src.plotting.report import plot_factor
        plot_factor(folder,factor_id,cfg.raw['plots']);executed.append('plotting')
    return dict(factor_id=factor_id,status='succeeded',modules=','.join(executed),error='')


def _worker(path,raw,modules,item):
    cfg=Config(Path(path),raw,modules,[])
    try:
        panel=read_panel(item['path'],raw['factor_input']['date_column'])
        digest=hashlib.sha256(Path(item['path']).read_bytes()).hexdigest()
        return run_one_factor(cfg,item['id'],panel,digest)
    except Exception as error:
        folder=cfg.output_dir/item['id'];folder.mkdir(parents=True,exist_ok=True)
        (folder/'error.txt').write_text(traceback.format_exc(),encoding='utf-8')
        return dict(factor_id=item['id'],status='failed',modules='',error=str(error))


def run_pipeline(config_path,modules=None):
    cfg=load_config(config_path,modules);cfg.output_dir.mkdir(parents=True,exist_ok=True)
    (cfg.output_dir/'resolved_config.yaml').write_text(yaml.safe_dump(cfg.raw,allow_unicode=True,sort_keys=False),encoding='utf-8')
    if 'factors' in cfg.modules:
        from src.factors.builder import generate_factors
        f={**cfg.raw['factors'],'values_dir':str(cfg.resolve(cfg.raw['factors']['values_dir']))}
        print('[factors] generating standard Factor values',flush=True)
        generate_factors(cfg.resolve(cfg.raw['data']['root']),f,cfg.factor_configs)
    stages=set(cfg.modules)&{'group_return','simple_backtest','account_backtest'}
    if not stages:
        if 'plotting' in cfg.modules and cfg.raw['plots']['enabled']:
            from src.plotting.report import plot_factor
            folders=sorted(p for p in cfg.output_dir.iterdir() if p.is_dir() and (p/'factor_input.json').exists())
            if not folders:raise ValueError('no saved factor results to plot')
            for folder in folders:plot_factor(folder,folder.name,cfg.raw['plots'])
        return pd.DataFrame()
    items=sources(cfg)
    for stage in stages:
        missing=set(cfg.raw[stage]['factor_ids'])-{i['id'] for i in items}
        if missing:raise ValueError(f'{stage} requests unavailable factors {missing}')
    parallel=cfg.raw['parallel'];results=[]
    if parallel['enabled'] and len(items)>1:
        Executor=ProcessPoolExecutor if parallel['backend']=='process' else ThreadPoolExecutor
        with Executor(max_workers=parallel['workers']) as executor:
            futures=[executor.submit(_worker,str(cfg.path),cfg.raw,cfg.modules,item) for item in items]
            for future in as_completed(futures):
                result=future.result();results.append(result);print(f"[{result['status']}] {result['factor_id']}",flush=True)
                if result['status']=='failed' and parallel['on_error']=='stop':
                    for f in futures:f.cancel()
                    break
    else:
        for item in items:
            result=_worker(str(cfg.path),cfg.raw,cfg.modules,item);results.append(result);print(f"[{result['status']}] {result['factor_id']}",flush=True)
            if result['status']=='failed' and parallel['on_error']=='stop':break
    frame=pd.DataFrame(results).sort_values('factor_id');frame.to_csv(cfg.output_dir/'run_status.csv',index=False)
    if (frame.status=='failed').any():raise RuntimeError(f"{int((frame.status=='failed').sum())} factor task(s) failed; see {cfg.output_dir/'run_status.csv'}")
    return frame
