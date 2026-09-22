"""为价值因子测试生成不依赖正式数据的 synthetic 原始目录。"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from tests.growth_synthetic_data import SyntheticGrowthMetadata
from tests.quality_synthetic_data import make_quality_synthetic_data


def make_value_synthetic_data(output_root: Path) -> SyntheticGrowthMetadata:
    """生成价值因子所需的估值、行情、财务指标和一致预期。"""
    metadata = make_quality_synthetic_data(output_root)
    _extend_daily_valuation(output_root)
    _extend_financial_income(output_root)
    _extend_financial_indicators(output_root)
    _extend_consensus(output_root)
    return metadata


def _extend_daily_valuation(output_root: Path) -> None:
    """补充传统估值倍数、股息字段和 TTM 经营现金流。"""
    valuation_directory = output_root / "stock" / "daily_valuation"
    for valuation_path in sorted(valuation_directory.glob("valuation_*.csv")):
        records = pd.read_csv(valuation_path)
        stock_position = records["S_INFO_WINDCODE"].str[:6].astype(int) - 1
        trade_dates = pd.to_datetime(
            records["TRADE_DT"].astype("string"),
            format="%Y%m%d",
        )
        day_of_year = trade_dates.dt.dayofyear.astype("float64")
        valuation_cycle = np.sin(day_of_year / 45.0)
        records = records.assign(
            S_VAL_PE_TTM=9.0 + stock_position * 1.2 + valuation_cycle,
            S_VAL_PE=10.0 + stock_position * 1.3 + valuation_cycle * 0.8,
            S_VAL_PS_TTM=1.2 + stock_position * 0.12 + valuation_cycle * 0.05,
            S_VAL_PCF_OCFTTM=7.0 + stock_position * 0.7 + valuation_cycle * 0.4,
            S_PRICE_DIV_DPS=22.0 + stock_position * 2.0 - valuation_cycle,
            NET_CASH_FLOWS_OPER_ACT_TTM=(
                90_000_000.0 + stock_position * 8_000_000.0 + day_of_year * 20_000.0
            ),
        )
        records.to_csv(valuation_path, index=False)


def _extend_financial_income(output_root: Path) -> None:
    """补充低估值期权因子使用的研发费用。"""
    income_directory = output_root / "stock" / "financial" / "income"
    for income_path in sorted(income_directory.glob("income_*.csv")):
        records = pd.read_csv(income_path)
        stock_position = records["S_INFO_WINDCODE"].str[:6].astype(int) - 1
        records["RD_EXPENSE"] = records["TOT_OPER_REV"] * (0.02 + stock_position * 0.006)
        records.to_csv(income_path, index=False)


def _extend_financial_indicators(output_root: Path) -> None:
    """补充 EV、价值质量和价值陷阱公式所需指标。"""
    indicator_directory = output_root / "stock" / "financial" / "indicators"
    for indicator_path in sorted(indicator_directory.glob("indicators_*.csv")):
        records = pd.read_csv(indicator_path)
        stock_position = records["S_INFO_WINDCODE"].str[:6].astype(int) - 1
        report_dates = pd.to_datetime(
            records["REPORT_PERIOD"].astype("string"),
            format="%Y%m%d",
        )
        time_position = (report_dates.dt.year - 2021) * 4 + report_dates.dt.quarter - 1
        records = records.assign(
            S_FA_EBIT=75_000_000.0 + stock_position * 7_000_000.0 + time_position * 1_500_000.0,
            S_FA_EBITDA=(92_000_000.0 + stock_position * 8_000_000.0 + time_position * 1_800_000.0),
            S_FA_FCFF=(48_000_000.0 + stock_position * 5_000_000.0 + time_position * 1_200_000.0),
            S_FA_NETDEBT=(35_000_000.0 + stock_position * 4_000_000.0 - time_position * 500_000.0),
            S_FA_YOYROE=-2.0 + stock_position * 0.5 + time_position * 0.2,
        )
        records.to_csv(indicator_path, index=False)


def _extend_consensus(output_root: Path) -> None:
    """补充一致预期 PE、PB、PS 和 PEG。"""
    consensus_directory = output_root / "stock" / "consensus" / "suntime"
    for consensus_path in sorted(consensus_directory.glob("suntime_*.csv")):
        records = pd.read_csv(consensus_path)
        stock_position = records["stock_code"].str[:6].astype(int) - 1
        consensus_dates = pd.to_datetime(
            records["con_date"].astype("string"),
            format="%Y%m%d",
        )
        day_of_year = consensus_dates.dt.dayofyear.astype("float64")
        records = records.assign(
            con_pe=11.0 + stock_position * 1.1 - day_of_year * 0.002,
            con_pb=1.4 + stock_position * 0.12 - day_of_year * 0.0002,
            con_ps=1.8 + stock_position * 0.15 - day_of_year * 0.0003,
            con_peg=0.9 + stock_position * 0.08 + day_of_year * 0.0002,
        )
        records.to_csv(consensus_path, index=False)
