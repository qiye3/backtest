"""跨因子分布与四周分组收益汇总图测试。"""

from __future__ import annotations

import unittest
from pathlib import Path
from unittest.mock import patch

import matplotlib.pyplot as plt
import pandas as pd
from matplotlib.colors import to_rgba

from src.plotter.overall import (
    _sample_evaluation_factor_panel,
    plot_factor_distribution_grid,
    plot_group_return_grid,
    plot_overall_evaluation,
)


class OverallPlotTest(unittest.TestCase):
    """验证跨因子汇总图的数据口径、布局和开关。"""

    def setUp(self) -> None:
        self.settings = {
            "formats": ["png"],
            "dpi": 60,
            "width": 13.0,
            "row_height": 3.4,
            "font_family": "DejaVu Sans",
            "note": "",
            "evaluation": {
                "group_colors": ["#A50026", "#006837"],
            },
            "distribution": {
                "bins": 10,
                "density": False,
                "kde": False,
                "clip_quantiles": None,
                "max_points": 100,
            },
            "overall": {
                "factor_distribution_grid": {
                    "enabled": False,
                    "columns": 5,
                },
                "group_return_grid": {
                    "enabled": True,
                    "columns": 5,
                    "share_y_axis": True,
                }
            },
        }

    def test_grid_uses_four_weeks_and_hides_unused_axes(self) -> None:
        """六个因子应排成两行五列，只绘制其四周收益。"""
        evaluation_results = {
            f"factor_{position}": self._evaluation_result(position + 1)
            for position in range(6)
        }
        captured_figures = []
        with patch(
            "src.plotter.overall.save_figure",
            side_effect=lambda figure, *_: (
                captured_figures.append(figure),
                [Path("group_return_4week_grid.png")],
            )[1],
        ):
            output_paths = plot_group_return_grid(
                evaluation_results,
                self.settings,
                Path("group_return_4week_grid"),
            )

        figure = captured_figures[0]
        visible_axes = [axis for axis in figure.axes if axis.get_visible()]
        self.assertEqual(output_paths, [Path("group_return_4week_grid.png")])
        self.assertEqual(len(figure.axes), 10)
        self.assertEqual(len(visible_axes), 6)
        self.assertEqual(
            [bar.get_height() for bar in visible_axes[0].patches],
            [0.01, 0.02],
        )
        self.assertEqual(
            visible_axes[0].patches[-1].get_facecolor(),
            to_rgba("#006837"),
        )
        self.assertTrue(
            all(axis.get_ylim() == visible_axes[0].get_ylim() for axis in visible_axes)
        )
        self.assertTrue(
            visible_axes[0].yaxis.get_major_formatter()(0.01, 0).endswith("bp")
        )
        plt.close(figure)

    def test_distribution_grid_uses_five_columns(self) -> None:
        """六个因子分布应排成两行五列，并隐藏四个空坐标轴。"""
        dates = pd.to_datetime(["2026-01-02", "2026-01-09"])
        factor_panels = {
            f"factor_{position}": pd.DataFrame(
                [[position, position + 1], [position + 2, position + 3]],
                index=dates,
            )
            for position in range(6)
        }
        evaluation_results = {
            factor_name: {
                "detail": pd.DataFrame({"factor_date": [dates[-1]]})
            }
            for factor_name in factor_panels
        }
        captured_figures = []
        with patch(
            "src.plotter.overall.save_figure",
            side_effect=lambda figure, *_: (
                captured_figures.append(figure),
                [Path("factor_distribution_grid.png")],
            )[1],
        ):
            output_paths = plot_factor_distribution_grid(
                factor_panels=factor_panels,
                evaluation_results=evaluation_results,
                settings=self.settings,
                sampling_settings=None,
                output_stem=Path("factor_distribution_grid"),
            )

        figure = captured_figures[0]
        visible_axes = [axis for axis in figure.axes if axis.get_visible()]
        self.assertEqual(output_paths, [Path("factor_distribution_grid.png")])
        self.assertEqual(len(figure.axes), 10)
        self.assertEqual(len(visible_axes), 6)
        self.assertEqual(visible_axes[0].get_title(), "factor_0")
        self.assertIn("N=2", visible_axes[0].texts[0].get_text())
        plt.close(figure)

    def test_distribution_sampling_uses_evaluation_factor_dates(self) -> None:
        """汇总分布只能使用 evaluation 实际对应的因子来源日。"""
        dates = pd.to_datetime(["2026-01-02", "2026-01-09"])
        factor_panel = pd.DataFrame([[100.0], [1.0]], index=dates)
        sampled_panel = _sample_evaluation_factor_panel(
            factor_panel,
            {"detail": pd.DataFrame({"factor_date": [dates[-1]]})},
        )

        pd.testing.assert_frame_equal(sampled_panel, factor_panel.iloc[[1]])

    def test_grid_can_use_independent_y_axes(self) -> None:
        """关闭共享收益轴后，各因子应按自身收益区间缩放。"""
        self.settings["overall"]["group_return_grid"]["share_y_axis"] = False
        captured_figures = []
        with patch(
            "src.plotter.overall.save_figure",
            side_effect=lambda figure, *_: (
                captured_figures.append(figure),
                [Path("group_return_4week_grid.png")],
            )[1],
        ):
            plot_group_return_grid(
                {
                    "small": self._evaluation_result(1),
                    "large": self._evaluation_result(10),
                },
                self.settings,
                Path("group_return_4week_grid"),
            )

        figure = captured_figures[0]
        self.assertNotEqual(figure.axes[0].get_ylim(), figure.axes[1].get_ylim())
        plt.close(figure)

    def test_disabled_grid_is_not_rendered(self) -> None:
        """关闭开关时 overall 只生成原有三类图。"""
        self.settings["overall"]["group_return_grid"]["enabled"] = False
        self.settings["overall"]["factor_distribution_grid"][
            "enabled"
        ] = False
        with (
            patch(
                "src.plotter.overall._plot_correlation_heatmap",
                return_value=[Path("correlation.png")],
            ),
            patch(
                "src.plotter.overall._plot_factor_distribution",
                return_value=[Path("distribution.png")],
            ),
            patch("src.plotter.overall.plot_group_return_grid") as grid_plot,
            patch(
                "src.plotter.overall.plot_factor_distribution_grid"
            ) as distribution_grid_plot,
        ):
            output_paths = plot_overall_evaluation(
                {
                    "factor_correlation": pd.DataFrame(),
                    "factor_ic": pd.DataFrame(),
                    "factor_return": pd.DataFrame(),
                },
                self.settings,
                Path("00_overall"),
            )

        grid_plot.assert_not_called()
        distribution_grid_plot.assert_not_called()
        self.assertEqual(
            set(output_paths),
            {"factor_correlation", "factor_ic", "factor_return"},
        )

    @staticmethod
    def _evaluation_result(scale: int) -> dict[str, pd.DataFrame]:
        """构造包含干扰周期的两组评价结果。"""
        definitions = pd.DataFrame(
            {"group_id": ["G1", "G10"], "label": ["G1", "G10"]}
        )
        summary = pd.DataFrame(
            [
                {
                    "horizon_value": horizon,
                    "horizon_unit": "weeks",
                    "group_id": group_id,
                    "group_return": value,
                }
                for horizon, values in [(1, [0.99, 0.99]), (4, [0.01, 0.02])]
                for group_id, value in zip(
                    definitions["group_id"],
                    [return_value * scale for return_value in values],
                )
            ]
        )
        return {"definitions": definitions, "summary": summary}


if __name__ == "__main__":
    unittest.main()
