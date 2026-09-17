"""从单个文件或配置目录动态构造组合规则。"""

from __future__ import annotations

from importlib import import_module
from pathlib import Path

import yaml

from src.strategy.base import PortfolioRule


def load_strategies(config_directory: str | Path) -> list[PortfolioRule]:
    """按文件名顺序加载目录第一层的 Strategy YAML。"""
    resolved_directory = Path(config_directory).expanduser().resolve()
    config_paths = sorted(resolved_directory.glob("*.yaml"))
    if not config_paths:
        raise FileNotFoundError(
            f"Strategy 配置目录中没有 YAML: {resolved_directory}"
        )

    strategies = [load_strategy(config_path) for config_path in config_paths]
    strategy_names = [strategy.name for strategy in strategies]
    if len(strategy_names) != len(set(strategy_names)):
        raise ValueError("批量 Strategy 配置中的 name 必须唯一")
    return strategies


def load_strategy(config_path: str | Path) -> PortfolioRule:
    """读取一个 Strategy YAML，并动态导入其中声明的 PortfolioRule。"""
    resolved_path = Path(config_path).expanduser().resolve()
    strategy_config = yaml.safe_load(resolved_path.read_text(encoding="utf-8"))
    implementation = strategy_config["implementation"]
    strategy_module = import_module(implementation["module"])
    strategy_class = getattr(strategy_module, implementation["class"])
    return strategy_class(strategy_config)
