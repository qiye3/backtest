"""调仓周期分面曲线；简易基准同步累加，账户基准保持复合净值。"""
from pathlib import Path
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
from matplotlib.ticker import PercentFormatter
from src.plotting.style import colors,finish,axis_style,title,date_axis,group_labels


_METRIC_LABELS={
    'annual_return':'Annual return','annual_volatility':'Annual volatility','sharpe':'Sharpe',
    'max_drawdown':'Max drawdown','annual_turnover':'Annual turnover','annual_cost_rate':'Annual cost rate',
    'total_cost_rate':'Total cost rate','net_total_return':'Net total return','gross_total_return':'Gross total return',
    'benchmark_total_return':'Benchmark return','excess_total_return':'Excess return',
    'tracking_error':'Tracking error','information_ratio':'Information ratio'}
_PERCENT_METRICS={'annual_return','annual_volatility','max_drawdown','annual_cost_rate','total_cost_rate',
                  'net_total_return','gross_total_return','benchmark_total_return','excess_total_return','tracking_error'}


def _format_metric(name,value):
    if pd.isna(value):return 'N/A'
    if name in _PERCENT_METRICS:return f'{value:.1%}'
    if name=='annual_turnover':return f'{value:.2f}x'
    return f'{value:.2f}'


def _summary_rows(metrics,periods,spec):
    lo,hi=map(float,spec['summary_quantile']);rows=[]
    for path in periods:
        weeks=int(path.name[1:])
        selected=metrics[(metrics.rebalance_weeks==weeks)&np.isclose(metrics.quantile_lower,lo)&np.isclose(metrics.quantile_upper,hi)]
        values=selected.iloc[0] if len(selected)==1 else None
        rows.append([f'{weeks} week(s)',*[_format_metric(name,values[name]) if values is not None else 'N/A' for name in spec['metric_columns']]])
    return rows


def _summary_group_label(summary_quantile):
    lo,hi=map(float,summary_quantile)
    if np.isclose(lo,.9) and np.isclose(hi,1):return 'q0.1 / Q10'
    return f'quantile [{lo:.2f}, {hi:.2f}]'


def plot_backtest(folder,factor_id,mode,settings,out):
    root=folder/('simple_backtest' if mode=='simple' else 'account_backtest')
    if not root.exists():return False
    periods=sorted([p for p in root.glob('W*') if p.is_dir()],key=lambda p:int(p.name[1:]))
    if not periods:return False
    spec=settings[mode];freq=settings['curve_frequency'];n=len(periods)
    table_ax=None
    if mode=='simple':
        fig=plt.figure(figsize=(settings['width'],settings['row_height']*n+1.8),layout='constrained')
        grid=fig.add_gridspec(n+1,1,height_ratios=[1]*n+[.45])
        plot_axes=[fig.add_subplot(grid[i,0]) for i in range(n)];table_ax=fig.add_subplot(grid[n,0])
    else:
        rows,cols=(n,1) if spec['layout']=='rows' else (1,n)
        fig,axes=plt.subplots(rows,cols,figsize=(settings['width'] if cols==1 else settings['width']*1.4,settings['row_height']*rows+.7),squeeze=False,layout='constrained')
        plot_axes=list(axes.flat)
    title(fig,f'{factor_id} | '+('Simple cumulative returns' if mode=='simple' else 'Independent account NAV'),settings)
    legend_handles=None;legend_labels=None
    for ax,path in zip(plot_axes,periods):
        defs=pd.read_csv(path/'definitions.csv');palette=colors(spec['group_colors'],len(defs));benchmark=None
        labels,deciles=group_labels(defs);handles=[]
        for j,rec in enumerate(defs.itertuples(index=False)):
            file=path/rec.group_id/f'curves_{freq}.csv.gz'
            if not file.exists():
                plt.close(fig);raise ValueError(f'{file} unavailable; regenerate this module with daily curves/metrics or plot rebalance curves')
            f=pd.read_csv(file,parse_dates=['timestamp'])
            key='cumulative_return' if mode=='simple' else 'nav'
            lw=1.65 if mode=='simple' and j in {0,len(defs)-1} else 1.15 if mode=='simple' else 1.3
            line,=ax.plot(f.timestamp,f[key],color=palette[j],lw=lw,
                          ls='-' if mode=='simple' else ['-','--','-.',':'][j%4],label=labels[j])
            handles.append(line)
            if benchmark is None:benchmark=f
        bkey='benchmark_cumulative_return' if mode=='simple' else 'benchmark_nav'
        benchmark_line,=ax.plot(benchmark.timestamp,benchmark[bkey],color=spec['benchmark_color'],lw=1.9,
                                ls='--' if mode=='simple' else '-',label='Benchmark',zorder=5)
        handles.append(benchmark_line)
        ax.axhline(0 if mode=='simple' else 1,color='#555555',lw=.6)
        if mode=='simple':ax.yaxis.set_major_formatter(PercentFormatter(1))
        ax.set_ylabel('Cumulative return (sum)' if mode=='simple' else 'NAV (initial = 1)')
        ax.set_title(f'Every {path.name[1:]} week(s) | {freq} observations | after costs',fontsize=10)
        if mode=='simple':
            if legend_handles is None:legend_handles,legend_labels=handles,[h.get_label() for h in handles]
        else:ax.legend(loc='upper left',bbox_to_anchor=(0,-.17),ncol=min(settings['legend_columns'],len(defs)+1),frameon=False,fontsize=8)
        axis_style(ax);date_axis(ax)
    if mode=='simple':
        fig.legend(legend_handles,legend_labels,loc='upper center',bbox_to_anchor=(.5,.945),
                   ncol=min(11,len(legend_handles)),frameon=False,fontsize=8)
        metrics=pd.read_csv(root/'metrics.csv')
        table_ax.axis('off')
        table_ax.set_title(f'{_summary_group_label(spec["summary_quantile"])} summary | displayed metrics are configurable',loc='left',fontsize=9,pad=6)
        columns=['Rebalance',*[_METRIC_LABELS[name] for name in spec['metric_columns']]]
        table=table_ax.table(cellText=_summary_rows(metrics,periods,spec),colLabels=columns,loc='center',cellLoc='center')
        table.auto_set_font_size(False);table.set_fontsize(8);table.scale(1,1.25)
        for (row,_),cell in table.get_celld().items():
            cell.set_facecolor('white');cell.set_edgecolor('#263238');cell.set_linewidth(.55)
            if row==0:cell.set_text_props(fontweight='bold')
    finish(fig,out/('02_simple_backtest' if mode=='simple' else '03_account_backtest'),settings);return True
