"""只读取已保存结果绘图；不重新估算收益、IC、换手或成本。"""
import json
from pathlib import Path
import threading
import matplotlib.pyplot as plt
from src.plotting.distribution import plot_distribution
from src.plotting.evaluation import plot_evaluation
from src.plotting.backtest import plot_backtest
_LOCK=threading.RLock()


def plot_factor(folder,factor_id,settings):
    if not settings['enabled']:return []
    folder=Path(folder);out=folder/'figures';out.mkdir(exist_ok=True)
    current=folder/'factor_input.json'
    fingerprint=json.loads(current.read_text()).get('input_sha256') if current.exists() else None
    # 不把同名因子的旧输入结果画成新输入的表现。
    for module in ['group_return','simple_backtest','account_backtest']:
        p=folder/module/'meta.json'
        if p.exists() and fingerprint and json.loads(p.read_text())['input_sha256']!=fingerprint:raise ValueError(f'stale {module} results for {factor_id}; regenerate or remove that module output')
    made=[]
    with _LOCK,plt.rc_context({'font.family':settings['font_family'],'axes.labelsize':10,'xtick.labelsize':8,'ytick.labelsize':9}):
        actions=[('distribution',lambda:plot_distribution(folder,factor_id,settings,out)),
                 ('evaluation',lambda:plot_evaluation(folder,factor_id,settings,out)),
                 ('simple',lambda:plot_backtest(folder,factor_id,'simple',settings,out)),
                 ('account',lambda:plot_backtest(folder,factor_id,'account',settings,out))]
        for name,action in actions:
            if not settings[name]['enabled']:continue
            if action():made.append(name)
            elif settings['missing_results']=='error':raise ValueError(f'missing {name} results for {factor_id}')
    (out/'plot_config.json').write_text(json.dumps(settings,ensure_ascii=False,indent=2),encoding='utf-8')
    return made
