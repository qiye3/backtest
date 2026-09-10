"""原始因子直方图与密度曲线；抽样和裁剪仅作用于显示。"""
import numpy as np
import pandas as pd
from scipy.stats import gaussian_kde
import matplotlib.pyplot as plt
from src.plotting.style import finish,axis_style,title


def plot_distribution(folder,factor_id,settings,out):
    spec=settings['distribution'];p=folder/'factor_sample.csv.gz'
    if not p.exists():return False
    values=pd.read_csv(p,index_col=0).to_numpy(float).ravel();values=values[np.isfinite(values)];total=len(values)
    if not total:raise ValueError('no finite factor values for distribution')
    clip=spec['clip_quantiles']
    if clip is not None:
        lo,hi=np.quantile(values,clip);values=values[(values>=lo)&(values<=hi)]
    if len(values)>spec['max_points']:values=np.random.default_rng(0).choice(values,spec['max_points'],replace=False)
    fig,ax=plt.subplots(figsize=(settings['width'],settings['row_height']*1.5),layout='constrained')
    _,bins,_=ax.hist(values,bins=spec['bins'],density=spec['density'],color='#80A9C5',alpha=.6,edgecolor='white',linewidth=.4,label='Histogram')
    if spec['kde'] and len(values)>=3 and np.std(values)>0:
        grid=np.linspace(bins[0],bins[-1],400);y=gaussian_kde(values)(grid)
        if not spec['density']:y*=len(values)*(bins[1]-bins[0])
        ax.plot(grid,y,color='#163B55',lw=1.8,label='Density' if spec['density'] else 'Scaled density')
    elif spec['kde']:ax.text(.98,.95,'Density unavailable: constant or sparse values',transform=ax.transAxes,ha='right',va='top',fontsize=9)
    title(fig,f'{factor_id} | Factor distribution',settings)
    ax.set_xlabel('Factor value');ax.set_ylabel('Density' if spec['density'] else 'Count')
    ax.set_title(f'{total:,} finite observations; {len(values):,} displayed'+(' | display clipping enabled' if clip else ''),fontsize=10)
    axis_style(ax);ax.legend(frameon=False);finish(fig,out/'00_factor_distribution',settings);return True
