"""读取并校验分钟账户回测配置。"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas as pd
import yaml


@dataclass(frozen=True)
class MinuteDataConfig:
    """描述 zxy 分钟归档、日线参考数据和按需缓存位置。"""

    minute_root: Path
    daily_root: Path | None
    cache_root: Path
    universe_name: str
    start_date: pd.Timestamp
    end_date: pd.Timestamp


@dataclass(frozen=True)
class TargetConfig:
    """描述统一目标仓位文件及日期输入的可得时刻。"""

    path: Path
    date_only_signal_time: str


@dataclass(frozen=True)
class AccountConfig:
    """描述首版多头现金账户边界。"""

    initial_capital: float
    liquidate_at_end: bool


@dataclass(frozen=True)
class ExecutionConfig:
    """描述分钟 bar 撮合、容量和 A 股交易约束。"""

    slippage_bps: float
    max_participation_rate: float
    lot_size: int
    execution_delay_bars: int
    time_in_force: str
    block_one_price_limit: bool
    enforce_t_plus_one: bool


@dataclass(frozen=True)
class CostConfig:
    """描述佣金、印花税和过户费口径。"""

    commission_rate: float
    minimum_commission: float
    transfer_fee_rate: float
    stamp_duty_rate_before_20230828: float
    stamp_duty_rate_from_20230828: float


@dataclass(frozen=True)
class MinuteBacktestConfig:
    """保存一次分钟回测的完整、已解析配置。"""

    path: Path
    run_name: str
    output_root: Path
    data: MinuteDataConfig
    targets: TargetConfig
    account: AccountConfig
    execution: ExecutionConfig
    costs: CostConfig
    raw: dict[str, Any]


def load_minute_config(config_path: str | Path) -> MinuteBacktestConfig:
    """读取 YAML，并把所有路径解析为绝对路径。"""
    resolved_path = Path(config_path).expanduser().resolve()
    raw_values = yaml.safe_load(resolved_path.read_text(encoding="utf-8"))
    if not isinstance(raw_values, Mapping):
        raise TypeError("分钟回测配置必须是映射")

    _check_keys(
        raw_values,
        {"run_name", "output_root", "data", "targets", "account", "execution", "costs"},
        "root",
    )
    run_name = _nonempty_string(raw_values["run_name"], "run_name")
    data_values = _mapping(raw_values["data"], "data")
    target_values = _mapping(raw_values["targets"], "targets")
    account_values = _mapping(raw_values["account"], "account")
    execution_values = _mapping(raw_values["execution"], "execution")
    cost_values = _mapping(raw_values["costs"], "costs")

    _check_keys(
        data_values,
        {"minute_root", "daily_root", "cache_root", "universe_name", "start_date", "end_date"},
        "data",
    )
    start_date = _date(data_values["start_date"], "data.start_date")
    end_date = _date(data_values["end_date"], "data.end_date")
    if end_date < start_date:
        raise ValueError("data.end_date 不能早于 data.start_date")
    data_config = MinuteDataConfig(
        minute_root=_existing_directory(
            resolved_path,
            data_values["minute_root"],
            "data.minute_root",
        ),
        daily_root=_optional_existing_directory(
            resolved_path,
            data_values["daily_root"],
            "data.daily_root",
        ),
        cache_root=_resolve_path(resolved_path, data_values["cache_root"]),
        universe_name=_nonempty_string(data_values["universe_name"], "data.universe_name"),
        start_date=start_date,
        end_date=end_date,
    )

    _check_keys(target_values, {"path", "date_only_signal_time"}, "targets")
    target_path = _resolve_path(resolved_path, target_values["path"])
    if not target_path.is_file():
        raise FileNotFoundError(f"目标仓位文件不存在: {target_path}")
    signal_time = _nonempty_string(
        target_values["date_only_signal_time"],
        "targets.date_only_signal_time",
    )
    try:
        pd.Timestamp(f"2000-01-01 {signal_time}")
    except ValueError as error:
        raise ValueError("targets.date_only_signal_time 不是有效时间") from error
    target_config = TargetConfig(
        path=target_path,
        date_only_signal_time=signal_time,
    )

    _check_keys(account_values, {"initial_capital", "liquidate_at_end"}, "account")
    initial_capital = _positive_number(
        account_values["initial_capital"],
        "account.initial_capital",
    )
    liquidate_at_end = _boolean(
        account_values["liquidate_at_end"],
        "account.liquidate_at_end",
    )
    account_config = AccountConfig(
        initial_capital=initial_capital,
        liquidate_at_end=liquidate_at_end,
    )

    _check_keys(
        execution_values,
        {
            "slippage_bps",
            "max_participation_rate",
            "lot_size",
            "execution_delay_bars",
            "time_in_force",
            "block_one_price_limit",
            "enforce_t_plus_one",
        },
        "execution",
    )
    time_in_force = _nonempty_string(
        execution_values["time_in_force"],
        "execution.time_in_force",
    )
    if time_in_force != "day":
        raise ValueError("首版 execution.time_in_force 只支持 day")
    execution_config = ExecutionConfig(
        slippage_bps=_nonnegative_number(
            execution_values["slippage_bps"],
            "execution.slippage_bps",
        ),
        max_participation_rate=_rate(
            execution_values["max_participation_rate"],
            "execution.max_participation_rate",
            allow_one=True,
        ),
        lot_size=_positive_integer(execution_values["lot_size"], "execution.lot_size"),
        execution_delay_bars=_positive_integer(
            execution_values["execution_delay_bars"],
            "execution.execution_delay_bars",
        ),
        time_in_force=time_in_force,
        block_one_price_limit=_boolean(
            execution_values["block_one_price_limit"],
            "execution.block_one_price_limit",
        ),
        enforce_t_plus_one=_boolean(
            execution_values["enforce_t_plus_one"],
            "execution.enforce_t_plus_one",
        ),
    )

    _check_keys(
        cost_values,
        {
            "commission_rate",
            "minimum_commission",
            "transfer_fee_rate",
            "stamp_duty_rate_before_20230828",
            "stamp_duty_rate_from_20230828",
        },
        "costs",
    )
    cost_config = CostConfig(
        commission_rate=_rate(cost_values["commission_rate"], "costs.commission_rate"),
        minimum_commission=_nonnegative_number(
            cost_values["minimum_commission"],
            "costs.minimum_commission",
        ),
        transfer_fee_rate=_rate(
            cost_values["transfer_fee_rate"],
            "costs.transfer_fee_rate",
        ),
        stamp_duty_rate_before_20230828=_rate(
            cost_values["stamp_duty_rate_before_20230828"],
            "costs.stamp_duty_rate_before_20230828",
        ),
        stamp_duty_rate_from_20230828=_rate(
            cost_values["stamp_duty_rate_from_20230828"],
            "costs.stamp_duty_rate_from_20230828",
        ),
    )
    return MinuteBacktestConfig(
        path=resolved_path,
        run_name=run_name,
        output_root=_resolve_path(resolved_path, raw_values["output_root"]),
        data=data_config,
        targets=target_config,
        account=account_config,
        execution=execution_config,
        costs=cost_config,
        raw=dict(raw_values),
    )


def _mapping(value: Any, location: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise TypeError(f"{location} 必须是映射")
    return value


def _check_keys(values: Mapping[str, Any], expected: set[str], location: str) -> None:
    missing_keys = expected - set(values)
    unknown_keys = set(values) - expected
    if missing_keys:
        raise ValueError(f"{location} 缺少字段: {sorted(missing_keys)}")
    if unknown_keys:
        raise ValueError(f"{location} 包含未知字段: {sorted(unknown_keys)}")


def _resolve_path(config_path: Path, value: Any) -> Path:
    path = Path(_nonempty_string(value, "path")).expanduser()
    if path.is_absolute():
        return path.resolve()
    return (config_path.parent / path).resolve()


def _existing_directory(config_path: Path, value: Any, location: str) -> Path:
    path = _resolve_path(config_path, value)
    if not path.is_dir():
        raise NotADirectoryError(f"{location} 目录不存在: {path}")
    return path


def _optional_existing_directory(
    config_path: Path,
    value: Any,
    location: str,
) -> Path | None:
    if value is None:
        return None
    return _existing_directory(config_path, value, location)


def _nonempty_string(value: Any, location: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{location} 必须是非空字符串")
    return value.strip()


def _date(value: Any, location: str) -> pd.Timestamp:
    timestamp = pd.Timestamp(value)
    if pd.isna(timestamp):
        raise ValueError(f"{location} 不是有效日期")
    return timestamp.normalize().tz_localize(None)


def _positive_number(value: Any, location: str) -> float:
    number = float(value)
    if number <= 0:
        raise ValueError(f"{location} 必须大于 0")
    return number


def _nonnegative_number(value: Any, location: str) -> float:
    number = float(value)
    if number < 0:
        raise ValueError(f"{location} 不能小于 0")
    return number


def _positive_integer(value: Any, location: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        raise ValueError(f"{location} 必须是正整数")
    return value


def _rate(value: Any, location: str, allow_one: bool = False) -> float:
    rate = _nonnegative_number(value, location)
    upper_bound_valid = rate <= 1 if allow_one else rate < 1
    if not upper_bound_valid:
        bracket = "[0, 1]" if allow_one else "[0, 1)"
        raise ValueError(f"{location} 必须位于 {bracket}")
    return rate


def _boolean(value: Any, location: str) -> bool:
    if not isinstance(value, bool):
        raise TypeError(f"{location} 必须是布尔值")
    return value
