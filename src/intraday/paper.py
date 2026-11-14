"""中证1000事后模拟盘：以统一分钟撮合引擎每天推进一次可恢复的账户。"""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
import tempfile
from contextlib import contextmanager
from dataclasses import asdict, fields
from pathlib import Path
from typing import Any, Iterator

import pandas as pd

from src.intraday.config import MinuteBacktestConfig
from src.intraday.data import (
    MinuteArchiveReader, attach_daily_trade_status,
    load_corporate_actions, load_daily_trade_status,
)
from src.intraday.engine import MinuteBacktestEngine
from src.intraday.execution import Fill, Order
from src.intraday.free_minute import FreeMinuteDailyUpdater, missing_execution_minutes
from src.intraday.targets import load_target_weights, load_strategy_output_targets
from src.intraday.universe import HistoricalIndexUniverse


def run_paper_day(
    config: MinuteBacktestConfig,
    trading_date: object,
    *,
    update_minutes: bool = True,
    delay_seconds: float = 0.25,
    min_coverage: float = 0.97,
) -> Path:
    """在一天内完成下载、回放、计价、账本发布。已发布日期禁止重复记账。"""
    if config.universe is None:
        raise ValueError("逐日账户必须设置 universe.members_root 为真实历史成份文件目录")
    if config.targets.mode not in {"file", "strategy_output"}:
        raise ValueError("逐日账户需要 targets.mode=file 或 strategy_output")
    date = pd.Timestamp(trading_date).normalize()
    if not config.data.start_date <= date <= config.data.end_date:
        raise ValueError("执行日期必须在 data.start_date 与 data.end_date 之间")
    account_name = config.run_name
    if not account_name or any(character in account_name for character in "/\\."):
        raise ValueError("run_name 用于账户目录，只允许普通非点号目录名")
    account_root = config.output_root / "paper_accounts" / account_name
    account_root.mkdir(parents=True, exist_ok=True)

    with _account_lock(account_root / ".account.lock"):
        universe = HistoricalIndexUniverse(config.universe.members_root)
        target_weights = (
            load_strategy_output_targets(
                config.targets.path, config.targets.rebalance_interval,
                config.targets.date_only_signal_time,
            ) if config.targets.mode == "strategy_output" else
            load_target_weights(config.targets.path, config.targets.date_only_signal_time)
        )
        days_root = account_root / "days"
        days_root.mkdir(exist_ok=True)
        previous_days = sorted(path for path in days_root.iterdir() if path.is_dir() and not path.name.startswith("."))
        previous_state: dict[str, Any] | None = None
        previous_nav = config.account.initial_capital
        previous_date = None
        signature = _config_signature(config)
        if previous_days:
            newest = previous_days[-1]
            previous_date = pd.Timestamp(newest.name)
            if date <= previous_date:
                raise FileExistsError(f"模拟账户已经处理到 {previous_date.date()}，拒绝重复记账")
            previous_record = json.loads((newest / "snapshot.json").read_text(encoding="utf-8"))
            if previous_record["configuration"] != signature:
                raise ValueError("成交/费用/股票池配置已改变，请使用新 run_name 新建账户")
            previous_digest = previous_record.get("universe_history_digest")
            if previous_digest and previous_digest != _universe_history_digest(universe, previous_date):
                raise ValueError("已经用于账户的历史中证1000成份发生变化，请另建账户")
            previous_state = previous_record["state"]
            previous_nav = float(previous_record["end_nav"])

        # 只读取当日有效的新目标，不再把几年前曾经买过的股票加入当天下载名单。
        last_signal = (
            pd.Timestamp(previous_state["last_applied_signal_timestamp"])
            if previous_state and previous_state.get("last_applied_signal_timestamp") else None
        )
        eligible = target_weights[
            target_weights["signal_timestamp"].dt.tz_localize(None).dt.normalize() < date
        ]
        if last_signal is not None:
            eligible = eligible[eligible["signal_timestamp"] > last_signal]
        if not eligible.empty:
            newest_signal = eligible["signal_timestamp"].max()
            eligible = eligible[eligible["signal_timestamp"] == newest_signal]
        target_weights = eligible.reset_index(drop=True)
        universe.validate_targets(target_weights)

        held = set(previous_state["positions"]) if previous_state else set()
        pending_codes = set(previous_state.get("pending_target_codes", [])) if previous_state else set()
        target_codes = set(target_weights["code"])
        needed = held | pending_codes | target_codes
        # 日频信号已由外部策略产出，撮合只需要持仓、待补单和本次目标的分钟行情。
        # 现金空仓日读取一只当日成份股用于推进账户日期。
        codes = sorted(needed) if needed else list(universe.codes_on(date)[:1])
        if not codes:
            raise ValueError(f"{date.date()} 无可用中证1000成份股，无法推进账户")
        status = load_daily_trade_status(config.data.daily_status_path, codes, date, date)
        suspended = set(status.loc[status["is_suspended"], "code"]) if not status.empty else set()
        # 要求对拟交易和已有持仓的股票有可用分钟数据，已知停牌的股票除外。
        essential = needed - suspended
        reader = MinuteArchiveReader(
            config.data.minute_root, config.data.cache_root, config.data.universe_name,
        )
        if update_minutes:
            FreeMinuteDailyUpdater(
                config.data.minute_root, delay_seconds=delay_seconds, min_coverage=min_coverage,
            ).update_day(
                date, codes, required_codes=essential,
                required_window=(config.execution.window_start, config.execution.window_end),
                exempt_codes=suspended,
            )
            reader = MinuteArchiveReader(
                config.data.minute_root, config.data.cache_root, config.data.universe_name,
            )
        available = reader.available_dates()
        if date not in available:
            raise FileNotFoundError(f"{date.date()} 缺少完整分钟行情，请先执行更新")
        if previous_date is not None:
            unprocessed = [d for d in available if previous_date < d < date]
            if unprocessed:
                raise ValueError(
                    f"不能跳过已有分钟行情交易日 {unprocessed[0].date()}，请按日期依次推进账户"
                )

        bars = reader.read_day(date, codes)
        if bars.empty:
            raise ValueError(f"{date.date()} 没有可用于推进账户的分钟行情")
        incomplete = missing_execution_minutes(
            bars, date, essential,
            (config.execution.window_start, config.execution.window_end),
        )
        if incomplete:
            raise ValueError(f"关键股票的成交窗口分钟数据不完整: {dict(list(incomplete.items())[:10])}")
        bars = attach_daily_trade_status(bars, status)
        actions = None
        if config.data.daily_root is not None and held:
            actions = load_corporate_actions(config.data.daily_root, held)

        engine = MinuteBacktestEngine(config)
        if previous_state is not None:
            engine.import_state(previous_state)
        result = engine.run_stream([bars], target_weights, actions, record_frequency="daily")
        state = engine.export_state()
        end_nav = float(result.nav.iloc[-1]["nav"])
        # 必须直接从日终状态读取；逐分钟 positions 表可能含已在盘中卖光的股票。
        end_positions = pd.DataFrame([
            {
                "date": date,
                "code": code,
                "shares": position.shares,
                "close": engine.last_prices.get(code),
                "market_value": position.shares * engine.last_prices[code],
            }
            for code, position in sorted(engine.positions.items()) if position.shares > 0
        ], columns=["date", "code", "shares", "close", "market_value"])
        stale = sorted(
            code for code, position in engine.positions.items()
            if position.shares > 0 and engine._last_price_date.get(code) != date
        )
        snapshot = {
            "date": str(date.date()),
            "configuration": signature,
            "universe_history_digest": _universe_history_digest(universe, date),
            "previous_nav": float(previous_nav),
            "end_nav": end_nav,
            "daily_return": float(end_nav / previous_nav - 1),
            "stale_price_positions": stale,
            "state": state,
        }
        if stale:
            print(f"警告：{len(stale)} 个持仓使用此前交易日最新可得价格估值：{stale[:8]}")
        destination = days_root / str(date.date())
        if destination.exists():
            raise FileExistsError(f"账户日期文件夹已存在: {destination}")
        with tempfile.TemporaryDirectory(prefix=f".{date.date()}-", dir=days_root) as tmp:
            working = Path(tmp)
            (working / "snapshot.json").write_text(
                json.dumps(snapshot, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            (result.orders if not result.orders.empty else
             pd.DataFrame(columns=[field.name for field in fields(Order)])
             ).to_parquet(working / "orders.parquet", index=False)
            (result.fills if not result.fills.empty else
             pd.DataFrame(columns=[field.name for field in fields(Fill)])
             ).to_parquet(working / "fills.parquet", index=False)
            end_positions.to_parquet(working / "positions.parquet", index=False)
            result.nav.tail(1).to_parquet(working / "daily_nav.parquet", index=False)
            os.replace(working, destination)
        rebuild_paper_daily_nav(account_root)
        return destination


def _config_signature(config: MinuteBacktestConfig) -> str:
    """锁定影响交易结果的参数；信号文件允许逐日追加内容。"""
    fields = {
        "index": config.universe.index_code,
        "members_file": str(config.universe.members_root / "000852.SH.csv"),
        "target_file": str(config.targets.path),
        "target_mode": config.targets.mode,
        "rebalance_interval": config.targets.rebalance_interval,
        "initial_capital": config.account.initial_capital,
        "rights_issue_policy": config.account.rights_issue_policy,
        "execution": asdict(config.execution),
        "costs": asdict(config.costs),
    }
    return hashlib.sha256(json.dumps(fields, sort_keys=True).encode("utf-8")).hexdigest()


def _universe_history_digest(universe: HistoricalIndexUniverse, date: pd.Timestamp) -> str:
    """锁定已发生日期的历史成份；未来新纳入的记录不影响已有账户。"""
    history = universe.intervals[universe.intervals["start_date"] <= date].copy()
    # 尚未生效的未来剔除信息对该日历史成份没有影响。
    history["end_date"] = history["end_date"].where(history["end_date"] <= date, pd.NaT)
    rows = [
        [str(item["asset_code"]), str(item["start_date"]),
         None if pd.isna(item["end_date"]) else str(item["end_date"])]
        for item in history.to_dict("records")
    ]
    return hashlib.sha256(json.dumps(rows, sort_keys=True).encode("utf-8")).hexdigest()


@contextmanager
def _account_lock(lock_path: Path) -> Iterator[None]:
    with lock_path.open("a") as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(lock.fileno(), fcntl.LOCK_UN)


def rebuild_paper_daily_nav(account_root: Path) -> Path:
    """从每日日终快照重建累计账户净值 CSV，不依赖增量追加或重复记账。"""
    root = Path(account_root)
    rows = []
    for folder in sorted((root / "days").iterdir()):
        if not folder.is_dir() or folder.name.startswith("."):
            continue
        info = json.loads((folder / "snapshot.json").read_text(encoding="utf-8"))
        rows.append({
            "date": info["date"],
            "previous_nav": info["previous_nav"],
            "nav": info["end_nav"],
            "return": info["daily_return"],
            "cash": info["state"]["cash"],
            "position_count": len(info["state"]["positions"]),
            "stale_price_count": len(info["stale_price_positions"]),
        })
    summary = pd.DataFrame(rows)
    if not summary.empty:
        initial_capital = float(summary.iloc[0]["previous_nav"])
        summary["unit_nav"] = summary["nav"] / initial_capital
        summary["cumulative_return"] = summary["unit_nav"] - 1
    with tempfile.NamedTemporaryFile(
        mode="w", encoding="utf-8", prefix=".daily_nav_", suffix=".tmp",
        dir=root, delete=False,
    ) as temporary_file:
        temp_path = Path(temporary_file.name)
    try:
        summary.to_csv(temp_path, index=False)
        os.replace(temp_path, root / "daily_nav.csv")
    finally:
        temp_path.unlink(missing_ok=True)
    return root / "daily_nav.csv"
