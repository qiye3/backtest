#!/usr/bin/env bash
set -eu

project_root=/home/qiye/zxy/backtest
log_root=/home/qiye/zxy/logs/backtest
mkdir -p "$log_root"
cd "$project_root"

# 同一时间只运行一份下载任务，避免定时重试与人工启动相互覆盖。
exec /usr/bin/flock -n "$log_root/minutes.lock" \
    /usr/bin/timeout --signal=TERM 2h \
    /home/qiye/miniforge3/envs/zxy_py310/bin/python -u \
    -m scripts.update_daily_minutes \
    --minute-root /home/qiye/zxy/data/minute_bars \
    --snapshot-root /home/qiye/zxy/data/index/observed_csi1000_members \
    --status-path "$log_root/latest_minutes.json" \
    >> "$log_root/daily_minutes.log" 2>&1
