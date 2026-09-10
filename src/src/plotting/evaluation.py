"""每个预测周期一行：分组聚合收益与完整有效截面的IC/RankIC序列。"""
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
from matplotlib.ticker import PercentFormatter
from src.plotting.style import colors,finish,axis_style,title,date_axis,group_labels


def plot_evaluation(folder,factor_id,settings,out):
    path=folder/'group_return'
    if not (path/'summary.csv').exists():return False
    summary=pd.read_csv(path/'summary.csv');ics=pd.read_csv(path/'ic.csv.gz',parse_dates=['date']);defs=pd.read_csv(path/'definitions.csv')
    horizons=list(summary.horizon_days.unique());spec=settings['evaluation'];palette=colors(spec['group_colors'],len(defs))
    fig,axes=plt.subplots(len(horizons),2,figsize=(settings['width'],settings['row_height']*len(horizons)+.5),
                          squeeze=False,layout='constrained',gridspec_kw={'width_ratios':[1,1]})
    title(fig,f'{factor_id} | Forward-return evaluation',settings)
    for row,h in enumerate(horizons):
        bar=axes[row,0 if spec['group_panel']=='left' else 1];line=axes[row,1 if spec['group_panel']=='left' else 0]
        g=summary[summary.horizon_days==h].set_index('group_id').reindex(defs.group_id)
        bars=bar.bar(np.arange(len(defs)),g.group_return,color=palette,width=.8)
        labels,deciles=group_labels(defs)
        bar.set_xticks(np.arange(len(defs)),labels,rotation=35 if not deciles and len(defs)>6 else 0,
                       ha='right' if not deciles and len(defs)>6 else 'center',fontsize=8)
        bar.yaxis.set_major_formatter(PercentFormatter(1));bar.axhline(0,color='#555555',lw=.7)
        bar.set_title(f'{h} trading days | groups: {g.group_return_agg.iloc[0]}, dates: {g.time_return_agg.iloc[0]}',fontsize=10)
        bar.set_ylabel('Aggregated forward return')
        missing=g.group_return.isna().to_numpy()
        for j in np.flatnonzero(missing):bar.text(j,0,'N/A',ha='center',va='bottom',fontsize=8)
        finite=g.group_return.dropna().abs()
        offset=max(float(finite.max()) if len(finite) else 0.,.002)*.045
        for rect,value in zip(bars,g.group_return):
            if pd.notna(value):bar.text(rect.get_x()+rect.get_width()/2,value+offset,f'{value:.2%}',ha='center',va='bottom',fontsize=7)
        c=ics[ics.horizon_days==h]
        line.plot(c.date,c.ic,label='IC (Pearson)',color=spec['ic_color'],lw=1.2,marker='o',ms=2.)
        line.plot(c.date,c.rank_ic,label='RankIC (Spearman)',color=spec['rank_ic_color'],lw=1.4)
        line.axhline(0,color='#555555',lw=.7);line.set_ylim(-1.05,1.05)
        line.set_title(f'{h} trading days | full valid stock universe',fontsize=10);line.set_ylabel('Correlation')
        line.legend(loc='upper right',frameon=False,ncol=2,fontsize=8)
        axis_style(bar);axis_style(line);date_axis(line)
    finish(fig,out/'01_evaluation',settings);return True
