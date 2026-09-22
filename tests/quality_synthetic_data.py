"""为质量因子测试扩展一套不依赖正式数据的 synthetic 原始目录。"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from tests.growth_synthetic_data import (
    SyntheticGrowthMetadata,
    make_growth_synthetic_data,
)


def make_quality_synthetic_data(output_root: Path) -> SyntheticGrowthMetadata:
    """生成质量因子所需的行情、三张财务报表、指标和一致预期。"""
    metadata = make_growth_synthetic_data(output_root)
    _extend_valuation(output_root)
    _extend_financial_indicators(output_root)
    _write_balance_sheets(output_root, metadata.income_records)
    _write_cashflows(output_root, metadata.income_records)
    _extend_consensus(output_root)
    return metadata


def _extend_valuation(output_root: Path) -> None:
    """为日频估值补充 PB。"""
    valuation_directory = output_root / "stock" / "daily_valuation"
    for valuation_path in sorted(valuation_directory.glob("valuation_*.csv")):
        records = pd.read_csv(valuation_path)
        stock_number = records["S_INFO_WINDCODE"].str[:6].astype(int)
        records["S_VAL_PB_NEW"] = 0.8 + stock_number * 0.15
        records.to_csv(valuation_path, index=False)


def _extend_financial_indicators(output_root: Path) -> None:
    """为原有单季 ROE 记录补充质量表使用的财务指标。"""
    indicator_directory = output_root / "stock" / "financial" / "indicators"
    for indicator_path in sorted(indicator_directory.glob("indicators_*.csv")):
        records = pd.read_csv(indicator_path)
        stock_position = records["S_INFO_WINDCODE"].str[:6].astype(int) - 1
        report_quarter = pd.to_datetime(
            records["REPORT_PERIOD"].astype("string"),
            format="%Y%m%d",
        ).dt.quarter
        report_year = pd.to_datetime(
            records["REPORT_PERIOD"].astype("string"),
            format="%Y%m%d",
        ).dt.year
        time_position = (report_year - 2021) * 4 + report_quarter - 1
        base_profitability = stock_position * 0.35 + time_position * 0.12
        records = records.assign(
            S_FA_ROE=8.0 + base_profitability,
            S_FA_ROE_DEDUCTED=7.2 + base_profitability * 0.9,
            S_FA_ROIC=6.5 + base_profitability * 0.8,
            S_FA_ROA=4.0 + base_profitability * 0.55,
            S_FA_GROSSPROFITMARGIN=25.0 + base_profitability,
            S_FA_NETPROFITMARGIN=9.0 + base_profitability * 0.6,
            S_FA_OPTOGR=11.0 + base_profitability * 0.7,
            S_FA_OCFTOOR=0.12 + base_profitability * 0.005,
            S_FA_OCFTOPROFIT=0.9 + base_profitability * 0.02,
            S_FA_DEDUCTEDPROFITTOPROFIT=0.82 + base_profitability * 0.004,
            S_FA_SALESCASHINTOOR=0.95 + base_profitability * 0.003,
            S_FA_DEBTTOASSETS=55.0 - base_profitability * 0.4,
            S_FA_ASSETSTOEQUITY=2.1 - base_profitability * 0.01,
            S_FA_ASSETSTURN=0.7 + base_profitability * 0.01,
            S_FA_TANGIBLEASSETSTOASSETS=0.6 + stock_position * 0.01,
            S_FA_CURRENT=1.3 + stock_position * 0.04,
            S_FA_QUICK=1.0 + stock_position * 0.03,
            S_FA_FCFF=(time_position - 5) * 8.0 + stock_position * 3.0,
            S_FA_NETDEBT=60.0 + stock_position * 8.0,
        )
        records.to_csv(indicator_path, index=False)


def _write_balance_sheets(output_root: Path, income_records: pd.DataFrame) -> None:
    """按利润表公告键生成资产负债表字段。"""
    records = income_records[
        [
            "S_INFO_WINDCODE",
            "ANN_DT",
            "ACTUAL_ANN_DT",
            "REPORT_PERIOD",
            "OPDATE",
        ]
    ].copy()
    stock_position = records["S_INFO_WINDCODE"].str[:6].astype(int) - 1
    report_dates = pd.to_datetime(records["REPORT_PERIOD"].astype("string"), format="%Y%m%d")
    time_position = (report_dates.dt.year - 2021) * 4 + report_dates.dt.quarter - 1
    records = records.assign(
        ACCOUNTS_RECEIVABLE=35.0 + stock_position * 3.0 + time_position * 1.2,
        GOODWILL=8.0 + stock_position * 2.0,
        INVENTORIES=45.0 + stock_position * 4.0 + time_position * 2.5,
        TOT_ASSETS=500.0 + stock_position * 45.0 + time_position * 15.0,
        TOT_SHRHLDR_EQY_EXCL_MIN_INT=220.0 + stock_position * 20.0 + time_position * 7.0,
    )
    _write_by_year(
        records,
        output_root / "stock" / "financial" / "balance_sheet",
        "balance_sheet",
    )


def _write_cashflows(output_root: Path, income_records: pd.DataFrame) -> None:
    """按利润表公告键生成经营现金流与资本开支。"""
    records = income_records[
        [
            "S_INFO_WINDCODE",
            "ANN_DT",
            "ACTUAL_ANN_DT",
            "REPORT_PERIOD",
            "OPDATE",
            "NET_PROFIT_EXCL_MIN_INT_INC",
        ]
    ].copy()
    stock_position = records["S_INFO_WINDCODE"].str[:6].astype(int) - 1
    records["NET_CASH_FLOWS_OPER_ACT"] = (
        records["NET_PROFIT_EXCL_MIN_INT_INC"] * 1.15 + stock_position
    )
    records["CASH_PAY_ACQ_CONST_FIOLTA"] = records["NET_CASH_FLOWS_OPER_ACT"] * 0.35
    _write_by_year(
        records,
        output_root / "stock" / "financial" / "cashflow",
        "cashflow",
    )


def _extend_consensus(output_root: Path) -> None:
    """为朝阳永续记录补充一致预期 ROE。"""
    consensus_directory = output_root / "stock" / "consensus" / "suntime"
    for consensus_path in sorted(consensus_directory.glob("suntime_*.csv")):
        records = pd.read_csv(consensus_path)
        stock_position = records["stock_code"].str[:6].astype(int) - 1
        date_position = np.arange(len(records), dtype="float64")
        records["con_roe"] = 9.0 + stock_position * 0.4 + date_position * 0.0001
        records.to_csv(consensus_path, index=False)


def _write_by_year(
    records: pd.DataFrame,
    output_directory: Path,
    prefix: str,
) -> None:
    """按实际公告日年份写出财务 CSV。"""
    output_directory.mkdir(parents=True, exist_ok=True)
    years = pd.to_datetime(
        records["ACTUAL_ANN_DT"].astype("string"),
        format="%Y%m%d",
    ).dt.year
    for year, annual_records in records.groupby(years):
        annual_records.to_csv(output_directory / f"{prefix}_{year}.csv", index=False)
