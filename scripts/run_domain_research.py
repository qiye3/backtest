"""按 domains YAML 指定的基础因子逐个运行分域研究。"""

from __future__ import annotations

import argparse
import shutil
import sys
from copy import deepcopy
from pathlib import Path
from typing import TYPE_CHECKING, Any

import yaml

from scripts.tmux_runner import launch_in_tmux

if TYPE_CHECKING:
    from src.config import RunConfig

SCRIPT_ROOT = Path(__file__).resolve().parents[1]
FRAMEWORK_ROOT = SCRIPT_ROOT / "code" if (SCRIPT_ROOT / "code").is_dir() else SCRIPT_ROOT


def _absolute_path(value: str) -> Path:
    path = Path(value).expanduser()
    if not path.is_absolute():
        raise argparse.ArgumentTypeError(f"必须使用绝对路径: {value}")
    return path.resolve()


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", required=True, type=_absolute_path)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument(
        "--fresh",
        action="store_true",
        help="清空各单因子实验的 .pipeline_cache 并从头运行。",
    )
    parser.add_argument(
        "--foreground",
        action="store_true",
        help="不使用 tmux，在当前终端运行正式任务。",
    )
    return parser.parse_args()


def _factor_config_paths(config_directory: Path) -> dict[str, Path]:
    """按 Factor 配置中的稳定名称建立单文件索引。"""
    factor_paths = {}
    for config_path in sorted(config_directory.glob("*.yaml")):
        factor_config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
        factor_paths[factor_config["name"]] = config_path
    return factor_paths


def _resolve_config_path(config_path: Path, configured_path: str) -> Path:
    """按原主配置位置解析需要写入派生配置的外部路径。"""
    resolved_path = Path(configured_path).expanduser()
    if not resolved_path.is_absolute():
        resolved_path = config_path.parent / resolved_path
    return resolved_path.resolve()


def _materialize_factor_runs(base_config: RunConfig) -> list[Path]:
    """为选中的每个基础因子生成可复现的单因子主配置。"""
    if base_config.factor_domains is None:
        raise ValueError("域研究主配置必须设置 factors.domain_config")
    if 4 not in base_config.raw["group_return"].get("future_return_weeks", []):
        raise ValueError("域研究 overall 分组收益大图需要 future_return_weeks 包含 4")

    factor_paths = _factor_config_paths(base_config.factor_config_directory)
    missing_factor_names = set(base_config.factor_domains.factor_names) - factor_paths.keys()
    if missing_factor_names:
        raise ValueError(
            f"domain factor_names 不在 Factor 配置目录中: {sorted(missing_factor_names)}"
        )

    generated_root = base_config.output_root / ".domain_run_configs"
    if generated_root.exists():
        shutil.rmtree(generated_root)
    run_config_paths = []
    for factor_name in base_config.factor_domains.factor_names:
        factor_run_root = generated_root / factor_name
        factor_config_directory = factor_run_root / "factors"
        factor_config_directory.mkdir(parents=True, exist_ok=True)
        factor_config_path = factor_config_directory / factor_paths[factor_name].name
        shutil.copy2(factor_paths[factor_name], factor_config_path)

        domain_config = {
            "factor_names": [factor_name],
            "domains": [
                {
                    "name": definition.name,
                    "rule": dict(definition.rule),
                }
                for definition in base_config.factor_domains.domains
            ],
        }
        domain_config_path = factor_run_root / "domains.yaml"
        domain_config_path.write_text(
            yaml.safe_dump(domain_config, allow_unicode=True, sort_keys=False),
            encoding="utf-8",
        )

        run_config = _single_factor_run_config(
            base_config,
            factor_name,
            factor_config_directory,
            domain_config_path,
        )
        run_config_path = factor_run_root / "run.yaml"
        run_config_path.write_text(
            yaml.safe_dump(run_config, allow_unicode=True, sort_keys=False),
            encoding="utf-8",
        )
        run_config_paths.append(run_config_path)
    return run_config_paths


def _single_factor_run_config(
    base_config: RunConfig,
    factor_name: str,
    factor_config_directory: Path,
    domain_config_path: Path,
) -> dict[str, Any]:
    """构造只运行一个基础因子及其域 variants 的上层配置。"""
    run_config = deepcopy(base_config.raw)
    run_config["run"].update(
        {
            "factors": True,
            "group_return": True,
            "strategies": False,
            "plotter": False,
            "overall_evaluation": True,
            "refresh_market_data": False,
        }
    )
    run_config["strategy_analysis"]["enabled"] = False
    run_config["factors"] = {
        "config_directory": str(factor_config_directory),
        "domain_config": str(domain_config_path),
        "selected_variants": ["raw"],
    }
    run_config["output"]["root"] = str(base_config.output_root / factor_name)

    market_data = run_config["market_data"]
    for path_name in ("source_root", "cache_root"):
        market_data[path_name] = str(
            _resolve_config_path(base_config.path, market_data[path_name])
        )
    if "external_returns" in run_config:
        run_config["external_returns"]["path"] = str(
            base_config.external_return_path
        )

    run_config["plots"]["overall"]["factor_distribution_grid"]["enabled"] = True
    run_config["plots"]["overall"]["group_return_grid"]["enabled"] = True
    return run_config


def main() -> None:
    """校验选择名单，复用一次 MarketData 并依次运行单因子域研究。"""
    arguments = _arguments()
    if str(FRAMEWORK_ROOT) not in sys.path:
        sys.path.insert(0, str(FRAMEWORK_ROOT))

    from src.config import load_config

    base_config = load_config(arguments.config)
    if not arguments.dry_run and not arguments.foreground:
        launch_in_tmux(base_config.output_root, "domain_research")
        return

    run_config_paths = _materialize_factor_runs(base_config)
    run_configs = [load_config(config_path) for config_path in run_config_paths]
    if arguments.dry_run:
        for run_config in run_configs:
            print(f"[dry-run] {run_config.output_root.name}: {run_config.path}")
        return

    from src.cli import run
    from src.data.market_data import MarketData

    shared_market_data = MarketData.from_yaml(
        base_config.path,
        refresh=base_config.raw["run"]["refresh_market_data"],
        market_data_config=base_config.raw["market_data"],
    )
    for run_config in run_configs:
        print(f"[{run_config.output_root.name}] 开始分域研究", flush=True)
        run(
            run_config,
            show_progress=True,
            market_data=shared_market_data,
            fresh=arguments.fresh,
        )


if __name__ == "__main__":
    main()
