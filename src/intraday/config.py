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
    """描述分钟归档、日线参考数据和按需缓存位置。"""

    minute_root: Path
    daily_root: Path | None
    cache_root: Path
    universe_name: str
    start_date: pd.Timestamp
    end_date: pd.Timestamp
    daily_status_path: Path | None = None


@dataclass(frozen=True)
class UniverseConfig:
    """历史指数成份根目录（内含 000852.SH.csv）与固定指数代码。"""

    members_root: Path
    index_code: str = "000852.SH"


@dataclass(frozen=True)
class StrategyImplementationConfig:
    """描述一个可动态导入的分钟日频策略。"""

    module: str
    class_name: str
    params: dict[str, Any]


@dataclass(frozen=True)
class TargetConfig:
    """描述外部目标文件或分钟日频策略。"""

    path: Path | None
    date_only_signal_time: str
    mode: str = "file"
    universe_path: Path | None = None
    implementation: StrategyImplementationConfig | None = None
    rebalance_interval: int | None = None
    # 只有 targets.mode=factor_layers 时使用，单策略回测不依赖因子分层。
    layer_count: int = 10
    factor_column: str = "factor_value"
    descending: bool = False


@dataclass(frozen=True)
class AccountConfig:
    """多头现金账户边界。"""

    initial_capital: float
    rights_issue_policy: str = "subscribe_or_fail"


@dataclass(frozen=True)
class ExecutionConfig:
    """唯一的固定时间窗口分钟成交规则；窗口边界在加载配置时推导。"""

    slippage_bps: float
    max_participation_rate: float
    block_one_price_limit: bool
    enforce_t_plus_one: bool
    order_time: str = "10:00:00"
    window_start: str = "10:01:00"
    window_end: str = "10:05:00"
    retry_unfilled_days: int = 5
    require_daily_limit_data: bool = False


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
    universe: UniverseConfig | None = None


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
        optional={"universe"},
    )
    data_values = _mapping(raw_values["data"], "data")
    target_values = _mapping(raw_values["targets"], "targets")
    account_values = _mapping(raw_values["account"], "account")
    execution_values = _mapping(raw_values["execution"], "execution")
    cost_values = _mapping(raw_values["costs"], "costs")

    config = MinuteBacktestConfig(
        path=resolved_path,
        run_name=_nonempty_string(raw_values["run_name"], "run_name"),
        output_root=_resolve_path(resolved_path, raw_values["output_root"]),
        data=_load_data_config(resolved_path, data_values),
        targets=_load_target_config(resolved_path, target_values),
        account=_load_account_config(account_values),
        execution=_load_execution_config(execution_values),
        costs=_load_cost_config(cost_values),
        raw=dict(raw_values),
        universe=_load_universe_config(resolved_path, raw_values.get("universe")),
    )
    if (
        config.targets.mode in {"strategy", "factor_layers"}
        and config.universe is None and config.targets.universe_path is None
    ):
        raise ValueError("策略或分层需要 universe.members_root 或 targets.universe_path")
    if config.targets.mode == "factor_layers" and config.universe is None:
        raise ValueError("正式分层要求真实中证1000历史成份 universe.members_root")
    if config.execution.require_daily_limit_data and config.data.daily_status_path is None:
        raise ValueError("execution.require_daily_limit_data=true 时必须配置 data.daily_status_path")
    return config


def _load_universe_config(config_path: Path, value: Any) -> UniverseConfig | None:
    if value is None:
        return None  # 兼容老配置；新版本正式账户必须提供历史成份文件
    values = _mapping(value, "universe")
    _check_keys(values, {"members_root"}, "universe", optional={"index_code"})
    index_code = str(values.get("index_code", "000852.SH"))
    if index_code != "000852.SH":
        raise ValueError("正式股票池固定为中证1000（000852.SH）")
    root = _existing_directory(config_path, values["members_root"], "universe.members_root")
    if not (root / f"{index_code}.csv").is_file():
        raise FileNotFoundError(f"缺少历史成份文件: {root / (index_code + '.csv')}")
    return UniverseConfig(members_root=root, index_code=index_code)


def _load_data_config(
    config_path: Path,
    values: Mapping[str, Any],
) -> MinuteDataConfig:
    _check_keys(
        values,
        {"minute_root", "daily_root", "cache_root", "universe_name", "start_date", "end_date"},
        "data",
        optional={"daily_status_path"},
    )
    start_date = _date(values["start_date"], "data.start_date")
    end_date = _date(values["end_date"], "data.end_date")
    if end_date < start_date:
        raise ValueError("data.end_date 不能早于 data.start_date")
    return MinuteDataConfig(
        minute_root=_existing_directory(config_path, values["minute_root"], "data.minute_root"),
        daily_root=_optional_existing_directory(
            config_path,
            values["daily_root"],
            "data.daily_root",
        ),
        cache_root=_resolve_path(config_path, values["cache_root"]),
        universe_name=_nonempty_string(values["universe_name"], "data.universe_name"),
        start_date=start_date,
        end_date=end_date,
        daily_status_path=_optional_existing_file(
            config_path,
            values.get("daily_status_path"),
            "data.daily_status_path",
        ),
    )


