"""生成基础配置使用的紧凑 synthetic 原始数据。"""

from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT_ROOT = PROJECT_ROOT / "examples" / "data"


def make_synthetic_data(output_root: str | Path) -> None:
    """生成指数行情、历史成员和个股复权收盘价 CSV。"""
    output_root = Path(output_root).expanduser().resolve()
    index_price_directory = output_root / "index" / "prices"
    member_directory = output_root / "index" / "members"
    stock_quote_directory = output_root / "stock" / "daily_quote"
    for directory in [
        index_price_directory,
        member_directory,
        stock_quote_directory,
    ]:
        directory.mkdir(parents=True, exist_ok=True)

    trading_dates = pd.bdate_range("2024-01-02", "2024-06-28")
    stock_codes = [
        f"{stock_number:06d}.SZ"
        for stock_number in range(1, 41)
    ]
    _write_index_prices(index_price_directory, trading_dates)
    _write_members(member_directory, stock_codes)
    _write_stock_quotes(stock_quote_directory, trading_dates, stock_codes)


def _write_index_prices(
    output_directory: Path,
    trading_dates: pd.DatetimeIndex,
) -> None:
    """生成决定交易日历和基准收益的指数收盘价。"""
    date_positions = np.arange(len(trading_dates))
    daily_returns = 0.0003 + 0.002 * np.sin(date_positions / 7)
    index_prices = pd.DataFrame(
        {
            "TRADE_DT": trading_dates.strftime("%Y%m%d"),
            "S_DQ_CLOSE": 1000 * np.cumprod(1 + daily_returns),
        }
    )
    index_prices.to_csv(
        output_directory / "000906.SH_2024.csv",
        index=False,
    )


def _write_members(
    output_directory: Path,
    stock_codes: list[str],
) -> None:
    """把四十只股票平均分配给两个历史指数股票池。"""
    members_by_index = {
        "000906.SH": stock_codes[:20],
        "000852.SH": stock_codes[20:],
    }
    for index_code, member_codes in members_by_index.items():
        member_records = pd.DataFrame(
            {
                "s_con_windcode": member_codes,
                "s_con_indate": "20240102",
                "s_con_outdate": pd.NA,
            }
        )
        member_records.to_csv(
            output_directory / f"{index_code}.csv",
            index=False,
        )


def _write_stock_quotes(
    output_directory: Path,
    trading_dates: pd.DatetimeIndex,
    stock_codes: list[str],
) -> None:
    """生成具有稳定横截面差异的个股复权收盘价。"""
    date_positions = np.arange(len(trading_dates))[:, None]
    stock_positions = np.arange(len(stock_codes))[None, :]
    daily_returns = (
        0.0001
        + stock_positions * 0.000015
        + 0.002 * np.sin(date_positions / 5 + stock_positions / 9)
    )
    adjusted_close = 20 * np.cumprod(1 + daily_returns, axis=0)
    quote_records = pd.DataFrame(
        {
            "TRADE_DT": np.repeat(
                trading_dates.strftime("%Y%m%d"),
                len(stock_codes),
            ),
            "S_INFO_WINDCODE": np.tile(stock_codes, len(trading_dates)),
            "S_DQ_ADJCLOSE": adjusted_close.reshape(-1),
            "OPDATE": np.repeat(
                trading_dates.strftime("%Y-%m-%d 18:00:00"),
                len(stock_codes),
            ),
        }
    )
    quote_records.to_csv(
        output_directory / "quote_2024.csv",
        index=False,
    )


def main() -> None:
    """解析输出目录并重新生成示例原始数据。"""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output-root",
        type=Path,
        default=DEFAULT_OUTPUT_ROOT,
    )
    arguments = parser.parse_args()
    make_synthetic_data(arguments.output_root)


if __name__ == "__main__":
    main()
