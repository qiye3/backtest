"""日终运行中证1000虚拟账户；可以由 cron 或任务计划每天触发。"""

from __future__ import annotations

import argparse
from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

import pandas as pd

from src.intraday.config import load_minute_config
from src.intraday.paper import run_paper_day


def latest_completed_day() -> pd.Timestamp:
    """上海时间 16:00 后取今日，否则取昨日；周末回退至最近工作日。"""
    now = datetime.now(ZoneInfo("Asia/Shanghai"))
    day = now.date() if now.time() >= time(16, 0) else (now - timedelta(days=1)).date()
    while day.weekday() >= 5:
        day -= timedelta(days=1)
    return pd.Timestamp(day)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", required=True, help="正式事后模拟盘配置 YAML")
    parser.add_argument("--date", default=None, help="交易日 YYYY-MM-DD；默认上海时间最近完成的工作日")
    parser.add_argument("--no-update-minutes", action="store_true", help="只使用本地完整分钟数据")
    parser.add_argument("--request-delay", type=float, default=0.25, help="每只股票间请求间隔秒数")
    parser.add_argument("--min-coverage", type=float, default=0.97, help="日行情发布最低股票覆盖率")
    args = parser.parse_args()
    date = pd.Timestamp(args.date).normalize() if args.date else latest_completed_day()
    output = run_paper_day(
        load_minute_config(args.config), date,
        update_minutes=not args.no_update_minutes,
        delay_seconds=args.request_delay,
        min_coverage=args.min_coverage,
    )
    print(f"中证1000事后模拟账户已更新: {output}")


if __name__ == "__main__":
    main()
