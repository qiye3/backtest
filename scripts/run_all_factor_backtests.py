"""共享一次市场缓存，依次运行 Growth、Quality、Value 三组正式因子。"""

from __future__ import annotations

import argparse
import sys
from copy import deepcopy
from pathlib import Path
from typing import Any

import yaml

SCRIPT_ROOT = Path(__file__).resolve().parents[1]
FRAMEWORK_ROOT = SCRIPT_ROOT / "code" if (SCRIPT_ROOT / "code").is_dir() else SCRIPT_ROOT
GROUPS = ("growth", "quality", "value")


def _absolute_path(value: str) -> Path:
    path = Path(value).expanduser()
    if not path.is_absolute():
        raise argparse.ArgumentTypeError(f"必须使用绝对路径: {value}")
    return path.resolve()


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--factors-root", required=True, type=_absolute_path)
    parser.add_argument("--data-root", required=True, type=_absolute_path)
    parser.add_argument("--output-root", required=True, type=_absolute_path)
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args()


def _enable_imports(factors_root: Path) -> None:
    for path in reversed((FRAMEWORK_ROOT, factors_root.parent)):
        if str(path) not in sys.path:
            sys.path.insert(0, str(path))


def _build_configs(arguments: argparse.Namespace) -> dict[str, dict[str, Any]]:
    configs = {}
    for group in GROUPS:
        group_root = arguments.factors_root / f"{group}_factors"
        template = group_root / "run_config.example.yaml"
        if not template.is_file() or not (group_root / "config").is_dir():
            raise FileNotFoundError(f"因子包缺少正式模板或配置目录: {group_root}")
        config = yaml.safe_load(template.read_text(encoding="utf-8"))
        config["factors"]["config_directory"] = str(group_root / "config")
        config["output"]["root"] = str(arguments.output_root / group)
        config["market_data"]["source_root"] = str(arguments.data_root)
        config["market_data"]["cache_root"] = str(
            arguments.output_root / ".cache" / "market_data"
        )
        config["run"].update(
            {
                "refresh_market_data": False,
                "simple_backtest": True,
                "account_backtest": False,
                "plotter": True,
            }
        )
        config["simple_backtest"]["insufficient_stocks_policy"] = "cash"
        config["plots"]["simple"]["enabled"] = True
        configs[group] = config
    return configs


def _validate_inputs(
    data_root: Path,
    configs: dict[str, dict[str, Any]],
) -> None:
    if not data_root.is_dir():
        raise FileNotFoundError(f"数据根不存在: {data_root}")
    index_codes = {
        str(code)
        for config in configs.values()
        for code in config["market_data"]["universe_indices"]
    }
    required_paths = [
        *(data_root / "index" / "members" / f"{code}.csv" for code in index_codes),
        data_root / "stock" / "industry" / "industry_history.csv",
    ]
    missing = [path for path in required_paths if not path.is_file()]
    if missing:
        raise FileNotFoundError(
            "缺少正式输入文件:\n" + "\n".join(map(str, missing))
        )


def _merge_source(target: dict[str, Any], incoming: dict[str, Any]) -> None:
    collection_keys = {"fields", "codes", "forecast_year_offsets"}
    semantic_keys = (target.keys() | incoming.keys()) - collection_keys
    conflicts = [key for key in semantic_keys if target.get(key) != incoming.get(key)]
    if conflicts:
        raise ValueError(f"三组来源口径不一致: {', '.join(sorted(conflicts))}")
    for key in collection_keys:
        if key in target or key in incoming:
            target[key] = list(
                dict.fromkeys([*target.get(key, []), *incoming.get(key, [])])
            )


def _shared_market_config(
    configs: dict[str, dict[str, Any]],
    output_root: Path,
) -> dict[str, Any]:
    markets = [config["market_data"] for config in configs.values()]
    shared = deepcopy(markets[0])
    shared["start_date"] = min(item["start_date"] for item in markets)
    shared["end_date"] = max(item["end_date"] for item in markets)
    shared["cache_root"] = str(output_root / ".cache" / "market_data")
    sources: dict[str, dict[str, Any]] = {}
    for market in markets:
        for source_name, source in market["sources"].items():
            if source_name not in sources:
                sources[source_name] = deepcopy(source)
            else:
                _merge_source(sources[source_name], source)
    shared["sources"] = sources
    return {"market_data": shared}


def main() -> None:
    """校验输入、只刷新一次共享缓存，再按固定顺序运行三组实验。"""
    arguments = _arguments()
    configs = _build_configs(arguments)
    _validate_inputs(arguments.data_root, configs)
    _enable_imports(arguments.factors_root)
    from src.config import load_config
    from src.factors.config import load_factors

    config_root = arguments.output_root / ".run_configs"
    config_root.mkdir(parents=True, exist_ok=True)
    market_path = config_root / "market_data.yaml"
    market_path.write_text(
        yaml.safe_dump(
            _shared_market_config(configs, arguments.output_root),
            allow_unicode=True,
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    run_configs = {}
    for group, config in configs.items():
        config_path = config_root / f"{group}.yaml"
        config_path.write_text(
            yaml.safe_dump(config, allow_unicode=True, sort_keys=False),
            encoding="utf-8",
        )
        run_configs[group] = load_config(config_path)
        factors = load_factors(run_configs[group].factor_config_directory)
        print(
            f"[{group}] loaded_factors={len(factors)} "
            f"directory={run_configs[group].factor_config_directory}"
        )
    if arguments.dry_run:
        print("[dry-run] 三组配置、动态导入、行业数据和共享缓存配置校验通过。")
        return

    from src.cli import run
    from src.data.market_data import MarketData

    MarketData.from_yaml(market_path, refresh=True)
    for group in GROUPS:
        print(f"[{group}] 开始实验", flush=True)
        run(run_configs[group], show_progress=True)


if __name__ == "__main__":
    main()
