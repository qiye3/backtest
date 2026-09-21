"""评价图共享分组规模表的回归测试。"""

from __future__ import annotations

import unittest
from pathlib import Path
from unittest.mock import patch

import matplotlib.pyplot as plt
import pandas as pd

from src.plotter.evaluation import (
    _shared_mean_group_sizes,
    plot_evaluation,
)


class EvaluationPlotTest(unittest.TestCase):
    """验证多预测周期只展示一份不重复的分组规模统计。"""

    def setUp(self) -> None:
        self.definitions = pd.DataFrame(
            {
                "group_id": [0, 1],
                "label": ["G1", "G2"],
            }
        )
        dates = pd.to_datetime(["2026-01-02", "2026-01-09"])
        detail_records = []
        for date, sizes in zip(dates, ([10, 12], [14, 16])):
            for horizon in (1, 2):
                for group_id, size in enumerate(sizes):
                    detail_records.append(
                        {
                            "date": date,
                            "horizon_value": horizon,
                            "horizon_unit": "weeks",
                            "group_id": group_id,
                            "n_group_stocks": size,
                        }
                    )
        self.detail = pd.DataFrame(detail_records)

    def test_shared_sizes_ignore_repeated_horizons(self) -> None:
        """同一日期的股票数不应因预测周期数量而重复计权。"""
        mean_sizes = _shared_mean_group_sizes(self.detail, self.definitions)
        pd.testing.assert_series_equal(
            mean_sizes,
            pd.Series(
                [12.0, 14.0],
                index=pd.Index([0, 1], name="group_id"),
                name="n_group_stocks",
            ),
        )

    def test_multiple_horizons_draw_one_shared_table(self) -> None:
        """多预测周期评价图底部只调用一次共享表格。"""
        summary = pd.DataFrame(
            [
                {
                    "horizon_value": horizon,
                    "horizon_unit": "weeks",
                    "group_id": group_id,
                    "group_return": 0.01 * (group_id + 1),
                    "group_return_agg": "mean",
                    "time_return_agg": "mean",
                }
                for horizon in (1, 2)
                for group_id in (0, 1)
            ]
        )
        ic = pd.DataFrame(
            [
                {
                    "date": date,
                    "horizon_value": horizon,
                    "horizon_unit": "weeks",
                    "ic": 0.1,
                    "rank_ic": 0.2,
                }
                for horizon in (1, 2)
                for date in pd.to_datetime(["2026-01-02", "2026-02-06"])
            ]
        )
        settings = {
            "width": 10.0,
            "row_height": 3.0,
            "note": "",
            "evaluation": {
                "group_panel": "left",
                "group_colors": ["#ff0000", "#00aa00"],
                "ic_color": "#D06A2D",
                "rank_ic_color": "#174A73",
                "rank_ic_view": "monthly",
            },
        }
        with (
            patch("matplotlib.axes.Axes.table", autospec=True) as table,
            patch(
                "src.plotter.evaluation.save_figure",
                side_effect=lambda figure, *_: (
                    plt.close(figure),
                    [Path("x.png")],
                )[1],
            ),
        ):
            plot_evaluation(
                "factor",
                {
                    "definitions": self.definitions,
                    "summary": summary,
                    "ic": ic,
                    "detail": self.detail,
                },
                settings,
                Path("evaluation"),
            )
        self.assertEqual(table.call_count, 1)


if __name__ == "__main__":
    unittest.main()