def _load_target_config(
    config_path: Path,
    values: Mapping[str, Any],
) -> TargetConfig:
    _check_keys(
        values,
        set(),
        "targets",
        optional={
            "mode",
            "path",
            "date_only_signal_time",
            "universe_path",
            "implementation", "rebalance_interval", "layer_count", "factor_column", "descending",
        },
    )
    mode = str(values.get("mode", "file")).strip()
    if mode not in {"file", "strategy_output", "strategy", "factor_layers"}:
        raise ValueError("targets.mode 只支持 file、strategy_output、strategy 或 factor_layers")

    signal_time = _nonempty_string(
        values.get("date_only_signal_time", "15:00:00"),
        "targets.date_only_signal_time",
    )
    try:
        pd.Timestamp(f"2000-01-01 {signal_time}")
    except ValueError as error:
        raise ValueError("targets.date_only_signal_time 不是有效时间") from error

    if mode in {"file", "strategy_output", "factor_layers"}:
        target_path = _required_existing_file(config_path, values.get("path"), "targets.path")
        if values.get("universe_path") is not None or values.get("implementation") is not None:
            raise ValueError("文件目标模式不能配置 universe_path 或 implementation")
        interval = values.get("rebalance_interval")
        if mode == "strategy_output":
            interval = _positive_integer(interval, "targets.rebalance_interval")
        elif interval is not None:
            raise ValueError("仅 strategy_output 需要 targets.rebalance_interval")
        if mode == "factor_layers":
            layer_count = _positive_integer(values.get("layer_count", 10), "targets.layer_count")
            if layer_count < 2 or layer_count > 100:
                raise ValueError("targets.layer_count 必须为2至100")
            factor_column = _nonempty_string(values.get("factor_column", "factor_value"), "targets.factor_column")
            descending = _boolean(values.get("descending", False), "targets.descending")
        else:
            if any(name in values for name in ("layer_count", "factor_column", "descending")):
                raise ValueError("分层参数只允许在 targets.mode=factor_layers 使用")
            layer_count, factor_column, descending = 10, "factor_value", False
        return TargetConfig(
            mode=mode, path=target_path, date_only_signal_time=signal_time,
            universe_path=None, implementation=None, rebalance_interval=interval,
            layer_count=layer_count, factor_column=factor_column, descending=descending,
        )

    if values.get("path") is not None or values.get("rebalance_interval") is not None:
        raise ValueError("targets.mode=strategy 时不能配置 path 或 rebalance_interval")
    if any(name in values for name in ("layer_count", "factor_column", "descending")):
        raise ValueError("分层参数只允许在 targets.mode=factor_layers 使用")
    universe_path = _optional_existing_file(
        config_path, values.get("universe_path"), "targets.universe_path",
    )
    implementation_values = _mapping(values.get("implementation"), "targets.implementation")
    _check_keys(
        implementation_values,
        {"module", "class"},
        "targets.implementation",
        optional={"params"},
    )
    params = implementation_values.get("params", {})
    if not isinstance(params, Mapping):
        raise TypeError("targets.implementation.params 必须是映射")
    implementation = StrategyImplementationConfig(
        module=_nonempty_string(implementation_values["module"], "targets.implementation.module"),
        class_name=_nonempty_string(
            implementation_values["class"],
            "targets.implementation.class",
        ),
        params=dict(params),
    )
    return TargetConfig(
        mode=mode,
        path=None,
        date_only_signal_time=signal_time,
        universe_path=universe_path,
        implementation=implementation,
    )


def _load_account_config(values: Mapping[str, Any]) -> AccountConfig:
    _check_keys(values, {"initial_capital"}, "account", optional={"rights_issue_policy"})
    rights_issue_policy = str(values.get("rights_issue_policy", "subscribe_or_fail")).strip()
    if rights_issue_policy not in {"subscribe_or_fail", "ignore"}:
        raise ValueError("account.rights_issue_policy 只支持 subscribe_or_fail 或 ignore")
    return AccountConfig(
        initial_capital=_positive_number(values["initial_capital"], "account.initial_capital"),
        rights_issue_policy=rights_issue_policy,
    )


