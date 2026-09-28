"""使用正式 factor-backtest 框架生成频率感知的时序因子变体。"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

SCRIPT_ROOT = Path(__file__).resolve().parents[1]
FRAMEWORK_ROOT = SCRIPT_ROOT / "code" if (SCRIPT_ROOT / "code").is_dir() else SCRIPT_ROOT


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", required=True, type=Path)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--fresh", action="store_true")
    return parser.parse_args()


def main() -> None:
    """校验搜索配置，并按需计算和发布时序因子变体。"""
    arguments = _arguments()
    sys.dont_write_bytecode = True
    if str(FRAMEWORK_ROOT) not in sys.path:
        sys.path.insert(0, str(FRAMEWORK_ROOT))

    from src.factors.search import (
        load_factor_search_config,
        report_json,
        run_factor_search,
        search_plan,
    )

    config = load_factor_search_config(arguments.config)
    if arguments.dry_run:
        print(report_json(search_plan(config)))
        return
    print(report_json(run_factor_search(config, fresh=arguments.fresh)))


if __name__ == "__main__":
    main()
