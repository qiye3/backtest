"""生成频率感知的因子时序算子规格并计算单个变体。"""

from __future__ import annotations

from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

SUPPORTED_FREQUENCIES = {
    "daily",
    "weekly",
    "monthly",
    "quarterly",
    "annual",
}
PERIODS_PER_YEAR = {
    "daily": 252,
    "weekly": 52,
    "monthly": 12,
    "quarterly": 4,
    "annual": 1,
}
CORE_OPERATOR_IDS = (
    "raw",
    "qtile_M12",
    "qtile_M24",
    "zscore_K12",
    "zscore_K24",
    "chg_K1",
    "qtilechg_K24_K1",
    "zchg_K24_K1",
)


@dataclass(frozen=True)
class OperatorSpec:
    """描述一个稳定命名的时间序列算子。"""

    operator_id: str
    kind: str
    params: Mapping[str, int] = field(default_factory=dict)
    operator_set: str = "set2"


@dataclass(frozen=True)
class FactorVariant:
    """保存一个可以立即写出的因子时序变体。"""

    name: str
    target_frequency: str
    operator: OperatorSpec
    values: pd.DataFrame


def target_frequencies(source_frequency: str, mode: str) -> tuple[str, ...]:
    """返回当前搜索模式需要计算的原生及派生频率。"""
    _validate_frequency(source_frequency)
    if mode != "all":
        return (source_frequency,)
    if source_frequency == "daily":
        return ("daily", "weekly", "monthly")
    if source_frequency == "weekly":
        return ("weekly", "monthly")
    return (source_frequency,)


def operator_specs(
    frequency: str,
    mode: str,
    include_average_growth: bool,
) -> tuple[OperatorSpec, ...]:
    """按频率和模式返回去重后的算子列表。"""
    _validate_frequency(frequency)
    if mode == "raw":
        return (OperatorSpec("raw", "raw"),)
    if mode == "core":
        if frequency == "quarterly":
            return _quarterly_set2_specs()
        if frequency not in {"daily", "weekly"}:
            return (OperatorSpec("raw", "raw"),)
        core_ids = set(CORE_OPERATOR_IDS)
        return tuple(
            spec
            for spec in _set2_specs(frequency)
            if spec.operator_id in core_ids
        )
    if mode != "all":
        raise ValueError(f"未知算子模式: {mode}")

    specs = [OperatorSpec("raw", "raw")]
    specs.extend(_set1_specs())
    if frequency in {"daily", "weekly"}:
        specs.extend(_set2_specs(frequency))
    elif frequency == "quarterly":
        specs.extend(_quarterly_set2_specs())
    if include_average_growth:
        specs.extend(_set3_specs())
    return _deduplicate_specs(specs)


def planned_variant_names(
    base_name: str,
    source_frequency: str,
    mode: str,
    include_average_growth: bool,
) -> tuple[str, ...]:
    """在不读取数据时列出一次搜索会生成的全部稳定名称。"""
    return tuple(
        _variant_name(base_name, frequency, spec.operator_id)
        for frequency in target_frequencies(source_frequency, mode)
        for spec in operator_specs(
            frequency,
            mode,
            include_average_growth,
        )
    )


def iter_factor_variants(
    base_name: str,
    factor_values: pd.DataFrame,
    source_frequency: str,
    mode: str,
    include_average_growth: bool,
    trading_calendar: pd.DatetimeIndex,
    quarterly_events: pd.DataFrame | None = None,
) -> Iterator[FactorVariant]:
    """逐个计算变体，避免全量搜索同时占用内存。"""
    if mode == "raw":
        raw_spec = OperatorSpec("raw", "raw")
        yield _build_variant(
            base_name,
            source_frequency,
            raw_spec,
            _restore_to_calendar(factor_values, trading_calendar),
        )
        return
    if source_frequency == "quarterly" and mode != "raw":
        if quarterly_events is None:
            raise ValueError(
                "季度非 raw 算子必须由正式 Factor 提供公告事件历史"
            )

    for target_frequency in target_frequencies(source_frequency, mode):
        specs = operator_specs(
            target_frequency,
            mode,
            include_average_growth,
        )
        if source_frequency == "quarterly" and quarterly_events is not None:
            for spec in specs:
                transformed = _apply_quarterly_event_operator(
                    quarterly_events,
                    factor_values.columns,
                    trading_calendar,
                    spec,
                )
                yield _build_variant(
                    base_name,
                    target_frequency,
                    spec,
                    transformed,
                )
            continue

        if len(specs) == 1 and specs[0].kind == "raw":
            native_values = factor_values
        else:
            native_values = _aggregate_to_frequency(
                factor_values,
                source_frequency,
                target_frequency,
            )
        for spec in specs:
            transformed_native = apply_operator(
                native_values,
                target_frequency,
                spec,
            )
            transformed = _restore_to_calendar(
                transformed_native,
                trading_calendar,
            )
            yield _build_variant(
                base_name,
                target_frequency,
                spec,
                transformed,
            )


