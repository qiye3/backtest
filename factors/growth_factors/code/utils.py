"""景气成长因子共享的季度转换、时间序列算子和后处理函数。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

import numpy as np
import pandas as pd

FactorFrequency = Literal["daily", "quarterly"]


@dataclass(frozen=True)
class BaseFactorPanel:
    """保存基础因子值、原生频率及季频因子的报告期状态。"""

    values: pd.DataFrame
    frequency: FactorFrequency
    report_periods: pd.DataFrame | None = None


def state_event_positions(
    factor_values: pd.Series,
    report_periods: pd.Series,
) -> np.ndarray:
    """找出单只股票报告期或因子状态实际发生变化的位置。"""
    previous_values = factor_values.shift()
    values_unchanged = factor_values.eq(previous_values)
    values_unchanged |= factor_values.isna() & previous_values.isna()

    previous_periods = report_periods.shift()
    periods_unchanged = report_periods.eq(previous_periods)
    periods_unchanged |= report_periods.isna() & previous_periods.isna()
    event_mask = report_periods.notna() & ~(values_unchanged & periods_unchanged)
    return np.flatnonzero(event_mask.to_numpy())


def materialize_event_values(
    event_positions: np.ndarray,
    event_values: list[float],
    row_count: int,
) -> np.ndarray:
    """把稀疏 PIT 事件展开为日频状态，并保留显式缺失状态。"""
    daily_values = np.full(row_count, np.nan, dtype="float64")
    for event_index, first_position in enumerate(event_positions):
        if event_index + 1 < len(event_positions):
            last_position = event_positions[event_index + 1]
        else:
            last_position = row_count
        daily_values[first_position:last_position] = event_values[event_index]
    return daily_values


def report_quarter_at(report_periods: pd.Series, position: int) -> pd.Period:
    """把指定位置的报告期转换为自然季度。"""
    return pd.Timestamp(report_periods.iloc[position]).to_period("Q")


def finite_value(value: object) -> float:
    """把有效数值转换为浮点数，其余状态统一记为缺失。"""
    numeric_value = float(value) if pd.notna(value) else np.nan
    if np.isfinite(numeric_value):
        return numeric_value
    return np.nan


def standardize_against_prior_history(
    current_value: float,
    prior_values: list[float],
) -> float:
    """使用至少两条历史观测的样本均值和样本标准差标准化当前值。"""
    valid_history = np.asarray(prior_values, dtype="float64")
    valid_history = valid_history[np.isfinite(valid_history)]
    if not np.isfinite(current_value) or len(valid_history) < 2:
        return np.nan
    history_standard_deviation = valid_history.std(ddof=1)
    if not np.isfinite(history_standard_deviation) or history_standard_deviation <= 0:
        return np.nan
    return float((current_value - valid_history.mean()) / history_standard_deviation)


def build_single_quarter_values(
    cumulative_values: pd.DataFrame,
    report_periods: pd.DataFrame,
) -> pd.DataFrame:
    """按股票公告状态把累计利润表字段还原为单季度值。"""
    quarterly_panel = pd.DataFrame(
        np.nan,
        index=cumulative_values.index,
        columns=cumulative_values.columns,
        dtype="float64",
    )
    for stock_code in cumulative_values.columns:
        stock_values = cumulative_values[stock_code]
        stock_periods = report_periods[stock_code]
        event_positions = state_event_positions(stock_values, stock_periods)
        cumulative_by_quarter: dict[pd.Period, float] = {}
        event_quarter_values: list[float] = []

        for event_position in event_positions:
            report_quarter = report_quarter_at(stock_periods, event_position)
            cumulative_value = finite_value(stock_values.iloc[event_position])
            cumulative_by_quarter[report_quarter] = cumulative_value
            if report_quarter.quarter == 1:
                quarter_value = cumulative_value
            else:
                previous_cumulative = cumulative_by_quarter.get(
                    report_quarter - 1,
                    np.nan,
                )
                if np.isfinite(cumulative_value) and np.isfinite(previous_cumulative):
                    quarter_value = cumulative_value - previous_cumulative
                else:
                    quarter_value = np.nan
            event_quarter_values.append(quarter_value)

        quarterly_panel[stock_code] = materialize_event_values(
            event_positions,
            event_quarter_values,
            len(quarterly_panel),
        )
    return quarterly_panel


def build_seasonal_surprise(
    quarterly_values: pd.DataFrame,
    report_periods: pd.DataFrame,
) -> pd.DataFrame:
    """计算单季值同比差分相对公告前历史差分的标准化偏离。"""
    surprise_panel = pd.DataFrame(
        np.nan,
        index=quarterly_values.index,
        columns=quarterly_values.columns,
        dtype="float64",
    )
    for stock_code in quarterly_values.columns:
        stock_values = quarterly_values[stock_code]
        stock_periods = report_periods[stock_code]
        event_positions = state_event_positions(stock_values, stock_periods)
        values_by_quarter: dict[pd.Period, float] = {}
        differences_by_quarter: dict[pd.Period, float] = {}
        event_surprises: list[float] = []

        for event_position in event_positions:
            report_quarter = report_quarter_at(stock_periods, event_position)
            current_value = finite_value(stock_values.iloc[event_position])
            values_by_quarter[report_quarter] = current_value
            prior_year_value = values_by_quarter.get(report_quarter - 4, np.nan)
            if np.isfinite(current_value) and np.isfinite(prior_year_value):
                seasonal_difference = current_value - prior_year_value
            else:
                seasonal_difference = np.nan
            differences_by_quarter[report_quarter] = seasonal_difference
            prior_differences = [
                difference
                for quarter, difference in differences_by_quarter.items()
                if quarter < report_quarter
            ]
            event_surprises.append(
                standardize_against_prior_history(
                    seasonal_difference,
                    prior_differences,
                )
            )

        surprise_panel[stock_code] = materialize_event_values(
            event_positions,
            event_surprises,
            len(surprise_panel),
        )
    return surprise_panel


def build_consensus_profit_surprise(
    quarterly_profit: pd.DataFrame,
    report_periods: pd.DataFrame,
    consensus_net_profit: pd.DataFrame,
) -> pd.DataFrame:
    """在实际利润公告日匹配最新一致预期并构造历史标准化 surprise。"""
    surprise_panel = pd.DataFrame(
        np.nan,
        index=quarterly_profit.index,
        columns=quarterly_profit.columns,
        dtype="float64",
    )
    for stock_code in quarterly_profit.columns:
        stock_profit = quarterly_profit[stock_code]
        stock_periods = report_periods[stock_code]
        stock_consensus = consensus_net_profit[stock_code]
        event_positions = state_event_positions(stock_profit, stock_periods)
        surprises_by_quarter: dict[pd.Period, float] = {}
        event_standardized_values: list[float] = []

        for event_position in event_positions:
            report_quarter = report_quarter_at(stock_periods, event_position)
            actual_profit = finite_value(stock_profit.iloc[event_position])
            annual_consensus = finite_value(stock_consensus.iloc[event_position])
            if np.isfinite(actual_profit) and np.isfinite(annual_consensus):
                current_surprise = actual_profit - annual_consensus / 4.0
            else:
                current_surprise = np.nan
            surprises_by_quarter[report_quarter] = current_surprise
            prior_surprises = [
                surprise
                for quarter, surprise in surprises_by_quarter.items()
                if quarter < report_quarter
            ]
            event_standardized_values.append(
                standardize_against_prior_history(
                    current_surprise,
                    prior_surprises,
                )
            )

        surprise_panel[stock_code] = materialize_event_values(
            event_positions,
            event_standardized_values,
            len(surprise_panel),
        )
    return surprise_panel


def apply_daily_operator(
    factor_values: pd.DataFrame,
    operator_name: str,
) -> pd.DataFrame:
    """对日频基础因子应用构造表定义的核心时间序列算子。"""
    if operator_name == "raw":
        return factor_values.copy()
    if operator_name == "qtile_M12":
        return rolling_percentile_rank(factor_values, window=240, min_periods=120)
    if operator_name == "qtile_M24":
        return rolling_percentile_rank(factor_values, window=480, min_periods=240)
    if operator_name == "zscore_K12":
        return rolling_zscore(factor_values, window=240, min_periods=120)
    if operator_name == "zscore_K24":
        return rolling_zscore(factor_values, window=480, min_periods=240)
    if operator_name == "chg_K1":
        return factor_values - factor_values.shift(20)
    if operator_name == "qtilechg_K24_K1":
        percentile_values = rolling_percentile_rank(
            factor_values,
            window=480,
            min_periods=240,
        )
        return percentile_values - percentile_values.shift(20)
    if operator_name == "zchg_K24_K1":
        standardized_values = rolling_zscore(
            factor_values,
            window=480,
            min_periods=240,
        )
        return standardized_values - standardized_values.shift(20)
    raise ValueError(f"未知日频景气算子: {operator_name}")


def rolling_percentile_rank(
    factor_values: pd.DataFrame,
    window: int,
    min_periods: int,
) -> pd.DataFrame:
    """计算当前值在逐股票滚动窗口中的百分位排名。"""
    return factor_values.rolling(
        window=window,
        min_periods=min_periods,
    ).rank(pct=True)


def rolling_zscore(
    factor_values: pd.DataFrame,
    window: int,
    min_periods: int,
) -> pd.DataFrame:
    """使用包含当前观测的滚动样本均值和样本标准差计算 Z-score。"""
    rolling_values = factor_values.rolling(
        window=window,
        min_periods=min_periods,
    )
    rolling_mean = rolling_values.mean()
    rolling_standard_deviation = rolling_values.std(ddof=1)
    return (factor_values - rolling_mean) / rolling_standard_deviation.replace(
        0.0,
        np.nan,
    )


def apply_quarterly_operator(
    factor_values: pd.DataFrame,
    report_periods: pd.DataFrame,
    operator_name: str,
) -> pd.DataFrame:
    """按每只股票自己的报告季度历史应用季频算子。"""
    if operator_name == "raw":
        return factor_values.copy()

    transformed_panel = pd.DataFrame(
        np.nan,
        index=factor_values.index,
        columns=factor_values.columns,
        dtype="float64",
    )
    for stock_code in factor_values.columns:
        stock_values = factor_values[stock_code]
        stock_periods = report_periods[stock_code]
        event_positions = state_event_positions(stock_values, stock_periods)
        values_by_quarter: dict[pd.Period, float] = {}
        event_transformed_values: list[float] = []

        for event_position in event_positions:
            report_quarter = report_quarter_at(stock_periods, event_position)
            current_value = finite_value(stock_values.iloc[event_position])
            values_by_quarter[report_quarter] = current_value
            transformed_value = calculate_quarterly_operator_value(
                values_by_quarter,
                report_quarter,
                current_value,
                operator_name,
            )
            event_transformed_values.append(transformed_value)

        transformed_panel[stock_code] = materialize_event_values(
            event_positions,
            event_transformed_values,
            len(transformed_panel),
        )
    return transformed_panel


def calculate_quarterly_operator_value(
    values_by_quarter: dict[pd.Period, float],
    report_quarter: pd.Period,
    current_value: float,
    operator_name: str,
) -> float:
    """计算一个报告事件对应的 qoq、yoy 或八季分位值。"""
    if operator_name == "qoq":
        prior_value = values_by_quarter.get(report_quarter - 1, np.nan)
        if np.isfinite(current_value) and np.isfinite(prior_value):
            return current_value - prior_value
        return np.nan
    if operator_name == "yoy":
        prior_value = values_by_quarter.get(report_quarter - 4, np.nan)
        if np.isfinite(current_value) and np.isfinite(prior_value):
            return current_value - prior_value
        return np.nan
    if operator_name == "qtile8":
        quarter_window = [report_quarter - offset for offset in range(7, -1, -1)]
        window_values = np.asarray(
            [values_by_quarter.get(quarter, np.nan) for quarter in quarter_window],
            dtype="float64",
        )
        if not np.isfinite(window_values).all():
            return np.nan
        values_below_current = np.count_nonzero(window_values < current_value)
        values_equal_current = np.count_nonzero(window_values == current_value)
        average_rank = values_below_current + (values_equal_current + 1) / 2.0
        return float(average_rank / len(window_values))
    raise ValueError(f"未知季频景气算子: {operator_name}")
