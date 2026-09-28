"""运行基于 zxy 分钟归档的真实成交账户回测。"""

from __future__ import annotations

import argparse

from src.intraday.config import load_minute_config
from src.intraday.data import MinuteArchiveReader, load_corporate_actions
from src.intraday.engine import MinuteBacktestEngine
from src.intraday.io import save_run_outputs
from src.intraday.targets import load_target_weights


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", required=True, help="分钟回测 YAML 路径")
    arguments = parser.parse_args()

    config = load_minute_config(arguments.config)
    targets = load_target_weights(
        config.targets.path,
        config.targets.date_only_signal_time,
    )
    codes = sorted(targets["code"].unique())
    reader = MinuteArchiveReader(
        config.data.minute_root,
        config.data.cache_root,
        config.data.universe_name,
    )
    bars = reader.read_range(config.data.start_date, config.data.end_date, codes)
    actions = None
    if config.data.daily_root is not None:
        actions = load_corporate_actions(config.data.daily_root, codes)
    result = MinuteBacktestEngine(config).run(bars, targets, actions)
    output_directory = save_run_outputs(config, result, reader.issues)
    print(f"分钟回测完成: {output_directory}")
    print(f"最终净值: {result.metrics.get('final_nav', float('nan')):,.2f}")


if __name__ == "__main__":
    main()
