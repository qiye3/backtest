"""为景气因子测试生成不依赖正式数据的原始 CSV 目录。"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd


@dataclass(frozen=True)
class SyntheticGrowthMetadata:
    """保存断言 PIT 日期和单季期望值需要的 synthetic 元数据。"""

    trading_dates: pd.DatetimeIndex
    stock_codes: tuple[str, ...]
    income_records: pd.DataFrame
    quarterly_revenue: dict[tuple[str, pd.Period], float]


def make_growth_synthetic_data(output_root: Path) -> SyntheticGrowthMetadata:
    """生成行情、估值、财务、一致预期和评级的确定性原始记录。"""
    trading_dates = pd.bdate_range("2021-01-04", "2024-12-31")
    stock_codes = tuple(f"{stock_number:06d}.SZ" for stock_number in range(1, 9))
    _write_index_prices(output_root, trading_dates)
    _write_members(output_root, stock_codes)
    _write_industry_history(output_root, stock_codes)
    _write_stock_daily_data(output_root, trading_dates, stock_codes)
    income_records, quarterly_revenue = _write_financial_data(
        output_root,
        stock_codes,
    )
    _write_consensus_data(output_root, trading_dates, stock_codes)
    _write_rating_data(output_root, trading_dates, stock_codes)
    return SyntheticGrowthMetadata(
        trading_dates=trading_dates,
        stock_codes=stock_codes,
        income_records=income_records,
        quarterly_revenue=quarterly_revenue,
    )


def _write_index_prices(
    output_root: Path,
    trading_dates: pd.DatetimeIndex,
) -> None:
    """生成基准交易日历和指数收盘价。"""
    date_positions = np.arange(len(trading_dates), dtype="float64")
    index_records = pd.DataFrame(
        {
            "TRADE_DT": trading_dates.strftime("%Y%m%d"),
            "S_DQ_CLOSE": 1000.0 + date_positions * 0.5,
        }
    )
    _write_annual_records(
        index_records,
        output_root / "index" / "prices",
        "000906.SH",
        "TRADE_DT",
    )


def _write_members(output_root: Path, stock_codes: tuple[str, ...]) -> None:
    """把股票平均放入中证800和中证1000 synthetic 股票池。"""
    members_directory = output_root / "index" / "members"
    members_directory.mkdir(parents=True, exist_ok=True)
    members_by_index = {
        "000906.SH": stock_codes[:4],
        "000852.SH": stock_codes[4:],
    }
    for index_code, member_codes in members_by_index.items():
        member_records = pd.DataFrame(
            {
                "s_con_windcode": member_codes,
                "s_con_indate": "20210104",
                "s_con_outdate": pd.NA,
            }
        )
        member_records.to_csv(
            members_directory / f"{index_code}.csv",
            index=False,
        )


def _write_industry_history(output_root: Path, stock_codes: tuple[str, ...]) -> None:
    """生成两组 CITICS 历史行业，覆盖完整 synthetic 区间。"""
    industry_directory = output_root / "stock" / "industry"
    industry_directory.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(
        {
            "stock_code": stock_codes,
            "begin_date": "20210101",
            "end_date": pd.NA,
            "industry_class_code": "CITICS",
            "ind_class_code": [f"CI{position % 2 + 1}" for position in range(len(stock_codes))],
        }
    ).to_csv(industry_directory / "industry_history.csv", index=False)


def _write_stock_daily_data(
    output_root: Path,
    trading_dates: pd.DatetimeIndex,
    stock_codes: tuple[str, ...],
) -> None:
    """生成个股复权收盘价和用于中性化的总市值。"""
    date_positions = np.arange(len(trading_dates))[:, None]
    stock_positions = np.arange(len(stock_codes))[None, :]
    adjusted_close = 20.0 + date_positions * 0.02 + stock_positions * 1.5
    total_market_value = (
        100_000.0 + date_positions * 30.0 + np.square(stock_positions + 1) * 20_000.0
    )
    common_columns = {
        "TRADE_DT": np.repeat(trading_dates.strftime("%Y%m%d"), len(stock_codes)),
        "S_INFO_WINDCODE": np.tile(stock_codes, len(trading_dates)),
        "OPDATE": np.repeat(
            trading_dates.strftime("%Y-%m-%d 18:00:00"),
            len(stock_codes),
        ),
    }
    quote_records = pd.DataFrame(
        {
            **common_columns,
            "S_DQ_ADJCLOSE": adjusted_close.reshape(-1),
        }
    )
    valuation_records = pd.DataFrame(
        {
            **common_columns,
            "S_VAL_MV": total_market_value.reshape(-1),
        }
    )
    _write_annual_records(
        quote_records,
        output_root / "stock" / "daily_quote",
        "quote",
        "TRADE_DT",
    )
    _write_annual_records(
        valuation_records,
        output_root / "stock" / "daily_valuation",
        "valuation",
        "TRADE_DT",
    )


def _write_financial_data(
    output_root: Path,
    stock_codes: tuple[str, ...],
) -> tuple[pd.DataFrame, dict[tuple[str, pd.Period], float]]:
    """生成错峰公告的累计利润表和单季度财务指标。"""
    report_quarters = pd.period_range("2021Q1", "2024Q3", freq="Q")
    income_rows: list[dict] = []
    indicator_rows: list[dict] = []
    quarterly_revenue: dict[tuple[str, pd.Period], float] = {}

    for stock_position, stock_code in enumerate(stock_codes):
        cumulative_revenue = 0.0
        cumulative_profit = 0.0
        current_year = None
        for quarter_position, report_quarter in enumerate(report_quarters):
            if current_year != report_quarter.year:
                current_year = report_quarter.year
                cumulative_revenue = 0.0
                cumulative_profit = 0.0
            single_revenue = (
                100.0
                + stock_position * 12.0
                + quarter_position * 7.0
                + quarter_position**2 * 0.4
                + report_quarter.quarter**2
            )
            single_profit = (
                12.0
                + stock_position * 2.0
                + quarter_position * 1.7
                + quarter_position**2 * 0.15
                + report_quarter.quarter * 0.8
            )
            cumulative_revenue += single_revenue
            cumulative_profit += single_profit
            quarterly_revenue[(stock_code, report_quarter)] = single_revenue

            announcement_date = report_quarter.end_time.normalize() + pd.Timedelta(days=20)
            actual_announcement_date = announcement_date + pd.Timedelta(
                days=7 + stock_position,
            )
            operation_time = actual_announcement_date + pd.Timedelta(hours=18)
            common_values = {
                "S_INFO_WINDCODE": stock_code,
                "ANN_DT": announcement_date.strftime("%Y%m%d"),
                "REPORT_PERIOD": report_quarter.end_time.strftime("%Y%m%d"),
                "OPDATE": operation_time.strftime("%Y-%m-%d %H:%M:%S"),
            }
            income_rows.append(
                {
                    **common_values,
                    "ACTUAL_ANN_DT": actual_announcement_date.strftime("%Y%m%d"),
                    "TOT_OPER_REV": cumulative_revenue,
                    "NET_PROFIT_EXCL_MIN_INT_INC": cumulative_profit,
                }
            )
            indicator_rows.append(
                {
                    **common_values,
                    "ANN_DT": actual_announcement_date.strftime("%Y%m%d"),
                    "S_QFA_ROE": 5.0 + stock_position * 0.4 + quarter_position * 0.25,
                }
            )

    income_records = pd.DataFrame(income_rows)
    indicator_records = pd.DataFrame(indicator_rows)
    _write_annual_records(
        income_records,
        output_root / "stock" / "financial" / "income",
        "income",
        "ACTUAL_ANN_DT",
    )
    _write_annual_records(
        indicator_records,
        output_root / "stock" / "financial" / "indicators",
        "indicators",
        "ANN_DT",
    )
    return income_records, quarterly_revenue


def _write_consensus_data(
    output_root: Path,
    trading_dates: pd.DatetimeIndex,
    stock_codes: tuple[str, ...],
) -> None:
    """生成当年朝阳永续和 Wind 一致预期日频记录。"""
    date_positions = np.arange(len(trading_dates), dtype="float64")
    stock_positions = np.arange(len(stock_codes), dtype="float64")
    repeated_dates = np.repeat(trading_dates, len(stock_codes))
    repeated_date_positions = np.repeat(date_positions, len(stock_codes))
    repeated_stock_positions = np.tile(stock_positions, len(trading_dates))
    tiled_stock_codes = np.tile(stock_codes, len(trading_dates))

    suntime_records = pd.DataFrame(
        {
            "stock_code": tiled_stock_codes,
            "con_date": repeated_dates.strftime("%Y%m%d"),
            "con_year": repeated_dates.year,
            "con_eps": 1.0 + repeated_stock_positions * 0.1 + repeated_date_positions * 0.001,
            "con_np": 80.0 + repeated_stock_positions * 8.0 + repeated_date_positions * 0.03,
            "con_npgrate_13w": (
                repeated_stock_positions * 0.2 + np.sin(repeated_date_positions / 30.0)
            ),
        }
    )
    wind_records = pd.DataFrame(
        {
            "stock_code": tiled_stock_codes,
            "con_date": repeated_dates.strftime("%Y%m%d"),
            "est_report_dt": repeated_dates.strftime("%Y1231"),
            "prediction_number": 5.0 + repeated_stock_positions + repeated_date_positions % 11,
        }
    )
    _write_annual_records(
        suntime_records,
        output_root / "stock" / "consensus" / "suntime",
        "suntime",
        "con_date",
    )
    _write_annual_records(
        wind_records,
        output_root / "stock" / "consensus" / "wind",
        "wind",
        "con_date",
    )


def _write_rating_data(
    output_root: Path,
    trading_dates: pd.DatetimeIndex,
    stock_codes: tuple[str, ...],
) -> None:
    """生成90日评级事件及不会通过周期筛选的干扰记录。"""
    rating_rows: list[dict] = []
    for date_position, rating_date in enumerate(trading_dates[::20]):
        for stock_position, stock_code in enumerate(stock_codes):
            base_row = {
                "RATING_DT": rating_date.strftime("%Y%m%d"),
                "S_INFO_WINDCODE": stock_code,
                "S_WRATING_UPGRADE": 2.0 + (date_position + stock_position) % 4,
                "S_WRATING_DOWNGRADE": 1.0 + stock_position % 2,
                "S_WRATING_MAINTAIN": 3.0 + date_position % 3,
                "OPDATE": (rating_date + pd.Timedelta(hours=18)).strftime("%Y-%m-%d %H:%M:%S"),
            }
            rating_rows.append(
                {
                    **base_row,
                    "S_WRATING_CYCLE": 263001000,
                }
            )
            rating_rows.append(
                {
                    **base_row,
                    "S_WRATING_CYCLE": 263002000,
                    "S_WRATING_UPGRADE": 999.0,
                }
            )
    rating_records = pd.DataFrame(rating_rows)
    _write_annual_records(
        rating_records,
        output_root / "stock" / "ratings",
        "ratings",
        "RATING_DT",
    )


def _write_annual_records(
    records: pd.DataFrame,
    output_directory: Path,
    file_prefix: str,
    date_column: str,
) -> None:
    """按日期字段年份写出框架约定的年度 CSV。"""
    output_directory.mkdir(parents=True, exist_ok=True)
    record_years = pd.to_datetime(
        records[date_column].astype("string"),
        format="%Y%m%d",
    ).dt.year
    for record_year, annual_records in records.groupby(record_years):
        annual_records.to_csv(
            output_directory / f"{file_prefix}_{record_year}.csv",
            index=False,
        )
