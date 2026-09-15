"""统一因子图表的配色、坐标轴和文件输出样式。"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib.colors import LinearSegmentedColormap


def group_colors(color_spec: Sequence[str], color_count: int) -> list[Any]:
    """颜色数量匹配时保留原色，否则插值成与分组数量一致的序列。"""
    if len(color_spec) == color_count:
        return list(color_spec)
    color_map = LinearSegmentedColormap.from_list("factor_groups", color_spec)
    return [
        color_map(position)
        for position in np.linspace(0.0, 1.0, color_count)
    ]


def group_labels(definitions: pd.DataFrame) -> tuple[list[str], bool]:
    """标准十等分返回 Q1 至 Q10，其他分组保留配置标签。"""
    if len(definitions) == 10:
        expected = np.column_stack(
            (np.arange(10) / 10, (np.arange(10) + 1) / 10)
        )
        boundaries = definitions[
            ["quantile_lower", "quantile_upper"]
        ].to_numpy(dtype=float)
        if np.allclose(boundaries, expected):
            return [f"Q{position + 1}" for position in range(10)], True
    return definitions["label"].tolist(), False


def style_date_axis(axis: plt.Axes) -> None:
    """以完整年月日格式显示自动选取的日期刻度。"""
    locator = mdates.AutoDateLocator(minticks=3, maxticks=6)
    axis.xaxis.set_major_locator(locator)
    axis.xaxis.set_major_formatter(mdates.DateFormatter("%Y-%m-%d"))


def style_axis(axis: plt.Axes) -> None:
    """应用所有图表共享的边框和横向网格。"""
    axis.spines[["top", "right"]].set_visible(False)
    axis.grid(axis="y", alpha=0.18)
    axis.set_axisbelow(True)


def set_figure_title(
    figure: plt.Figure,
    text: str,
    settings: Mapping[str, Any],
) -> None:
    """设置主标题，并在配置存在说明时追加副标题。"""
    subtitle = f"\n{settings['note']}" if settings["note"] else ""
    figure.suptitle(
        text + subtitle,
        fontsize=14,
        fontweight="bold",
    )


def save_figure(
    figure: plt.Figure,
    output_stem: Path,
    settings: Mapping[str, Any],
) -> list[Path]:
    """按配置格式覆盖保存图表并关闭 Matplotlib Figure。"""
    output_stem.parent.mkdir(parents=True, exist_ok=True)
    output_paths = []
    for extension in settings["formats"]:
        output_path = output_stem.with_suffix(f".{extension}")
        figure.savefig(
            output_path,
            dpi=settings["dpi"],
            bbox_inches="tight",
            facecolor="white",
        )
        output_paths.append(output_path)
    plt.close(figure)
    return output_paths
