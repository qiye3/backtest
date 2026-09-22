"""验证市场来源版本与因子尾部更新的完整闭环。"""

from __future__ import annotations

import json
import shutil
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

import pandas as pd
import yaml

from src.config import load_config
from src.data.incremental import update_market_data
from src.data.market_data import MarketData
from src.factors.config import load_factors
from src.factors.engine import calc_factors
from src.factors.incremental import (
    update_factor_results,
    validate_factor_market_revision,
)
from src.factors.io import load_factor_panel

PROJECT_ROOT = Path(__file__).resolve().parents[1]
BASE_CONFIG_PATH = PROJECT_ROOT / "configs" / "base_config.yaml"
SYNTHETIC_DATA_ROOT = PROJECT_ROOT / "examples" / "data"
FACTOR_CONFIG_ROOT = PROJECT_ROOT / "examples" / "config" / "base_factors"


class IncrementalUpdateTests(unittest.TestCase):
    """验证干跑、无变化复用、原始修订和版本门禁。"""

    def test_market_revision_and_factor_tail_match_clean_rebuild(self) -> None:
        """行情文件修订后的增量因子应与干净全量计算一致。"""
        with TemporaryDirectory() as temporary_directory:
            workspace = Path(temporary_directory)
            data_root = workspace / "raw_data"
            shutil.copytree(SYNTHETIC_DATA_ROOT, data_root)
            config_path = self._write_config(workspace, data_root)
            config = load_config(config_path)

            dry_run = update_market_data([config], dry_run=True)
            self.assertEqual(dry_run.mode, "rebuild")
            self.assertFalse((workspace / "market_cache").exists())
            dry_run_factors = update_factor_results(
                config,
                dry_run,
                dry_run=True,
            )
            self.assertEqual(
                dry_run_factors.rebuilt,
                ("return_10d", "return_20d"),
            )
            self.assertFalse(config.output_root.exists())

            first_market = update_market_data([config])
            first_factors = update_factor_results(config, first_market)
            self.assertEqual(first_market.revision_after, 1)
            self.assertEqual(first_market.mode, "rebuild")
            self.assertEqual(first_factors.rebuilt, ("return_10d", "return_20d"))

            reused_market = update_market_data([config])
            reused_factors = update_factor_results(config, reused_market)
            self.assertEqual(reused_market.mode, "reuse")
            self.assertEqual(reused_market.revision_after, 1)
            self.assertEqual(reused_factors.reused, ("return_10d", "return_20d"))

            self._revise_quote_history(data_root)
            updated_market = update_market_data([config])
            updated_factors = update_factor_results(config, updated_market)
            self.assertEqual(updated_market.mode, "incremental")
            self.assertEqual(updated_market.changed_sources, ("stock_quote",))
            self.assertEqual(updated_market.revision_after, 2)
            self.assertEqual(
                updated_factors.incremental,
                ("return_10d", "return_20d"),
            )

            clean_config_path = self._write_config(
                workspace,
                data_root,
                name="clean.yaml",
                cache_name="clean_market_cache",
                output_name="clean_output",
            )
            clean_config = load_config(clean_config_path)
            clean_market_data = MarketData.from_yaml(clean_config_path, refresh=True)
            expected_panels = calc_factors(
                load_factors(clean_config.factor_config_directory),
                clean_market_data,
            )
            for factor_name, expected_panel in expected_panels.items():
                actual_panel = load_factor_panel(
                    factor_name,
                    config.output_root / "factors",
                )
                pd.testing.assert_frame_equal(actual_panel, expected_panel)

            market_state = json.loads(
                (workspace / "market_cache" / ".state" / "market_update.json").read_text(
                    encoding="utf-8"
                )
            )
            factor_state = json.loads(
                (config.output_root / ".state" / "factor_update.json").read_text(
                    encoding="utf-8"
                )
            )
            self.assertEqual(market_state["revision"], 2)
            self.assertEqual(factor_state["market_revision"], 2)

            updated_market.market_data.revision = 3
            with self.assertRaisesRegex(ValueError, "update_factor_cache"):
                validate_factor_market_revision(config, updated_market.market_data)

    @staticmethod
    def _write_config(
        workspace: Path,
        data_root: Path,
        name: str = "incremental.yaml",
        cache_name: str = "market_cache",
        output_name: str = "output",
    ) -> Path:
        """用仓库的可重复样例数据构造最小因子运行配置。"""
        config_data = yaml.safe_load(BASE_CONFIG_PATH.read_text(encoding="utf-8"))
        config_data["run"].update(
            {
                "factors": True,
                "group_return": False,
                "simple_backtest": False,
                "account_backtest": False,
                "plotter": False,
                "overall_evaluation": False,
                "max_workers": 1,
            }
        )
        config_data["factors"]["config_directory"] = str(FACTOR_CONFIG_ROOT)
        config_data["output"]["root"] = str(workspace / output_name)
        market_config = config_data["market_data"]
        market_config.update(
            {
                "source_root": str(data_root),
                "cache_root": str(workspace / cache_name),
                "start_date": "2024-01-02",
                "end_date": "2024-06-28",
            }
        )
        config_path = workspace / name
        config_path.write_text(
            yaml.safe_dump(config_data, allow_unicode=True, sort_keys=False),
            encoding="utf-8",
        )
        return config_path

    @staticmethod
    def _revise_quote_history(data_root: Path) -> None:
        """修订已有年度文件的历史收盘价，模拟 Wind 回补。"""
        quote_path = data_root / "stock" / "daily_quote" / "quote_2024.csv"
        quote_data = pd.read_csv(quote_path)
        quote_data.loc[quote_data.index[-1], "S_DQ_ADJCLOSE"] *= 1.05
        quote_data.to_csv(quote_path, index=False)


if __name__ == "__main__":
    unittest.main()
