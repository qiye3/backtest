"""验证原生日频因子 Parquet 的显式只读输入契约。"""

from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

import numpy as np
import pandas as pd
import yaml

from src.config import load_config
from src.factors.io import (
    find_factor_names,
    load_factor_panel,
    load_factor_parquet,
)

PROJECT_ROOT = Path(__file__).resolve().parents[1]
BASE_CONFIG_PATH = PROJECT_ROOT / "configs" / "base_config.yaml"


class FactorParquetInputTests(unittest.TestCase):
    """覆盖显式文件映射的配置解析、发现和面板校验。"""

    def test_config_resolves_multiple_relative_parquet_files(self) -> None:
        """相对文件路径应按主配置目录解析，并按因子名稳定排序。"""
        with TemporaryDirectory() as temporary_directory:
            workspace = Path(temporary_directory)
            first_path = workspace / "factor_a.parquet"
            second_path = workspace / "factor_b.parquet"
            self._valid_panel().to_parquet(first_path)
            self._valid_panel().to_parquet(second_path)

            config_data = self._base_config(workspace / "output")
            config_data["factors"] = {
                "parquet_files": {
                    "factor_b": second_path.name,
                    "factor_a": first_path.name,
                }
            }
            config_path = workspace / "run.yaml"
            config_path.write_text(
                yaml.safe_dump(config_data, sort_keys=False),
                encoding="utf-8",
            )

            config = load_config(config_path)

            self.assertEqual(
                config.factor_parquet_files,
                {
                    "factor_a": first_path.resolve(),
                    "factor_b": second_path.resolve(),
                },
            )
            self.assertEqual(
                find_factor_names(config.factor_parquet_files),
                ("factor_a", "factor_b"),
            )
            pd.testing.assert_frame_equal(
                load_factor_panel("factor_a", config.factor_parquet_files),
                self._valid_panel(),
            )
            with self.assertRaisesRegex(FileNotFoundError, "没有因子"):
                load_factor_panel("missing", config.factor_parquet_files)

    def test_config_rejects_conflicting_factor_sources(self) -> None:
        """显式文件不能与结果根或本次 Factor 计算同时启用。"""
        with TemporaryDirectory() as temporary_directory:
            workspace = Path(temporary_directory)
            factor_path = workspace / "factor.parquet"
            self._valid_panel().to_parquet(factor_path)
            config_data = self._base_config(workspace / "output")
            config_data["factors"] = {
                "parquet_files": {"demo": str(factor_path)},
                "result_root": str(workspace / "existing"),
            }
            config_path = workspace / "run.yaml"
            config_path.write_text(
                yaml.safe_dump(config_data, sort_keys=False),
                encoding="utf-8",
            )

            with self.assertRaisesRegex(ValueError, "不能同时配置"):
                load_config(config_path)

            config_data["run"]["factors"] = True
            config_data["factors"] = {
                "config_directory": str(
                    PROJECT_ROOT / "examples" / "config" / "base_factors"
                ),
                "parquet_files": {"demo": str(factor_path)},
            }
            config_path.write_text(
                yaml.safe_dump(config_data, sort_keys=False),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ValueError, "run.factors=false"):
                load_config(config_path)

    def test_factor_parquet_validation_rejects_invalid_panels(self) -> None:
        """日期、股票列和值违反原生宽表契约时应明确失败。"""
        with TemporaryDirectory() as temporary_directory:
            workspace = Path(temporary_directory)
            valid_panel = self._valid_panel()
            invalid_panels = {
                "duplicate_dates": pd.concat(
                    [valid_panel.iloc[[0]], valid_panel.iloc[[0]]]
                ),
                "unordered_dates": valid_panel.iloc[::-1],
                "nonnumeric": valid_panel.astype(str),
                "infinite": valid_panel.mask(
                    valid_panel.eq(valid_panel.iloc[0, 0]),
                    np.inf,
                ),
            }
            for case_name, invalid_panel in invalid_panels.items():
                with self.subTest(case_name=case_name):
                    factor_path = workspace / f"{case_name}.parquet"
                    invalid_panel.to_parquet(factor_path)
                    with self.assertRaises(ValueError):
                        load_factor_parquet(factor_path)

            duplicate_columns = pd.DataFrame(
                [[1.0, 2.0]],
                index=valid_panel.index[:1],
                columns=["000001.SZ", "000001.SZ"],
            )
            with patch(
                "src.factors.io.pd.read_parquet",
                return_value=duplicate_columns,
            ):
                with self.assertRaisesRegex(ValueError, "股票代码不能重复"):
                    load_factor_parquet(workspace / "duplicate_codes.parquet")

    @staticmethod
    def _valid_panel() -> pd.DataFrame:
        """返回带标准轴名称的最小有效因子宽表。"""
        return pd.DataFrame(
            [[1.0, np.nan], [2.0, 3.0]],
            index=pd.DatetimeIndex(
                ["2024-01-02", "2024-01-03"],
                name="date",
            ),
            columns=pd.Index(
                ["000001.SZ", "000002.SZ"],
                name="asset_code",
            ),
        )

    @staticmethod
    def _base_config(output_root: Path) -> dict:
        """构造只启用 group return 的最小现有主配置。"""
        config_data = yaml.safe_load(
            BASE_CONFIG_PATH.read_text(encoding="utf-8")
        )
        config_data["run"].update(
            {
                "factors": False,
                "plotter": False,
                "overall_evaluation": False,
            }
        )
        config_data["output"]["root"] = str(output_root)
        return config_data


if __name__ == "__main__":
    unittest.main()
