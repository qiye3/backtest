"""验证第二批32个新数据因子的公式接口、PIT时点和配置完整性。"""

from __future__ import annotations

import unittest
from pathlib import Path

import numpy as np
import pandas as pd

from factors.second_batch_factors.code.SecondBatchFactor import SECOND_BATCH_FACTORS
from src.data.market_data import MarketData
from src.factors.config import load_factors
from src.factors.engine import calc_factors

PROJECT_ROOT = Path(__file__).resolve().parents[1]
CONFIG_DIRECTORY = PROJECT_ROOT / "factors" / "second_batch_factors" / "config"


class SecondBatchFactorTests(unittest.TestCase):
    """覆盖配置数量、输出契约和四个数据域的关键时点。"""

    @classmethod
    def setUpClass(cls) -> None:
        """构造包含六个年度报告期和多类公告事件的内存市场数据。"""
        cls.calendar = pd.bdate_range("2017-01-02", periods=900, name="date")
        cls.asset_codes = ["000001.SZ", "000002.SZ"]
        cls.financial_positions = [100, 220, 340, 460, 580, 700]
        cls.report_periods = [
            pd.Timestamp(f"{report_year}-12-31")
            for report_year in range(2016, 2022)
        ]
        cls.market_data = _make_market_data(
            cls.calendar,
            cls.asset_codes,
            cls.financial_positions,
            cls.report_periods,
        )
        cls.factors = load_factors(CONFIG_DIRECTORY)
        cls.factor_values = {
            factor.name: factor.calc(cls.market_data)
            for factor in cls.factors
        }

    def test_all_32_configs_match_documented_factor_names(self) -> None:
        """配置目录应完整且不重复地覆盖32个公开因子。"""
        configured_names = {factor.name for factor in self.factors}
        self.assertEqual(len(self.factors), 32)
        self.assertEqual(configured_names, SECOND_BATCH_FACTORS)

    def test_all_factor_outputs_follow_framework_contract(self) -> None:
        """每个因子都应返回与公共日历、股票列一致的 float32 面板。"""
        for factor_name, factor_values in self.factor_values.items():
            with self.subTest(factor_name=factor_name):
                self.assertTrue(factor_values.index.equals(self.calendar))
                self.assertEqual(factor_values.columns.tolist(), self.asset_codes)
                self.assertEqual(
                    factor_values.dtypes.unique().tolist(),
                    [np.dtype("float32")],
                )

    def test_standard_engine_outputs_two_variants_per_factor(self) -> None:
        """32份配置通过正式引擎后应生成64个标准变体。"""
        factor_panels = calc_factors(
            self.factors,
            self.market_data,
            max_workers=2,
        )
        expected_names = {
            f"{factor_name}__{suffix}"
            for factor_name in SECOND_BATCH_FACTORS
            for suffix in ("raw", "industry_neutral")
        }
        self.assertEqual(set(factor_panels), expected_names)

    def test_dividend_announcement_starts_next_trading_day(self) -> None:
        """分红方案不能在公告日收盘前进入可交易因子。"""
        source_position = self.financial_positions[0]
        announced_yield = self.factor_values["announced_dividend_yield"]["000001.SZ"]
        self.assertTrue(pd.isna(announced_yield.iloc[source_position]))
        self.assertTrue(np.isfinite(announced_yield.iloc[source_position + 1]))

    def test_profit_express_uses_announcement_effective_state(self) -> None:
        """快报增长只在同报告期上年基准存在后形成状态。"""
        second_express_position = self.financial_positions[1] - 9
        profit_growth = self.factor_values["express_profit_growth"]["000001.SZ"]
        self.assertTrue(pd.isna(profit_growth.iloc[second_express_position - 1]))
        self.assertTrue(np.isfinite(profit_growth.iloc[second_express_position]))

    def test_insider_trade_uses_day_after_disclosure(self) -> None:
        """内部人交易只能从公告后的下一交易日形成事件。"""
        buy_event = self.factor_values["insider_buy_event"]["000001.SZ"]
        self.assertTrue(pd.isna(buy_event.iloc[300]))
        self.assertEqual(buy_event.iloc[301], 1.0)

    def test_insider_rolling_signals_expire_after_60_calendar_days(self) -> None:
        """净买入和聚集买入不能把自然日窗口误写成交易日或永久状态。"""
        last_effective_date = self.calendar[311]
        expired_position = self.calendar.searchsorted(
            last_effective_date + pd.Timedelta(days=60),
            side="right",
        )
        net_intensity = self.factor_values[
            "insider_net_buy_intensity_60d"
        ]["000001.SZ"]
        clustered_buying = self.factor_values[
            "clustered_insider_buying_60d"
        ]["000001.SZ"]
        self.assertEqual(net_intensity.iloc[expired_position], 0.0)
        self.assertEqual(clustered_buying.iloc[expired_position], 0.0)

    def test_customer_data_waits_for_financial_report_announcement(self) -> None:
        """客户数据不得按报告期回填，只能从匹配财报公告后生效。"""
        customer_share = self.factor_values["top5_customer_share"]["000001.SZ"]
        first_financial_position = self.financial_positions[0]
        self.assertTrue(pd.isna(customer_share.iloc[first_financial_position]))
        self.assertTrue(np.isfinite(customer_share.iloc[first_financial_position + 1]))


