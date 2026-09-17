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
    """返回配置组名，并标记是否适合不旋转地紧凑展示。"""
    labels = definitions["label"].astype(str).tolist()
    compact_labels = len(labels) <= 12 and all(
        len(label) <= 6 for label in labels
    )
    return labels, compact_labels


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
    annotation: str | None = None,
) -> None:
    """设置加粗主标题，并把运行口径作为普通字重标注。"""
    annotation_lines = [
        line
        for line in [annotation, settings["note"]]
        if line
    ]
    if annotation_lines:
        figure_height = float(figure.get_size_inches()[1])
        title_y = 1 - 0.05 / figure_height
        annotation_y = 1 - 0.28 / figure_height
        reserved_height = 0.58 + 0.18 * (len(annotation_lines) - 1)
        content_top = 1 - reserved_height / figure_height
        figure.suptitle(
            text,
            fontsize=14,
            fontweight="bold",
            y=title_y,
        )
        figure.get_layout_engine().set(rect=(0, 0, 1, content_top))
        figure.text(
            0.5,
            annotation_y,
            "\n".join(annotation_lines),
            horizontalalignment="center",
            verticalalignment="top",
            fontsize=9,
            fontweight="normal",
        )
        return
    figure.suptitle(
        text,
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
