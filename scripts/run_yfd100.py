"""使用外部 Skill 框架运行独立 yfd100 策略包。"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import yaml


def _absolute_path(value: str) -> Path:
    path = Path(value).expanduser()
    if not path.is_absolute():
        raise argparse.ArgumentTypeError(f"必须使用绝对路径: {value}")
    return path.resolve()


def main() -> None:
    """生成外部路径配置，默认仅运行策略 simple 回测。"""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--framework-root", required=True, type=_absolute_path)
    parser.add_argument("--data-root", required=True, type=_absolute_path)
    parser.add_argument("--output-root", required=True, type=_absolute_path)
    parser.add_argument("--dry-run", action="store_true")
    arguments = parser.parse_args()

    package_root = Path(__file__).resolve().parents[1]
    strategy_root = package_root / "strategies" / "yfd_growth100_factors"
    framework_code = arguments.framework_root / "code"
    if not (framework_code / "src").is_dir():
        raise FileNotFoundError(f"Skill 框架代码不存在: {framework_code}")
    for path in reversed((framework_code, package_root)):
        sys.path.insert(0, str(path))

    config = yaml.safe_load((strategy_root / "run.yaml").read_text(encoding="utf-8"))
    config["factors"]["config_directory"] = str(strategy_root / "factor_configs")
    if "result_root" in config["factors"]:
        factor_result_root = Path(config["factors"]["result_root"]).expanduser()
        if not factor_result_root.is_absolute():
            factor_result_root = strategy_root / factor_result_root
        config["factors"]["result_root"] = str(factor_result_root.resolve())
    config["strategies"]["config_directory"] = str(
        strategy_root / "strategy_configs"
    )
    config["market_data"]["source_root"] = str(arguments.data_root)
    config["market_data"]["cache_root"] = str(arguments.output_root / ".cache")
    config["output"]["root"] = str(arguments.output_root)
    config["run"].update(
        {
            "strategy_simple_backtest": True,
            "strategy_account_backtest": False,
            "account_backtest": False,
        }
    )
    required_members = [
        arguments.data_root / "index" / "members" / f"{code}.csv"
        for code in config["market_data"]["universe_indices"]
    ]
    missing = [path for path in required_members if not path.is_file()]
    if missing:
        raise FileNotFoundError("缺少历史指数成份:\n" + "\n".join(map(str, missing)))

    arguments.output_root.mkdir(parents=True, exist_ok=True)
    config_path = arguments.output_root / "yfd100.run.yaml"
    config_path.write_text(
        yaml.safe_dump(config, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    from src.config import load_config
    from src.factors.config import load_factors
    from src.strategy.config import load_strategies

    run_config = load_config(config_path)
    factors = (
        load_factors(run_config.factor_config_directory)
        if run_config.raw["run"]["factors"]
        else []
    )
    strategies = load_strategies(run_config.strategy_config_directory)
    if arguments.dry_run:
        print(
            f"[dry-run] yfd100 配置与动态导入校验通过: "
            f"factors={len(factors)}, strategies={len(strategies)}, "
            f"config={config_path}"
        )
        return
    from src.cli import run

    run(run_config, show_progress=True)


if __name__ == "__main__":
    main()