def _make_market_data(
    calendar: pd.DatetimeIndex,
    asset_codes: list[str],
    financial_positions: list[int],
    report_periods: list[pd.Timestamp],
) -> MarketData:
    """构造四个第二批数据域所需的最小内存 MarketData。"""
    membership = pd.DataFrame(True, index=calendar, columns=asset_codes)
    income_panel, cashflow_panel = _financial_panels(
        calendar,
        asset_codes,
        financial_positions,
        report_periods,
    )
    source_panels = {
        "stock_quote": _stock_quote_panel(calendar, asset_codes),
        "industry_history": _field_panel(
            calendar,
            asset_codes,
            {"ind_class_code": ("CI1", "CI1")},
        ),
        "financial_income": income_panel,
        "financial_cashflow": cashflow_panel,
        "profit_express": _profit_express_panel(
            calendar,
            asset_codes,
            financial_positions,
            report_periods,
        ),
        "profit_notice": _profit_notice_panel(
            calendar,
            asset_codes,
            financial_positions,
            report_periods,
        ),
        "consensus_suntime": _field_panel(
            calendar,
            asset_codes,
            {"con_np": (100.0, 130.0)},
        ),
        "dividend_wind": _dividend_records(
            calendar,
            asset_codes,
            financial_positions,
            report_periods,
        ),
        "major_holder_trade": _insider_records(calendar),
        "customer": _customer_records(asset_codes, report_periods),
        "supplier": _supplier_records(asset_codes, report_periods),
        "mb_product_rank": _product_records(asset_codes, report_periods),
        "mb_consist": _business_consist_records(asset_codes, report_periods),
    }
    return MarketData(
        source_panels=source_panels,
        calendar=calendar,
        membership=membership,
        benchmark_index="000906.SH",
    )


