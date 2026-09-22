"""使用外部 Skill 框架顺序运行指数增强策略套件。"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

import yaml
from tmux_runner import launch_in_tmux

STRATEGY_SUITES = {
    "yfd100": "yfd_growth100_factors",
    "roadshow": "roadshow_indices",
}


def _absolute_path(value: str) -> Path:
    path = Path(value).expanduser()
    if not path.is_absolute():
        raise argparse.ArgumentTypeError(f"必须使用绝对路径: {value}")
    return path.resolve()


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--framework-root", required=True, type=_absolute_path)
    parser.add_argument("--data-root", required=True, type=_absolute_path)
    parser.add_argument("--output-root", required=True, type=_absolute_path)
    parser.add_argument(
        "--suite",
        choices=("all", *STRATEGY_SUITES),
        default="all",
    )
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument(
        "--foreground",
        action="store_true",
        help="不使用 tmux，在当前终端运行正式任务。",
    )
    return parser.parse_args()


def _selected_suites(suite: str) -> tuple[str, ...]:
    if suite == "all":
        # roadshow 套件已包含成长100，默认不再重复运行旧单策略套件。
        return ("roadshow",)
    return (suite,)


def _enable_imports(framework_root: Path, package_root: Path) -> None:
    framework_code = framework_root / "code"
    if not (framework_code / "src").is_dir():
        raise FileNotFoundError(f"Skill 框架代码不存在: {framework_code}")
    for path in reversed((framework_code, package_root)):
        if str(path) not in sys.path:
            sys.path.insert(0, str(path))


def _build_config(
    suite: str,
    package_root: Path,
    arguments: argparse.Namespace,
) -> tuple[Path, dict[str, Any]]:
    strategy_root = package_root / "strategies" / STRATEGY_SUITES[suite]
    config = yaml.safe_load(
        (strategy_root / "run.yaml").read_text(encoding="utf-8")
    )
    config["factors"]["config_directory"] = str(
        strategy_root / "factor_configs"
    )
    config["strategies"]["config_directory"] = str(
        strategy_root / "strategy_configs"
    )
    config["market_data"]["source_root"] = str(arguments.data_root)
    config["market_data"]["cache_root"] = str(
        arguments.output_root / ".cache" / "market_data"
    )
    config["output"]["root"] = str(arguments.output_root / suite)
    config["run"].update(
        {
            "simple_backtest": False,
            "account_backtest": False,
            "strategy_simple_backtest": True,
            "strategy_account_backtest": False,
            "plotter": True,
            "overall_evaluation": False,
        }
    )
    config["plots"]["distribution"]["enabled"] = False
    config["plots"]["evaluation"]["enabled"] = False
    config["plots"]["simple"]["enabled"] = False
    config["plots"]["account"]["enabled"] = False
    config["plots"]["strategy"]["enabled"] = True
    return strategy_root, config


def _validate_members(data_root: Path, configs: list[dict[str, Any]]) -> None:
    index_codes = {
        str(index_code)
        for config in configs
        for index_code in config["market_data"]["universe_indices"]
    }
    missing_paths = [
        data_root / "index" / "members" / f"{index_code}.csv"
        for index_code in sorted(index_codes)
        if not (data_root / "index" / "members" / f"{index_code}.csv").is_file()
    ]
    if missing_paths:
        raise FileNotFoundError(
            "缺少历史指数成份:\n" + "\n".join(map(str, missing_paths))
        )


def main() -> None:
    """生成套件配置并默认在一个 tmux session 中顺序执行。"""
    arguments = _arguments()
    if not arguments.dry_run and not arguments.foreground:
        launch_in_tmux(arguments.output_root, "strategy_backtest")
        return

    package_root = Path(__file__).resolve().parents[1]
    _enable_imports(arguments.framework_root, package_root)
    selected_suites = _selected_suites(arguments.suite)
    suite_configs = []
    for suite in selected_suites:
        strategy_root, config = _build_config(
            suite,
            package_root,
            arguments,
        )
        suite_configs.append((suite, strategy_root, config))
    _validate_members(
        arguments.data_root,
        [config for _, _, config in suite_configs],
    )

    from src.config import load_config
    from src.factors.config import load_factors
    from src.strategy.config import load_strategies

    run_configs = []
    config_root = arguments.output_root / ".run_configs"
    config_root.mkdir(parents=True, exist_ok=True)
    for suite, strategy_root, config in suite_configs:
        config_path = config_root / f"{suite}.yaml"
        config_path.write_text(
            yaml.safe_dump(config, allow_unicode=True, sort_keys=False),
            encoding="utf-8",
        )
        run_config = load_config(config_path)
        factors = load_factors(run_config.factor_config_directory)
        strategies = load_strategies(run_config.strategy_config_directory)
        print(
            f"[{suite}] factors={len(factors)} strategies={len(strategies)} "
            f"directory={strategy_root}"
        )
        run_configs.append((suite, run_config))

    if arguments.dry_run:
        print("[dry-run] 策略配置、动态导入和历史成份校验通过。")
        return

    from src.cli import run

    for suite, run_config in run_configs:
        print(f"[{suite}] 开始策略回测", flush=True)
        run(run_config, show_progress=True)


if __name__ == "__main__":
    main()