def _load_execution_config(values: Mapping[str, Any]) -> ExecutionConfig:
    """正式回测只支持一套固定成交窗口，不读取已停用的参数。"""
    _check_keys(
        values,
        {"slippage_bps", "max_participation_rate", "block_one_price_limit", "enforce_t_plus_one"},
        "execution",
        optional={"order_time", "window_bars", "retry_unfilled_days", "require_daily_limit_data"},
    )
    order_time = _clock_time(values.get("order_time", "10:00:00"), "execution.order_time")
    window_bars = _positive_integer(values.get("window_bars", 5), "execution.window_bars")
    window_start, window_end = _derive_execution_window(order_time, window_bars)
    retry_days = values.get("retry_unfilled_days", 5)
    if not isinstance(retry_days, int) or isinstance(retry_days, bool) or retry_days < 0:
        raise ValueError("execution.retry_unfilled_days 必须是非负整数")
    return ExecutionConfig(
        slippage_bps=_nonnegative_number(values["slippage_bps"], "execution.slippage_bps"),
        max_participation_rate=_rate(
            values["max_participation_rate"], "execution.max_participation_rate", allow_one=True,
        ),
        block_one_price_limit=_boolean(values["block_one_price_limit"], "execution.block_one_price_limit"),
        enforce_t_plus_one=_boolean(values["enforce_t_plus_one"], "execution.enforce_t_plus_one"),
        order_time=order_time,
        window_start=window_start,
        window_end=window_end,
        retry_unfilled_days=retry_days,
        require_daily_limit_data=_boolean(
            values.get("require_daily_limit_data", False), "execution.require_daily_limit_data",
        ),
    )


def _load_cost_config(values: Mapping[str, Any]) -> CostConfig:
    _check_keys(
        values,
        {
            "commission_rate",
            "minimum_commission",
            "transfer_fee_rate",
            "stamp_duty_rate_before_20230828",
            "stamp_duty_rate_from_20230828",
        },
        "costs",
    )
    return CostConfig(
        commission_rate=_rate(values["commission_rate"], "costs.commission_rate"),
        minimum_commission=_nonnegative_number(
            values["minimum_commission"],
            "costs.minimum_commission",
        ),
        transfer_fee_rate=_rate(values["transfer_fee_rate"], "costs.transfer_fee_rate"),
        stamp_duty_rate_before_20230828=_rate(
            values["stamp_duty_rate_before_20230828"],
            "costs.stamp_duty_rate_before_20230828",
        ),
        stamp_duty_rate_from_20230828=_rate(
            values["stamp_duty_rate_from_20230828"],
            "costs.stamp_duty_rate_from_20230828",
        ),
    )


def _mapping(value: Any, location: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise TypeError(f"{location} 必须是映射")
    return value


def _check_keys(
    values: Mapping[str, Any],
    required: set[str],
    location: str,
    optional: set[str] | None = None,
) -> None:
    optional_keys = optional or set()
    missing_keys = required - set(values)
    unknown_keys = set(values) - required - optional_keys
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


def _required_existing_file(config_path: Path, value: Any, location: str) -> Path:
    if value is None:
        raise ValueError(f"{location} 不能为空")
    path = _resolve_path(config_path, value)
    if not path.is_file():
        raise FileNotFoundError(f"{location} 文件不存在: {path}")
    return path


def _optional_existing_file(
    config_path: Path,
    value: Any,
    location: str,
) -> Path | None:
    if value is None:
        return None
    return _required_existing_file(config_path, value, location)


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


def _clock_time(value: Any, location: str) -> str:
    """将执行时刻标准化，按字典序也能正确比较。"""
    from datetime import time

    if not isinstance(value, str):
        raise TypeError(f"{location} 必须是 HH:MM[:SS] 字符串")
    try:
        return time.fromisoformat(value).strftime("%H:%M:%S")
    except ValueError as error:
        raise ValueError(f"{location} 必须是有效的 HH:MM[:SS] 时刻") from error


def _derive_execution_window(order_time: str, window_bars: int) -> tuple[str, str]:
    """从指定发单分钟起取后续 N 根已结束的交易时段分钟K线，自动跳过午休。"""
    hh, mm, ss = map(int, order_time.split(":"))
    if ss != 0:
        raise ValueError("固定窗口的 execution.order_time 只能精确到整分钟")
    reference = hh * 60 + mm
    valid = list(range(9 * 60 + 31, 11 * 60 + 31)) + list(
        range(13 * 60 + 1, 15 * 60 + 1)
    )
    subsequent = [minute for minute in valid if minute > reference]
    in_session = (9 * 60 + 31 <= reference <= 11 * 60 + 30) or (
        13 * 60 <= reference < 15 * 60
    )
    if not in_session or not subsequent:
        raise ValueError("发单时刻须在 09:31—11:30 或 13:00—14:59 之间")
    if len(subsequent) < window_bars:
        raise ValueError("交易日剩余分钟数量不足以覆盖 window_bars")
    def stamp(value: int) -> str:
        return f"{value // 60:02d}:{value % 60:02d}:00"
    return stamp(subsequent[0]), stamp(subsequent[window_bars - 1])