def _financial_panels(
    calendar: pd.DatetimeIndex,
    asset_codes: list[str],
    financial_positions: list[int],
    report_periods: list[pd.Timestamp],
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """生成正式财报利润、收入和经营现金流 PIT 状态。"""
    net_profit = _empty_panel(calendar, asset_codes)
    total_revenue = _empty_panel(calendar, asset_codes)
    operating_cashflow = _empty_panel(calendar, asset_codes)
    period_state = _empty_panel(calendar, asset_codes, object_dtype=True)
    for event_number, (position, report_period) in enumerate(
        zip(financial_positions, report_periods, strict=True)
    ):
        net_profit.loc[calendar[position] :, :] = [110.0 + event_number * 12, 140.0 + event_number * 10]
        total_revenue.loc[calendar[position] :, :] = [1_000.0 + event_number * 100, 1_300.0 + event_number * 90]
        operating_cashflow.loc[calendar[position] :, :] = [180.0 + event_number * 15, 210.0 + event_number * 12]
        _assign_timestamp_state(
            period_state,
            calendar[position],
            report_period,
        )
    income_panel = pd.concat(
        {
            "NET_PROFIT_EXCL_MIN_INT_INC": net_profit,
            "TOT_OPER_REV": total_revenue,
            "REPORT_PERIOD": period_state,
        },
        axis=1,
        names=["field", "asset_code"],
    )
    cashflow_panel = pd.concat(
        {
            "NET_CASH_FLOWS_OPER_ACT": operating_cashflow,
            "REPORT_PERIOD": period_state.copy(),
        },
        axis=1,
        names=["field", "asset_code"],
    )
    return income_panel, cashflow_panel


def _profit_express_panel(
    calendar: pd.DatetimeIndex,
    asset_codes: list[str],
    financial_positions: list[int],
    report_periods: list[pd.Timestamp],
) -> pd.DataFrame:
    """生成比正式财报提前九个交易日生效的快报状态。"""
    net_profit = _empty_panel(calendar, asset_codes)
    revenue = _empty_panel(calendar, asset_codes)
    announcement_date = _empty_panel(calendar, asset_codes, object_dtype=True)
    period_state = _empty_panel(calendar, asset_codes, object_dtype=True)
    for event_number, (financial_position, report_period) in enumerate(
        zip(financial_positions, report_periods, strict=True)
    ):
        effective_position = financial_position - 9
        source_date = calendar[effective_position - 1]
        net_profit.loc[calendar[effective_position] :, :] = [108.0 + event_number * 12, 137.0 + event_number * 10]
        revenue.loc[calendar[effective_position] :, :] = [980.0 + event_number * 100, 1_270.0 + event_number * 90]
        announcement_date.loc[calendar[effective_position] :, :] = source_date.strftime("%Y%m%d")
        _assign_timestamp_state(
            period_state,
            calendar[effective_position],
            report_period,
        )
    return pd.concat(
        {
            "net_profit_excl_min_int_inc": net_profit,
            "oper_rev": revenue,
            "ann_dt": announcement_date,
            "REPORT_PERIOD": period_state,
        },
        axis=1,
        names=["field", "asset_code"],
    )


def _profit_notice_panel(
    calendar: pd.DatetimeIndex,
    asset_codes: list[str],
    financial_positions: list[int],
    report_periods: list[pd.Timestamp],
) -> pd.DataFrame:
    """生成早于快报的业绩预告区间状态。"""
    lower_profit = _empty_panel(calendar, asset_codes)
    upper_profit = _empty_panel(calendar, asset_codes)
    period_state = _empty_panel(calendar, asset_codes, object_dtype=True)
    for event_number, (financial_position, report_period) in enumerate(
        zip(financial_positions, report_periods, strict=True)
    ):
        effective_position = financial_position - 15
        lower_profit.loc[calendar[effective_position] :, :] = [100.0 + event_number * 12, 130.0 + event_number * 10]
        upper_profit.loc[calendar[effective_position] :, :] = [106.0 + event_number * 12, 136.0 + event_number * 10]
        _assign_timestamp_state(
            period_state,
            calendar[effective_position],
            report_period,
        )
    return pd.concat(
        {
            "s_profitnotice_netprofitmin": lower_profit,
            "s_profitnotice_netprofitmax": upper_profit,
            "REPORT_PERIOD": period_state,
        },
        axis=1,
        names=["field", "asset_code"],
    )


def _stock_quote_panel(
    calendar: pd.DatetimeIndex,
    asset_codes: list[str],
) -> pd.DataFrame:
    """生成递增的未复权和复权收盘价。"""
    day_number = np.arange(len(calendar), dtype="float64")
    close_price = pd.DataFrame(
        np.column_stack([10.0 + day_number * 0.01, 20.0 + day_number * 0.015]),
        index=calendar,
        columns=asset_codes,
    )
    return pd.concat(
        {
            "S_DQ_CLOSE": close_price,
            "S_DQ_ADJCLOSE": close_price.copy(),
        },
        axis=1,
        names=["field", "asset_code"],
    )


def _dividend_records(
    calendar: pd.DatetimeIndex,
    asset_codes: list[str],
    financial_positions: list[int],
    report_periods: list[pd.Timestamp],
) -> pd.DataFrame:
    """生成六年普通现金分红方案及除息日。"""
    rows: list[dict[str, object]] = []
    for event_number, (position, report_period) in enumerate(
        zip(financial_positions, report_periods, strict=True)
    ):
        for asset_number, asset_code in enumerate(asset_codes):
            cash_dps = 0.20 + event_number * 0.03 + asset_number * 0.02
            rows.append(
                {
                    "asset_code": asset_code,
                    "source_date": calendar[position],
                    "report_period": report_period,
                    "CASH_DVD_PER_SH_PRE_TAX": cash_dps,
                    "TOT_CASH_DVD": 50.0 + event_number * 6 + asset_number * 5,
                    "S_DIV_PROGRESS": "实施",
                    "S_DIV_OBJECT": "普通股东",
                    "DISTRIBUTION_MODEL": "普通现金分红",
                    "EX_DT": calendar[position + 5],
                }
            )
    return pd.DataFrame(rows)


def _insider_records(calendar: pd.DatetimeIndex) -> pd.DataFrame:
    """生成两名高管增持和一名高管减持事件。"""
    return pd.DataFrame(
        {
            "asset_code": ["000001.SZ", "000001.SZ", "000002.SZ"],
            "source_date": [calendar[300], calendar[310], calendar[350]],
            "transact_startdate": [calendar[295], calendar[305], calendar[345]],
            "transact_enddate": [calendar[299], calendar[309], calendar[349]],
            "holder_name": ["董事甲", "高管乙", "董事丙"],
            "holder_type": ["董事", "高管", "董事"],
            "manager_relation": ["本人", "本人", "本人"],
            "holder_manager_relation": ["本人", "本人", "本人"],
            "transact_type": ["增持", "买入", "减持"],
            "transact_quantity": [100_000.0, 80_000.0, 60_000.0],
            "transact_quantity_circulating_ratio": [0.2, 0.1, 0.15],
            "trade_avg_price": [13.1, 13.3, 25.1],
            "change_period_avg_price": [13.0, 13.2, 25.0],
            "holder_quantity_new_ratio": [0.8, 0.5, 0.4],
            "trade_reason_code": ["A", "A", "B"],
            "trade_reason_name": ["主动增持", "主动增持", "个人资金需求"],
            "trade_detail": ["集中竞价", "集中竞价", "集中竞价"],
        }
    )


def _customer_records(
    asset_codes: list[str],
    report_periods: list[pd.Timestamp],
) -> pd.DataFrame:
    """生成各公司每年前三大客户及占比。"""
    rows: list[dict[str, object]] = []
    for report_number, report_period in enumerate(report_periods):
        for asset_code in asset_codes:
            for rank_number in range(1, 4):
                rows.append(
                    {
                        "asset_code": asset_code,
                        "report_period": report_period,
                        "customer_name_rank": f"客户{rank_number + report_number % 2}",
                        "s_info_amount": 100.0 - rank_number * 10,
                        "pct": 12.0 - rank_number + report_number * 0.2,
                    }
                )
    return pd.DataFrame(rows)


def _supplier_records(
    asset_codes: list[str],
    report_periods: list[pd.Timestamp],
) -> pd.DataFrame:
    """生成各公司每年前三大供应商及占比。"""
    rows: list[dict[str, object]] = []
    for report_number, report_period in enumerate(report_periods):
        for asset_code in asset_codes:
            for rank_number in range(1, 4):
                rows.append(
                    {
                        "asset_code": asset_code,
                        "report_period": report_period,
                        "supplier_rank": rank_number,
                        "s_info_amount": 80.0 - rank_number * 8,
                        "pct": 10.0 - rank_number + report_number * 0.1,
                    }
                )
    return pd.DataFrame(rows)


def _product_records(
    asset_codes: list[str],
    report_periods: list[pd.Timestamp],
) -> pd.DataFrame:
    """生成两个毛利率不同的产品分部。"""
    rows: list[dict[str, object]] = []
    for report_number, report_period in enumerate(report_periods):
        for asset_code in asset_codes:
            rows.extend(
                [
                    {
                        "asset_code": asset_code,
                        "report_period": report_period,
                        "mb_name_product": "高毛利产品",
                        "mb_revenue_product": 600.0 + report_number * 40,
                        "mb_cost_product": 300.0 + report_number * 10,
                    },
                    {
                        "asset_code": asset_code,
                        "report_period": report_period,
                        "mb_name_product": "基础产品",
                        "mb_revenue_product": 400.0 + report_number * 20,
                        "mb_cost_product": 320.0 + report_number * 15,
                    },
                ]
            )
    return pd.DataFrame(rows)


def _business_consist_records(
    asset_codes: list[str],
    report_periods: list[pd.Timestamp],
) -> pd.DataFrame:
    """生成逐年增长的海外收入。"""
    rows = [
        {
            "asset_code": asset_code,
            "report_period": report_period,
            "mb_overseas_revenue": 120.0 + report_number * 25,
        }
        for report_number, report_period in enumerate(report_periods)
        for asset_code in asset_codes
    ]
    return pd.DataFrame(rows)


def _field_panel(
    calendar: pd.DatetimeIndex,
    asset_codes: list[str],
    fields: dict[str, tuple[object, object]],
) -> pd.DataFrame:
    """把按股票给定的常量字段转换成 MarketData 多层列面板。"""
    field_panels = {
        field_name: pd.DataFrame(
            np.tile(field_values, (len(calendar), 1)),
            index=calendar,
            columns=asset_codes,
        )
        for field_name, field_values in fields.items()
    }
    return pd.concat(field_panels, axis=1, names=["field", "asset_code"])


def _empty_panel(
    calendar: pd.DatetimeIndex,
    asset_codes: list[str],
    object_dtype: bool = False,
) -> pd.DataFrame:
    """生成数值或对象类型的空日频面板。"""
    panel_dtype = "object" if object_dtype else "float64"
    return pd.DataFrame(
        np.nan,
        index=calendar,
        columns=asset_codes,
        dtype=panel_dtype,
    )


def _assign_timestamp_state(
    panel: pd.DataFrame,
    effective_date: pd.Timestamp,
    state_timestamp: pd.Timestamp,
) -> None:
    """把同一时间戳状态写入生效日后的每个股票列。"""
    for asset_code in panel.columns:
        panel.loc[effective_date:, asset_code] = state_timestamp


if __name__ == "__main__":
    unittest.main()
