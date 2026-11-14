"""研究 CLI 只承接因子、分组评价和 Strategy 目标产出。"""
from __future__ import annotations

from pathlib import Path

from src.cli import _enabled_progress_stages, _remaining_factor_plot_names
from src.config import load_config
from src.group_return.grouping import build_group_definitions, core_group_ids


def test_research_config_and_csi1000_universe() -> None:
    config = load_config(Path("configs/base_config.yaml"))
    assert config.raw["market_data"]["universe_indices"] == ["000852.SH"]
    assert config.raw["market_data"]["benchmark_index"] == "000852.SH"
    definitions = build_group_definitions(
        config.raw["group_return"]["grouping"]["quantile_edges"],
        config.raw["group_return"]["grouping"]["group_aliases"],
    )
    assert core_group_ids(definitions) == [f"G{i}" for i in range(1, 11)]
    assert len(definitions) == 12


def test_cli_contains_only_live_research_stages() -> None:
    config = load_config(Path("configs/base_config.yaml"))
    stages = _enabled_progress_stages(config)
    assert stages == ("market_data", "factors", "group_return", "overall_evaluation", "plotter")
    assert not any("backtest" in stage for stage in stages)


def test_strategy_targets_do_not_trigger_obsolete_plotter_modes() -> None:
    config = load_config(Path("strategies/yfd_growth100_factors/run.yaml"))
    assert config.raw["run"]["strategies"] is True
    assert _remaining_factor_plot_names(config.raw["run"], config.raw["plots"]) == set()
