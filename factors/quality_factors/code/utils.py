"""质量因子的 PIT 季度算子和安全数值运算。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

import numpy as np
import pandas as pd

from factors.fundamental_utils import safe_divide as _safe_divide
from factors.quarterly_history import apply_quarterly_event_operator

QualityFrequency = Literal["daily", "quarterly"]
safe_divide = _safe_divide


@dataclass(frozen=True)
class QualityBasePanel:
    """保存基础值、频率和季频报告期状态。"""

    values: pd.DataFrame
    frequency: QualityFrequency
    report_periods: pd.DataFrame | None = None
    quarterly_events: pd.DataFrame | None = None


def aligned_financial_ratio(
    numerator: pd.DataFrame,
    numerator_periods: pd.DataFrame,
    denominator: pd.DataFrame,
    denominator_periods: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """只使用报告期一致且在当日都已公告的跨表数据。"""
    aligned_periods = numerator_periods.where(numerator_periods.eq(denominator_periods))
    ratio = safe_divide(numerator, denominator).where(aligned_periods.notna())
    return ratio, aligned_periods


def apply_quality_operator(
    base_panel: QualityBasePanel,
    operator_name: str,
) -> pd.DataFrame:
    """按基础因子频率执行质量因子变体算子。"""
    if operator_name == "raw":
        return base_panel.values.copy()
    if base_panel.frequency == "daily":
        if operator_name == "chg65":
            return base_panel.values - base_panel.values.shift(65)
        raise ValueError(f"未知日频质量算子: {operator_name}")
    if base_panel.report_periods is None:
        raise ValueError("季频质量因子缺少 REPORT_PERIOD")
    return apply_quarterly_operator(
        base_panel.values,
        base_panel.report_periods,
        operator_name,
        base_panel.quarterly_events,
    )


def apply_quarterly_operator(
    factor_values: pd.DataFrame,
    report_periods: pd.DataFrame,
    operator_name: str,
    quarterly_events: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """依据每只股票自己的公告历史计算季频变化和稳定性。"""
    if quarterly_events is not None:
        return apply_quarterly_event_operator(
            quarterly_events=quarterly_events,
            calendar=factor_values.index,
            asset_codes=factor_values.columns,
            calculator=lambda values_by_quarter, report_quarter, current_value: (
                _calculate_operator_value(
                    values_by_quarter,
                    report_quarter,
                    current_value,
                    operator_name,
                )
            ),
        )
    transformed = pd.DataFrame(
        np.nan,
        index=factor_values.index,
        columns=factor_values.columns,
        dtype="float64",
    )
    for stock_code in factor_values.columns:
        transformed[stock_code] = _transform_stock_events(
            factor_values[stock_code],
            report_periods[stock_code],
            operator_name,
        )
    return transformed


def _transform_stock_events(
    stock_values: pd.Series,
    stock_periods: pd.Series,
    operator_name: str,
) -> np.ndarray:
    """计算单只股票的稀疏报告事件并展开为日频状态。"""
    event_positions = _state_event_positions(stock_values, stock_periods)
    values_by_quarter: dict[pd.Period, float] = {}
    event_values: list[float] = []
    for event_position in event_positions:
        report_quarter = pd.Timestamp(stock_periods.iloc[event_position]).to_period("Q")
        current_value = _finite_value(stock_values.iloc[event_position])
        values_by_quarter[report_quarter] = current_value
        event_values.append(
            _calculate_operator_value(
                values_by_quarter,
                report_quarter,
                current_value,
                operator_name,
            )
        )
    return _materialize_events(event_positions, event_values, len(stock_values))


def _calculate_operator_value(
    values_by_quarter: dict[pd.Period, float],
    report_quarter: pd.Period,
    current_value: float,
    operator_name: str,
) -> float:
    """计算一个公告事件对应的指定季度算子。"""
    if operator_name in {"qoq", "yoy"}:
        offset = 1 if operator_name == "qoq" else 4
        prior_value = values_by_quarter.get(report_quarter - offset, np.nan)
        if np.isfinite(current_value) and np.isfinite(prior_value):
            return float(current_value - prior_value)
        return np.nan
    window_by_operator = {
        "std8": (8, "std"),
        "std12": (12, "std"),
        "std20": (20, "std"),
        "cv12": (12, "cv"),
        "mean12": (12, "mean"),
    }
    if operator_name in window_by_operator:
        window, statistic = window_by_operator[operator_name]
        window_values = _quarter_window(values_by_quarter, report_quarter, window)
        if window_values is None:
            return np.nan
        if statistic == "std":
            return float(window_values.std(ddof=1))
        if statistic == "mean":
            return float(window_values.mean())
        mean_absolute_value = abs(float(window_values.mean()))
        if mean_absolute_value <= 1e-12:
            return np.nan
        return float(window_values.std(ddof=1) / mean_absolute_value)
    if operator_name == "turning_positive":
        prior_value = values_by_quarter.get(report_quarter - 1, np.nan)
        if not np.isfinite(current_value) or not np.isfinite(prior_value):
            return np.nan
        return float(current_value > 0 and prior_value <= 0)
    raise ValueError(f"未知季频质量算子: {operator_name}")


def _quarter_window(
    values_by_quarter: dict[pd.Period, float],
    report_quarter: pd.Period,
    window: int,
) -> np.ndarray | None:
    """取得连续且完整的自然季度窗口。"""
    values = np.asarray(
        [
            values_by_quarter.get(report_quarter - offset, np.nan)
            for offset in range(window - 1, -1, -1)
        ],
        dtype="float64",
    )
    if not np.isfinite(values).all():
        return None
    return values


def _state_event_positions(
    factor_values: pd.Series,
    report_periods: pd.Series,
) -> np.ndarray:
    """找出报告期或数值状态发生变化的位置。"""
    previous_values = factor_values.shift()
    values_unchanged = factor_values.eq(previous_values)
    values_unchanged |= factor_values.isna() & previous_values.isna()
    previous_periods = report_periods.shift()
    periods_unchanged = report_periods.eq(previous_periods)
    periods_unchanged |= report_periods.isna() & previous_periods.isna()
    event_mask = report_periods.notna() & ~(values_unchanged & periods_unchanged)
    return np.flatnonzero(event_mask.to_numpy())


def _materialize_events(
    event_positions: np.ndarray,
    event_values: list[float],
    row_count: int,
) -> np.ndarray:
    """把稀疏事件值延续到下一报告事件。"""
    daily_values = np.full(row_count, np.nan, dtype="float64")
    for event_index, first_position in enumerate(event_positions):
        if event_index + 1 < len(event_positions):
            last_position = event_positions[event_index + 1]
        else:
            last_position = row_count
        daily_values[first_position:last_position] = event_values[event_index]
    return daily_values


def _finite_value(value: object) -> float:
    """把有限数值转为 float，其余统一记为缺失。"""
    numeric_value = float(value) if pd.notna(value) else np.nan
    if np.isfinite(numeric_value):
        return numeric_value
    return np.nan