def apply_operator(
    factor_values: pd.DataFrame,
    frequency: str,
    spec: OperatorSpec,
) -> pd.DataFrame:
    """在原生频率面板上应用一个确定的时序算子。"""
    periods_per_year = PERIODS_PER_YEAR[frequency]
    operator_kind = spec.kind
    params = spec.params
    if operator_kind == "raw":
        return factor_values.copy()
    if spec.operator_set == "set1":
        return _apply_set1_operator(
            factor_values,
            periods_per_year,
            operator_kind,
            params,
        )
    if spec.operator_set == "set3":
        years = int(params["N"])
        window = max(2, years * periods_per_year)
        return _rolling_average_growth(
            factor_values,
            window,
            max(2, window // 2),
        )
    return _apply_set2_operator(
        factor_values,
        frequency,
        operator_kind,
        params,
    )


def _set1_specs() -> list[OperatorSpec]:
    specs = []
    for years in range(1, 6):
        specs.append(
            OperatorSpec(
                f"mean_N{years}",
                "mean",
                {"N": years},
                "set1",
            )
        )
    for years in range(1, 6):
        specs.append(
            OperatorSpec(
                f"std_N{years}",
                "std",
                {"N": years},
                "set1",
            )
        )
    for years in range(1, 6):
        specs.append(
            OperatorSpec(
                f"zscore_N{years}",
                "zscore",
                {"N": years},
                "set1",
            )
        )
    for years in range(1, 6):
        specs.append(
            OperatorSpec(
                f"cv_N{years}",
                "cv",
                {"N": years},
                "set1",
            )
        )
    specs.extend(
        [
            OperatorSpec("qoq_diff", "qoq_diff", operator_set="set1"),
            OperatorSpec("qoq_pct", "qoq_pct", operator_set="set1"),
            OperatorSpec("yoy_diff", "yoy_diff", operator_set="set1"),
            OperatorSpec("yoy_pct", "yoy_pct", operator_set="set1"),
        ]
    )
    for years in range(1, 6):
        specs.append(
            OperatorSpec(
                f"trend_slope_N{years}",
                "trend_slope",
                {"N": years},
                "set1",
            )
        )
    for years in range(1, 6):
        specs.append(
            OperatorSpec(
                f"trend_improve_N{years}",
                "trend_improve",
                {"N": years},
                "set1",
            )
        )
    for years in range(1, 6):
        specs.append(
            OperatorSpec(
                f"quantile_N{years}",
                "quantile_N",
                {"N": years},
                "set1",
            )
        )
    for months in (1, 3, 6, 12):
        specs.append(
            OperatorSpec(
                f"quantile_K{months}",
                "quantile_K",
                {"K": months},
                "set1",
            )
        )
    return specs


def _set2_specs(frequency: str) -> list[OperatorSpec]:
    months_per_bar = 20 if frequency == "daily" else 4
    specs = [OperatorSpec("raw", "raw")]
    for months in (6, 12, 24, 60):
        specs.append(
            OperatorSpec(
                f"qtile_M{months}",
                "qtile",
                {"M": months, "mpb": months_per_bar},
            )
        )
    for short_months in (1, 2, 3):
        for long_months in (3, 6, 12, 24, 60):
            specs.append(
                OperatorSpec(
                    f"dev_K{short_months}_K{long_months}",
                    "dev",
                    {
                        "K1": short_months,
                        "K2": long_months,
                        "mpb": months_per_bar,
                    },
                )
            )
    for months in (6, 12, 24, 36, 60):
        specs.append(
            OperatorSpec(
                f"zscore_K{months}",
                "zscore",
                {"K": months, "mpb": months_per_bar},
            )
        )
    for months in (1, 2, 3, 6):
        specs.append(
            OperatorSpec(
                f"chg_K{months}",
                "chg",
                {"K": months, "mpb": months_per_bar},
            )
        )
        specs.append(
            OperatorSpec(
                f"pctchg_K{months}",
                "pctchg",
                {"K": months, "mpb": months_per_bar},
            )
        )
    for history_months in (6, 12, 24, 60):
        for change_months in (1, 2, 3, 6):
            specs.append(
                OperatorSpec(
                    f"qtilechg_K{history_months}_K{change_months}",
                    "qtilechg",
                    {
                        "K1": history_months,
                        "K2": change_months,
                        "mpb": months_per_bar,
                    },
                )
            )
    for history_months in (6, 12, 24, 36, 60):
        for change_months in (1, 2, 3):
            specs.append(
                OperatorSpec(
                    f"zchg_K{history_months}_K{change_months}",
                    "zchg",
                    {
                        "K1": history_months,
                        "K2": change_months,
                        "mpb": months_per_bar,
                    },
                )
            )
    return specs


def _quarterly_set2_specs() -> tuple[OperatorSpec, ...]:
    return (
        OperatorSpec("raw", "raw"),
        OperatorSpec("qoq", "qoq"),
        OperatorSpec("yoy", "yoy"),
        OperatorSpec("qtile8", "qtile8"),
    )


def _set3_specs() -> list[OperatorSpec]:
    return [
        OperatorSpec(
            f"avg_growth_N{years}",
            "avg_growth",
            {"N": years},
            "set3",
        )
        for years in range(1, 6)
    ]


def _deduplicate_specs(specs: Sequence[OperatorSpec]) -> tuple[OperatorSpec, ...]:
    unique_specs: dict[str, OperatorSpec] = {}
    for spec in specs:
        unique_specs.setdefault(spec.operator_id, spec)
    return tuple(unique_specs.values())


def _apply_set1_operator(
    factor_values: pd.DataFrame,
    periods_per_year: int,
    operator_kind: str,
    params: Mapping[str, int],
) -> pd.DataFrame:
    years = int(params.get("N", 1))
    window = max(1, years * periods_per_year)
    statistical_window = max(2, window)
    statistical_minimum = max(2, statistical_window // 2)
    if operator_kind == "mean":
        return factor_values.rolling(window, min_periods=max(1, window // 2)).mean()
    if operator_kind == "std":
        return factor_values.rolling(
            statistical_window,
            min_periods=statistical_minimum,
        ).std()
    if operator_kind == "zscore":
        return _rolling_zscore(
            factor_values,
            statistical_window,
            statistical_minimum,
        )
    if operator_kind == "cv":
        rolling_values = factor_values.rolling(
            statistical_window,
            min_periods=statistical_minimum,
        )
        return rolling_values.std() / rolling_values.mean().replace(0.0, np.nan)
    if operator_kind == "qoq_diff":
        return factor_values - factor_values.shift(1)
    if operator_kind == "qoq_pct":
        prior_values = factor_values.shift(1)
        return (factor_values - prior_values) / prior_values.abs().replace(0.0, np.nan)
    if operator_kind == "yoy_diff":
        return factor_values - factor_values.shift(periods_per_year)
    if operator_kind == "yoy_pct":
        prior_values = factor_values.shift(periods_per_year)
        return (factor_values - prior_values) / prior_values.abs().replace(0.0, np.nan)
    if operator_kind == "trend_slope":
        # 年频 N1 只有一个点，斜率至少需要当前值和上一期。
        return _rolling_slope(
            factor_values,
            statistical_window,
            statistical_minimum,
        )
    if operator_kind == "trend_improve":
        changes = factor_values.diff()
        improvements = changes.gt(0).where(changes.notna())
        return improvements.rolling(
            window,
            min_periods=max(1, window // 2),
        ).sum()
    if operator_kind == "quantile_N":
        minimum_periods = max(1, min(window, max(2, window // 2)))
        return _rolling_latest_rank(factor_values, window, minimum_periods)
    if operator_kind == "quantile_K":
        months = int(params["K"])
        month_window = max(1, int(round(months * periods_per_year / 12.0)))
        month_minimum = max(1, min(month_window, max(2, month_window // 2)))
        return _rolling_latest_rank(
            factor_values,
            month_window,
            month_minimum,
        )
    raise ValueError(f"未知第一套算子: {operator_kind}")


def _apply_set2_operator(
    factor_values: pd.DataFrame,
    frequency: str,
    operator_kind: str,
    params: Mapping[str, int],
) -> pd.DataFrame:
    if operator_kind == "raw":
        return factor_values.copy()
    if operator_kind == "qoq":
        return factor_values - factor_values.shift(1)
    if operator_kind == "yoy":
        return factor_values - factor_values.shift(4)
    if operator_kind == "qtile8":
        return _rolling_latest_rank(factor_values, 8, 8)
    if frequency not in {"daily", "weekly"}:
        raise ValueError(f"第二套月窗算子不支持频率: {frequency}")

    months_per_bar = int(params["mpb"])
    if operator_kind == "qtile":
        window = int(params["M"]) * months_per_bar
        return _rolling_latest_rank(factor_values, window, max(8, window // 2))
    if operator_kind == "dev":
        short_window = int(params["K1"]) * months_per_bar
        long_window = int(params["K2"]) * months_per_bar
        short_mean = factor_values.rolling(
            short_window,
            min_periods=max(2, short_window // 2),
        ).mean()
        long_mean = factor_values.rolling(
            long_window,
            min_periods=max(4, long_window // 2),
        ).mean()
        return short_mean / long_mean.replace(0.0, np.nan)
    if operator_kind == "zscore":
        window = int(params["K"]) * months_per_bar
        return _rolling_zscore(factor_values, window, max(4, window // 2))
    if operator_kind in {"chg", "pctchg"}:
        lag = int(params["K"]) * months_per_bar
        prior_values = factor_values.shift(lag)
        if operator_kind == "chg":
            return factor_values - prior_values
        return (factor_values - prior_values) / prior_values.abs().replace(0.0, np.nan)
    history_window = int(params["K1"]) * months_per_bar
    change_lag = int(params["K2"]) * months_per_bar
    if operator_kind == "qtilechg":
        percentile_values = _rolling_latest_rank(
            factor_values,
            history_window,
            max(8, history_window // 2),
        )
        return percentile_values - percentile_values.shift(change_lag)
    if operator_kind == "zchg":
        standardized_values = _rolling_zscore(
            factor_values,
            history_window,
            max(4, history_window // 2),
        )
        return standardized_values - standardized_values.shift(change_lag)
    raise ValueError(f"未知第二套算子: {operator_kind}")


def _aggregate_to_frequency(
    factor_values: pd.DataFrame,
    source_frequency: str,
    target_frequency: str,
) -> pd.DataFrame:
    factor_values = factor_values.sort_index()
    source_native = _sample_native_frequency(factor_values, source_frequency)
    if source_frequency == target_frequency:
        return source_native
    if source_frequency == "daily" and target_frequency == "weekly":
        rolling_values = factor_values.rolling(5, min_periods=1).mean()
        return _last_observation_per_period(rolling_values, "W-FRI")
    if source_frequency == "daily" and target_frequency == "monthly":
        rolling_values = factor_values.rolling(20, min_periods=10).mean()
        return _last_observation_per_period(rolling_values, "M")
    if source_frequency == "weekly" and target_frequency == "monthly":
        rolling_values = source_native.rolling(4, min_periods=2).mean()
        return _last_observation_per_period(rolling_values, "M")
    raise ValueError(
        f"不支持的频率聚合: {source_frequency} -> {target_frequency}"
    )


def _sample_native_frequency(
    factor_values: pd.DataFrame,
    frequency: str,
) -> pd.DataFrame:
    if frequency == "daily":
        return factor_values
    period_aliases = {
        "weekly": "W-FRI",
        "monthly": "M",
        "quarterly": "Q",
        "annual": "Y",
    }
    return _last_observation_per_period(
        factor_values,
        period_aliases[frequency],
    )


def _last_observation_per_period(
    factor_values: pd.DataFrame,
    period_alias: str,
) -> pd.DataFrame:
    period_labels = factor_values.index.to_period(period_alias)
    last_positions = ~period_labels.duplicated(keep="last")
    return factor_values.loc[last_positions]


def _restore_to_calendar(
    factor_values: pd.DataFrame,
    trading_calendar: pd.DatetimeIndex,
) -> pd.DataFrame:
    combined_dates = trading_calendar.union(factor_values.index).sort_values()
    restored = factor_values.reindex(combined_dates).ffill().reindex(trading_calendar)
    return _finite_values(restored)


def _apply_quarterly_event_operator(
    quarterly_events: pd.DataFrame,
    asset_codes: Sequence[object],
    trading_calendar: pd.DatetimeIndex,
    spec: OperatorSpec,
) -> pd.DataFrame:
    event_rows: list[dict[str, object]] = []
    for asset_code, asset_events in quarterly_events.groupby(
        "asset_code",
        sort=False,
    ):
        values_by_quarter: dict[pd.Period, float] = {}
        ordered_events = asset_events.sort_values(
            ["date", "report_period"],
            kind="mergesort",
        )
        for event_date, date_events in ordered_events.groupby("date", sort=True):
            for event in date_events.itertuples(index=False):
                report_quarter = pd.Timestamp(event.report_period).to_period("Q")
                values_by_quarter[report_quarter] = _finite_float(event.value)
            current_quarter = max(values_by_quarter)
            native_history = _quarterly_history_frame(
                values_by_quarter,
                current_quarter,
            )
            transformed_history = apply_operator(
                native_history,
                "quarterly",
                spec,
            )
            event_rows.append(
                {
                    "date": pd.Timestamp(event_date),
                    "asset_code": str(asset_code),
                    "value": transformed_history.iloc[-1, 0],
                }
            )

    event_values = pd.DataFrame.from_records(event_rows).pivot(
        index="date",
        columns="asset_code",
        values="value",
    )
    restored = _restore_to_calendar(event_values, trading_calendar)
    return restored.reindex(
        columns=pd.Index([str(code) for code in asset_codes], name="asset_code")
    )


def _quarterly_history_frame(
    values_by_quarter: Mapping[pd.Period, float],
    current_quarter: pd.Period,
) -> pd.DataFrame:
    first_quarter = min(values_by_quarter)
    quarters = pd.period_range(first_quarter, current_quarter, freq="Q")
    values = [values_by_quarter.get(quarter, np.nan) for quarter in quarters]
    return pd.DataFrame(
        {"value": values},
        index=quarters.to_timestamp(how="end").normalize(),
    )


def _rolling_latest_rank(
    factor_values: pd.DataFrame,
    window: int,
    minimum_periods: int,
) -> pd.DataFrame:
    values = factor_values.to_numpy(dtype="float64", na_value=np.nan)
    output = np.full_like(values, np.nan, dtype="float64")
    if values.size == 0:
        return pd.DataFrame(output, index=factor_values.index, columns=factor_values.columns)
    for column_position in range(values.shape[1]):
        column_values = values[:, column_position]
        padded_values = np.concatenate(
            [np.full(window - 1, np.nan), column_values]
        )
        windows = np.lib.stride_tricks.sliding_window_view(
            padded_values,
            window,
        )
        finite_mask = np.isfinite(windows)
        finite_counts = finite_mask.sum(axis=1)
        current_values = windows[:, -1][:, None]
        less_counts = (finite_mask & (windows < current_values)).sum(axis=1)
        equal_counts = (finite_mask & (windows == current_values)).sum(axis=1)
        average_ranks = less_counts + (equal_counts + 1.0) / 2.0
        valid_rows = (
            (finite_counts >= minimum_periods)
            & finite_mask[:, -1]
        )
        output[:, column_position] = np.where(
            valid_rows,
            average_ranks / finite_counts,
            np.nan,
        )
    return pd.DataFrame(
        output,
        index=factor_values.index,
        columns=factor_values.columns,
    )


def _rolling_slope(
    factor_values: pd.DataFrame,
    window: int,
    minimum_periods: int,
) -> pd.DataFrame:
    return _rolling_regression_statistic(
        factor_values,
        window,
        minimum_periods,
        normalize_by_mean=False,
    )


def _rolling_average_growth(
    factor_values: pd.DataFrame,
    window: int,
    minimum_periods: int,
) -> pd.DataFrame:
    return _rolling_regression_statistic(
        factor_values,
        window,
        minimum_periods,
        normalize_by_mean=True,
    )


def _rolling_regression_statistic(
    factor_values: pd.DataFrame,
    window: int,
    minimum_periods: int,
    normalize_by_mean: bool,
) -> pd.DataFrame:
    values = factor_values.to_numpy(dtype="float64", na_value=np.nan)
    output = np.full_like(values, np.nan, dtype="float64")
    x_values = np.arange(1, window + 1, dtype="float64")
    for column_position in range(values.shape[1]):
        column_values = values[:, column_position]
        padded_values = np.concatenate(
            [np.full(window - 1, np.nan), column_values]
        )
        windows = np.lib.stride_tricks.sliding_window_view(
            padded_values,
            window,
        )
        finite_mask = np.isfinite(windows)
        finite_counts = finite_mask.sum(axis=1).astype("float64")
        masked_x = np.where(finite_mask, x_values, 0.0)
        masked_y = np.where(finite_mask, windows, 0.0)
        mean_x = masked_x.sum(axis=1) / np.where(finite_counts > 0, finite_counts, np.nan)
        mean_y = masked_y.sum(axis=1) / np.where(finite_counts > 0, finite_counts, np.nan)
        centered_x = np.where(finite_mask, x_values - mean_x[:, None], 0.0)
        centered_y = np.where(finite_mask, windows - mean_y[:, None], 0.0)
        numerator = (centered_x * centered_y).sum(axis=1)
        denominator = np.square(centered_x).sum(axis=1)
        statistic = numerator / np.where(denominator > 0, denominator, np.nan)
        if normalize_by_mean:
            statistic = statistic / np.where(mean_y != 0, mean_y, np.nan)
        valid_rows = (finite_counts >= minimum_periods) & (denominator > 0)
        output[:, column_position] = np.where(valid_rows, statistic, np.nan)
    return pd.DataFrame(
        output,
        index=factor_values.index,
        columns=factor_values.columns,
    )


def _rolling_zscore(
    factor_values: pd.DataFrame,
    window: int,
    minimum_periods: int,
) -> pd.DataFrame:
    rolling_values = factor_values.rolling(window, min_periods=minimum_periods)
    rolling_mean = rolling_values.mean()
    rolling_standard_deviation = rolling_values.std()
    return (factor_values - rolling_mean) / rolling_standard_deviation.replace(
        0.0,
        np.nan,
    )


def _build_variant(
    base_name: str,
    target_frequency: str,
    spec: OperatorSpec,
    factor_values: pd.DataFrame,
) -> FactorVariant:
    factor_values.index = pd.DatetimeIndex(factor_values.index, name="date")
    factor_values.columns = pd.Index(
        factor_values.columns.astype(str),
        name="asset_code",
    )
    return FactorVariant(
        name=_variant_name(base_name, target_frequency, spec.operator_id),
        target_frequency=target_frequency,
        operator=spec,
        values=_finite_values(factor_values).astype("float32"),
    )


def _variant_name(
    base_name: str,
    frequency: str,
    operator_id: str,
) -> str:
    return f"{base_name}__{frequency}__{operator_id}"


def _finite_values(factor_values: pd.DataFrame) -> pd.DataFrame:
    return factor_values.replace([np.inf, -np.inf], np.nan)


def _finite_float(value: object) -> float:
    numeric_value = float(value) if pd.notna(value) else np.nan
    if np.isfinite(numeric_value):
        return numeric_value
    return np.nan


def _validate_frequency(frequency: str) -> None:
    if frequency not in SUPPORTED_FREQUENCIES:
        raise ValueError(f"未知因子频率: {frequency}")
