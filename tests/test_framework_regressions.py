"""覆盖 2026-09-22 数据与策略运行问题的回归测试。"""

from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import patch

import pandas as pd
import yaml

from src.config import _complete_strategy_market_data_sources, load_config
from src.factors.config import load_factors
from src.strategy.config import load_strategies
from src.strategy.io import load_strategy_targets, save_strategy_targets
from strategies.roadshow_indices.portfolio import MarketValuePortfolio


def test_strategy_dependencies_are_added_from_strategy_configs() -> None:
    """策略基准的价格和权重来源应在市场数据加载前补齐。"""
    raw_config = {
        "run": {
            "strategies": True,
            "strategy_simple_backtest": False,
            "strategy_account_backtest": False,
        },
        "market_data": {
            "sources": {
                "index_price": {
                    "codes": ["000906.SH"],
                    "fields": ["S_DQ_CLOSE"],
                }
            }
        },
    }
    with TemporaryDirectory() as temporary_directory:
        config_directory = Path(temporary_directory)
        (config_directory / "demo.yaml").write_text(
            yaml.safe_dump({"benchmark_index": "000300.SH"}),
            encoding="utf-8",
        )

        _complete_strategy_market_data_sources(
            raw_config,
            config_directory,
            config_directory / "output",
        )

    sources = raw_config["market_data"]["sources"]
    assert sources["index_price"]["codes"] == ["000906.SH", "000300.SH"]
    assert sources["index_weights_monthly"] == {
        "codes": ["000300.SH"],
        "fields": ["I_WEIGHT"],
    }


def test_combined_strategy_suite_loads_six_peer_strategies() -> None:
    """默认套件应在同一配置层级加载成长100与其他五个策略。"""
    config = load_config(Path("strategies/roadshow_indices/run.yaml"))

    factor_names = {
        factor.name for factor in load_factors(config.factor_config_directory)
    }
    strategy_names = {
        strategy.name
        for strategy in load_strategies(config.strategy_config_directory)
    }

    assert len(factor_names) == 6
    assert strategy_names == {
        "cni_growth100",
        "cni_value100",
        "cni_free_cashflow",
        "csi500_quality_growth",
        "csi_dividend_low_volatility100",
        "csi_technology_top",
    }


def test_insufficient_candidates_use_all_and_persist_diagnostics() -> None:
    """候选数不足时应按配置降级，并把实际选样口径写入结果。"""
    rebalance_date = pd.Timestamp("2024-03-11")
    stock_codes = pd.Index(["000001.SZ", "000002.SZ", "000003.SZ"])
    signals = pd.DataFrame(
        [[3.0, 2.0, 1.0]],
        index=pd.DatetimeIndex([rebalance_date], name="date"),
        columns=stock_codes,
    )
    market_values = pd.DataFrame(
        [[3.0, 2.0, 1.0]],
        index=signals.index,
        columns=stock_codes,
    )
    market_data = SimpleNamespace(
        membership=pd.DataFrame(True, index=signals.index, columns=stock_codes),
        get_panel=lambda *_args, **_kwargs: market_values,
    )
    strategy = MarketValuePortfolio(
        {
            "name": "small_universe",
            "factor_name": "score",
            "benchmark_index": "000906.SH",
            "params": {
                "top_n": 5,
                "insufficient_candidates_policy": "warn_and_use_all",
            },
        }
    )

    with patch("warnings.warn") as warn:
        targets = strategy.build_target_weights(
            signals,
            market_data,
            signals.index,
        )
    result = {
        "strategy_name": strategy.name,
        "factor_name": strategy.factor_name,
        "benchmark_index": strategy.benchmark_index,
        "rebalance_frequency": "quarterly",
        "periods": {1: targets},
        "selection_diagnostics": {1: strategy.selection_diagnostics},
    }
    with TemporaryDirectory() as temporary_directory:
        save_strategy_targets(result, temporary_directory)
        restored = load_strategy_targets(strategy.name, temporary_directory)

    diagnostics = restored["selection_diagnostics"][1].iloc[0]
    assert targets.ne(0).sum(axis=1).iloc[0] == 3
    assert diagnostics["candidate_count"] == 3
    assert diagnostics["requested_top_n"] == 5
    assert diagnostics["selected_count"] == 3
    assert diagnostics["status"] == "warn_and_use_all"
    warn.assert_called_once()


def test_skipped_rebalance_date_keeps_diagnostics_without_holdings() -> None:
    """skip_date 不应产生目标持仓，但必须保留该日诊断。"""
    rebalance_date = pd.Timestamp("2024-03-11")
    result = {
        "strategy_name": "skip_demo",
        "factor_name": "score",
        "benchmark_index": "000906.SH",
        "rebalance_frequency": "quarterly",
        "periods": {
            1: pd.DataFrame(
                columns=["000001.SZ"],
                index=pd.DatetimeIndex([], name="date"),
                dtype=float,
            )
        },
        "selection_diagnostics": {
            1: pd.DataFrame(
                {
                    "date": [rebalance_date],
                    "candidate_count": [3],
                    "requested_top_n": [5],
                    "selected_count": [0],
                    "status": ["skipped"],
                }
            )
        },
    }

    with TemporaryDirectory() as temporary_directory:
        save_strategy_targets(result, temporary_directory)
        restored = load_strategy_targets("skip_demo", temporary_directory)

    assert restored["periods"][1].empty
    diagnostics = restored["selection_diagnostics"][1].iloc[0]
    assert diagnostics["date"] == rebalance_date
    assert diagnostics["selected_count"] == 0
    assert diagnostics["status"] == "skipped"
