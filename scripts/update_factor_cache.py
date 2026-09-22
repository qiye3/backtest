"""供定时任务调用的市场缓存与因子结果独立更新入口。"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SCRIPT_ROOT = Path(__file__).resolve().parents[1]
FRAMEWORK_ROOT = SCRIPT_ROOT / "code" if (SCRIPT_ROOT / "code").is_dir() else SCRIPT_ROOT


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("configs", nargs="+", type=Path)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--rebuild", action="store_true")
    return parser.parse_args()


def _cache_groups(configs: list[Any]) -> list[list[Any]]:
    """让不同缓存根的配置分别更新，同一缓存根只构造一次市场数据。"""
    grouped_configs: dict[Path, list[Any]] = defaultdict(list)
    for config in configs:
        cache_root = Path(config.raw["market_data"]["cache_root"]).expanduser()
        if not cache_root.is_absolute():
            cache_root = config.path.parent / cache_root
        grouped_configs[cache_root.resolve()].append(config)
    return list(grouped_configs.values())


def _result_record(market_result: Any, factor_results: list[Any]) -> dict[str, Any]:
    return {
        "market": {
            "mode": market_result.mode,
            "revision_before": market_result.revision_before,
            "revision_after": market_result.revision_after,
            "changed_sources": list(market_result.changed_sources),
            "changed_from": (
                market_result.changed_from.strftime("%Y-%m-%d")
                if market_result.changed_from is not None
                else None
            ),
        },
        "experiments": [
            {
                "output_root": str(result.output_root),
                "reused": list(result.reused),
                "incremental": list(result.incremental),
                "rebuilt": list(result.rebuilt),
            }
            for result in factor_results
        ],
    }


def _write_report(output_root: Path, report: dict[str, Any]) -> None:
    report_path = output_root / ".state" / "update_report.json"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = report_path.with_suffix(".json.tmp")
    temporary_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    os.replace(temporary_path, report_path)


def main() -> None:
    """按共享缓存分组更新市场数据，再更新每份配置的因子面板。"""
    arguments = _arguments()
    if str(FRAMEWORK_ROOT) not in sys.path:
        sys.path.insert(0, str(FRAMEWORK_ROOT))

    from src.config import load_config
    from src.data.incremental import update_market_data
    from src.factors.incremental import update_factor_results

    configs = [
        load_config(config_path.expanduser().resolve())
        for config_path in arguments.configs
    ]
    started_at = datetime.now(timezone.utc).isoformat()
    group_reports = []
    for config_group in _cache_groups(configs):
        market_result = update_market_data(
            config_group,
            rebuild=arguments.rebuild,
            dry_run=arguments.dry_run,
        )
        factor_results = [
            update_factor_results(
                config,
                market_result,
                rebuild=arguments.rebuild,
                dry_run=arguments.dry_run,
            )
            for config in config_group
        ]
        group_reports.append(_result_record(market_result, factor_results))

    report = {
        "status": "dry_run" if arguments.dry_run else "complete",
        "started_at": started_at,
        "finished_at": datetime.now(timezone.utc).isoformat(),
        "groups": group_reports,
    }
    if not arguments.dry_run:
        for config in configs:
            _write_report(config.output_root, report)
    print(json.dumps(report, ensure_ascii=False))


if __name__ == "__main__":
    main()
