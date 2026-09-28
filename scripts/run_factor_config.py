"""校验并运行任意 Factor Backtest 主配置。"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from tmux_runner import launch_in_tmux

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
        help="清空 .pipeline_cache 并从头运行。",
    )
    parser.add_argument(
        "--foreground",
        action="store_true",
        help="不使用 tmux，在当前终端运行正式任务。",
    )
    return parser.parse_args()


def main() -> None:
    """默认通过 tmux 运行配置，并提供前台与校验模式。"""
    arguments = _arguments()
    if str(FRAMEWORK_ROOT) not in sys.path:
        sys.path.insert(0, str(FRAMEWORK_ROOT))

    from src.config import load_config

    run_config = load_config(arguments.config)
    if arguments.dry_run:
        print(f"[dry-run] 配置校验通过: {arguments.config}")
        return
    if not arguments.foreground:
        launch_in_tmux(run_config.output_root, "factor_config")
        return

    from src.cli import run

    run(run_config, show_progress=True, fresh=arguments.fresh)


if __name__ == "__main__":
    main()
