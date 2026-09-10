"""静态图通用样式，用户的红绿顺序优先；用线型和明确区间标签辅助区分。"""
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.dates as mdates


def date_axis(ax):
    """每行最多六个日期刻度，避免多个预测周期的窄面板标签重叠。"""
    locator=mdates.AutoDateLocator(minticks=3,maxticks=6)
    ax.xaxis.set_major_locator(locator)
    ax.xaxis.set_major_formatter(mdates.ConciseDateFormatter(locator))
from matplotlib.colors import LinearSegmentedColormap
import numpy as np


def colors(spec,n):
    cmap=LinearSegmentedColormap.from_list('groups',spec)
    return [cmap(v) for v in np.linspace(0,1,n)]


def group_labels(defs):
    """标准十等分用简洁Q标签；自定义或重叠区间保留完整百分位边界。"""
    if len(defs)==10:
        expected=np.column_stack((np.arange(10)/10,(np.arange(10)+1)/10))
        if np.allclose(defs[['quantile_lower','quantile_upper']].to_numpy(float),expected):
            return [f'Q{i+1}' for i in range(10)],True
    return defs.label.tolist(),False


def finish(fig,path,settings):
    for ext in settings['formats']:fig.savefig(str(path)+'.'+ext,dpi=settings['dpi'],bbox_inches='tight',facecolor='white')
    plt.close(fig)


def axis_style(ax):
    ax.spines[['top','right']].set_visible(False);ax.grid(axis='y',alpha=.18);ax.set_axisbelow(True)


def title(fig,text,settings):
    subtitle='\n'+settings['note'] if settings['note'] else ''
    fig.suptitle(text+subtitle,fontsize=14,fontweight='bold')
