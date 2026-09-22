"""把本地 Wind Parquet 整理成 factor-backtest 正式数据目录。"""

from __future__ import annotations

import argparse
import json
from concurrent.futures import ThreadPoolExecutor
from functools import partial
from pathlib import Path

import numpy as np
import pandas as pd

CSI800_CODE = "000906.SH"
CSI1000_CODE = "000852.SH"


def prepare_wind_formal_data(
    wind_cache_root: Path,
    output_root: Path,
    start_date: pd.Timestamp,
    end_date: pd.Timestamp,
    max_workers: int,
) -> dict[str, object]:
    """整理指数价格、静态成员区间和个股复权收盘价量。"""
    csi1800_root = wind_cache_root / "raw" / "csi1800_2010"
    csi800_root = wind_cache_root / "raw" / "csi800_2010"
    csi1800_universe = pd.read_parquet(csi1800_root / "universe.parquet")
    csi800_universe = pd.read_parquet(csi800_root / "universe.parquet")
    csi1800_codes = pd.Index(csi1800_universe["code"], name="asset_code")
    csi800_codes = pd.Index(csi800_universe["code"], name="asset_code")
    csi1000_codes = csi1800_codes.difference(csi800_codes, sort=False)

    benchmark_path = (
        csi800_root / "daily_bars" / f"{CSI800_CODE}.parquet"
    )
    benchmark_records = _load_benchmark_records(
        benchmark_path,
        start_date,
        end_date,
    )
    stock_paths = [
        csi1800_root / "daily_bars" / f"{code}.parquet"
        for code in csi1800_codes
    ]
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        stock_parts = list(
            executor.map(
                partial(
                    _load_adjusted_stock_records,
                    start_date=start_date,
                    end_date=end_date,
                ),
                stock_paths,
            )
        )
    stock_records = pd.concat(stock_parts, ignore_index=True)

    _write_annual_records(
        benchmark_records,
        output_root / "index" / "prices",
        f"{CSI800_CODE}_{{year}}.csv",
    )
    _write_annual_records(
        stock_records,
        output_root / "stock" / "daily_quote",
        "quote_{year}.csv",
    )
    _write_static_members(
        output_root=output_root,
        index_code=CSI800_CODE,
        asset_codes=csi800_codes,
        start_date=start_date,
    )
    _write_static_members(
        output_root=output_root,
        index_code=CSI1000_CODE,
        asset_codes=csi1000_codes,
        start_date=start_date,
    )

    trading_days = benchmark_records["TRADE_DT"].nunique()
    expected_stock_observations = trading_days * len(csi1800_codes)
    quality_summary = {
        "source": str(csi1800_root),
        "output_root": str(output_root),
        "start_date": str(start_date.date()),
        "end_date": str(end_date.date()),
        "trading_days": int(trading_days),
        "stock_count": len(csi1800_codes),
        "csi800_count": len(csi800_codes),
        "csi1000_count": len(csi1000_codes),
        "stock_price_observations": len(stock_records),
        "stock_price_missing_rate": (
            1 - len(stock_records) / expected_stock_observations
        ),
        "constituent_snapshot_date": str(
            pd.Timestamp(csi1800_universe["snapshot_date"].iloc[0]).date()
        ),
        "survivorship_bias": "current constituent snapshot applied to full period",
        "adjustment": "cumprod(close / prev_close)",
    }
    output_root.mkdir(parents=True, exist_ok=True)
    (output_root / "data_quality.json").write_text(
        json.dumps(quality_summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return quality_summary


def _load_benchmark_records(
    source_path: Path,
    start_date: pd.Timestamp,
    end_date: pd.Timestamp,
) -> pd.DataFrame:
    """读取框架用于交易日历和基准曲线的指数收盘价。"""
    raw_bars = pd.read_parquet(
        source_path,
        columns=["trade_date", "close"],
    )
    selected_bars = raw_bars.loc[
        raw_bars["trade_date"].between(start_date, end_date)
    ].sort_values("trade_date")
    return pd.DataFrame(
        {
            "TRADE_DT": selected_bars["trade_date"].dt.strftime("%Y%m%d"),
            "S_DQ_CLOSE": selected_bars["close"].to_numpy(),
        }
    )


def _load_adjusted_stock_records(
    source_path: Path,
    start_date: pd.Timestamp,
    end_date: pd.Timestamp,
) -> pd.DataFrame:
    """用 Wind 每日涨跌链接复权收盘价，并保留成交量与成交额。"""
    raw_bars = pd.read_parquet(
        source_path,
        columns=[
            "trade_date",
            "prev_close",
            "close",
            "volume_shares",
            "amount_cny",
            "code",
        ],
    )
    selected_bars = raw_bars.loc[
        raw_bars["trade_date"].between(start_date, end_date)
    ].sort_values("trade_date")
    if selected_bars["trade_date"].duplicated().any():
        raise ValueError(f"行情日期重复: {source_path}")

    daily_growth = selected_bars["close"] / selected_bars["prev_close"]
    if (~np.isfinite(daily_growth) | (daily_growth <= 0)).any():
        raise ValueError(f"行情价格无效: {source_path}")
    adjusted_close = selected_bars["prev_close"].iloc[0] * daily_growth.cumprod()
    operation_times = selected_bars["trade_date"] + pd.Timedelta(hours=18)
    return pd.DataFrame(
        {
            "TRADE_DT": selected_bars["trade_date"].dt.strftime("%Y%m%d"),
            "S_INFO_WINDCODE": selected_bars["code"].to_numpy(),
            "S_DQ_ADJCLOSE": adjusted_close.to_numpy(),
            "S_DQ_VOLUME": selected_bars["volume_shares"].to_numpy(),
            "S_DQ_AMOUNT": selected_bars["amount_cny"].to_numpy(),
            # 原始缓存每个交易日只有一个版本；固定收盘后时间满足正式去重契约。
            "OPDATE": operation_times.dt.strftime("%Y-%m-%d %H:%M:%S"),
        }
    )


def _write_annual_records(
    records: pd.DataFrame,
    output_directory: Path,
    filename_template: str,
) -> None:
    """按交易年份覆盖写入框架会扫描的年度 CSV。"""
    output_directory.mkdir(parents=True, exist_ok=True)
    years = records["TRADE_DT"].str[:4].astype(int)
    for year, annual_records in records.groupby(years, sort=True):
        output_path = output_directory / filename_template.format(year=year)
        annual_records.to_csv(output_path, index=False)


def _write_static_members(
    output_root: Path,
    index_code: str,
    asset_codes: pd.Index,
    start_date: pd.Timestamp,
) -> None:
    """把当前成份快照显式表示为覆盖研究区间的静态成员。"""
    member_directory = output_root / "index" / "members"
    member_directory.mkdir(parents=True, exist_ok=True)
    member_records = pd.DataFrame(
        {
            "s_con_windcode": asset_codes,
            "s_con_indate": start_date.strftime("%Y%m%d"),
            "s_con_outdate": pd.NA,
        }
    )
    member_records.to_csv(member_directory / f"{index_code}.csv", index=False)


def main() -> None:
    """解析源目录、输出目录和研究范围并生成正式数据。"""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--wind-cache-root", required=True, type=Path)
    parser.add_argument("--output-root", required=True, type=Path)
    parser.add_argument("--start", required=True)
    parser.add_argument("--end", required=True)
    parser.add_argument("--max-workers", type=int, default=4)
    arguments = parser.parse_args()
    quality_summary = prepare_wind_formal_data(
        wind_cache_root=arguments.wind_cache_root.expanduser().resolve(),
        output_root=arguments.output_root.expanduser().resolve(),
        start_date=pd.Timestamp(arguments.start),
        end_date=pd.Timestamp(arguments.end),
        max_workers=arguments.max_workers,
    )
    print(json.dumps(quality_summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
