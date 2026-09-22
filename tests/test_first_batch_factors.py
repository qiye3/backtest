"""验证第一批24个新数据因子的公式、时点和配置完整性。"""

from __future__ import annotations

import unittest
from pathlib import Path

import numpy as np
import pandas as pd

from factors.first_batch_factors.code.FirstBatchFactor import FIRST_BATCH_FACTORS
from src.data.market_data import MarketData
from src.factors.config import load_factors
from src.factors.engine import calc_factors

PROJECT_ROOT = Path(__file__).resolve().parents[1]
CONFIG_DIRECTORY = PROJECT_ROOT / "factors" / "first_batch_factors" / "config"


class FirstBatchFactorTests(unittest.TestCase):
    """覆盖配置数量、主要公式和回购公告后生效口径。"""

    @classmethod
    def setUpClass(cls) -> None:
        """构造足够覆盖五年滚动窗口的内存市场数据并计算全部因子。"""
        cls.calendar = pd.bdate_range("2021-01-04", periods=700, name="date")
        cls.asset_codes = ["000001.SZ", "000002.SZ"]
        cls.market_data = _make_market_data(cls.calendar, cls.asset_codes)
        cls.factors = load_factors(CONFIG_DIRECTORY)
        cls.factor_values = {
            factor.name: factor.calc(cls.market_data)
            for factor in cls.factors
        }

    def test_all_24_configs_match_documented_factor_names(self) -> None:
        """配置目录应完整且不重复地覆盖24个公开因子。"""
        configured_names = {factor.name for factor in self.factors}
        self.assertEqual(len(self.factors), 24)
        self.assertEqual(configured_names, FIRST_BATCH_FACTORS)

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

    def test_standard_engine_outputs_raw_and_industry_neutral_variants(self) -> None:
        """24份配置通过正式引擎后应生成48个标准变体。"""
        factor_panels = calc_factors(
            self.factors,
            self.market_data,
            max_workers=2,
        )
        expected_names = {
            f"{factor_name}__{suffix}"
            for factor_name in FIRST_BATCH_FACTORS
            for suffix in ("raw", "industry_neutral")
        }
        self.assertEqual(set(factor_panels), expected_names)

    def test_notice_revision_stays_inside_same_report_period(self) -> None:
        """新报告期首次预告不能误算成上一次报告期的修正。"""
        revision = self.factor_values["notice_revision"]["000001.SZ"]
        revision_date = self.calendar[20]
        new_report_date = self.calendar[40]
        self.assertAlmostEqual(revision.loc[revision_date], 0.2)
        self.assertTrue(pd.isna(revision.loc[new_report_date]))

    def test_repurchase_uses_operation_date_then_next_trading_day(self) -> None:
        """晚于公告日的更新状态只能在更新日后的首个交易日生效。"""
        execution = self.factor_values["buyback_execution_intensity"]["000001.SZ"]
        operation_date = self.calendar[30]
        effective_date = self.calendar[31]
        self.assertTrue(pd.isna(execution.loc[operation_date]))
        self.assertTrue(np.isfinite(execution.loc[effective_date]))

    def test_ev_yield_rejects_nonpositive_multiple(self) -> None:
        """负 EBITDA 对应的非正倍数不能通过倒数产生伪高价值信号。"""
        ebitda_ev = self.factor_values["ebitda_ev"]
        self.assertAlmostEqual(ebitda_ev.iloc[0, 0], 0.1)
        self.assertTrue(pd.isna(ebitda_ev.iloc[0, 1]))

    def test_five_year_percentile_becomes_available_after_warmup(self) -> None:
        """五年历史分位只应在至少600个交易日后产生结果。"""
        percentile = self.factor_values["ev_ebitda_percentile_5y"]["000001.SZ"]
        self.assertTrue(pd.isna(percentile.iloc[598]))
        self.assertTrue(np.isfinite(percentile.iloc[599]))


def _make_market_data(
    calendar: pd.DatetimeIndex,
    asset_codes: list[str],
) -> MarketData:
    """构造覆盖三类公式所需字段的最小内存 MarketData。"""
    membership = pd.DataFrame(True, index=calendar, columns=asset_codes)
    source_panels = {
        "profit_notice": _profit_notice_panel(calendar, asset_codes),
        "financial_income": _financial_income_panel(calendar, asset_codes),
        "consensus_suntime": _field_panel(
            calendar,
            asset_codes,
            {
                "con_np": (90.0, 120.0),
                "con_npcgrate_2y": (15.0, 8.0),
            },
        ),
        "stock_valuation": _field_panel(
            calendar,
            asset_codes,
            {"S_VAL_MV": (100_000.0, 160_000.0)},
        ),
        "stock_quote": _field_panel(
            calendar,
            asset_codes,
            {"S_DQ_CLOSE": (10.0, 20.0)},
        ),
        "ev_indicator": _ev_indicator_panel(calendar, asset_codes),
        "financial_indicators": _field_panel(
            calendar,
            asset_codes,
            {
                "S_FA_ROIC": (10.0, 6.0),
                "S_FA_OCFTOOR": (0.18, 0.09),
            },
        ),
        "industry_history": _field_panel(
            calendar,
            asset_codes,
            {"ind_class_code": ("CI1", "CI1")},
        ),
        "repo_wind": _repurchase_records(calendar),
    }
    return MarketData(
        source_panels=source_panels,
        calendar=calendar,
        membership=membership,
        benchmark_index="000906.SH",
    )


def _profit_notice_panel(
    calendar: pd.DatetimeIndex,
    asset_codes: list[str],
) -> pd.DataFrame:
    """生成含同报告期修正和下一报告期首次预告的 PIT 状态。"""
    report_period = pd.DataFrame(pd.NaT, index=calendar, columns=asset_codes)
    report_period.loc[calendar[10]:, :] = pd.Timestamp("2022-12-31")
    report_period.loc[calendar[40]:, :] = pd.Timestamp("2023-03-31")

    lower_profit = pd.DataFrame(np.nan, index=calendar, columns=asset_codes)
    upper_profit = lower_profit.copy()
    lower_profit.loc[calendar[10]:, :] = [80.0, 100.0]
    upper_profit.loc[calendar[10]:, :] = [120.0, 140.0]
    lower_profit.loc[calendar[20]:, "000001.SZ"] = 100.0
    upper_profit.loc[calendar[20]:, "000001.SZ"] = 140.0
    lower_profit = lower_profit.ffill()
    upper_profit = upper_profit.ffill()
    lower_profit.loc[calendar[40]:, :] = [120.0, 130.0]
    upper_profit.loc[calendar[40]:, :] = [160.0, 170.0]

    fields = {
        "s_profitnotice_changemin": _constant_state(calendar, asset_codes, (10.0, -20.0)),
        "s_profitnotice_changemax": _constant_state(calendar, asset_codes, (30.0, 0.0)),
        "s_profitnotice_netprofitmin": lower_profit,
        "s_profitnotice_netprofitmax": upper_profit,
        "s_profitnotice_changemin_ded": _constant_state(
            calendar,
            asset_codes,
            (5.0, -25.0),
        ),
        "s_profitnotice_changemax_ded": _constant_state(
            calendar,
            asset_codes,
            (20.0, -5.0),
        ),
        "s_profitnotice_style": _constant_state(
            calendar,
            asset_codes,
            ("预增", "首亏"),
        ),
        "REPORT_PERIOD": report_period,
    }
    return pd.concat(fields, axis=1, names=["field", "asset_code"])


def _financial_income_panel(
    calendar: pd.DatetimeIndex,
    asset_codes: list[str],
) -> pd.DataFrame:
    """生成与首份预告报告期匹配的正式利润状态。"""
    actual_profit = pd.DataFrame(np.nan, index=calendar, columns=asset_codes)
    actual_period = pd.DataFrame(pd.NaT, index=calendar, columns=asset_codes)
    actual_profit.loc[calendar[25]:, :] = [110.0, 125.0]
    actual_period.loc[calendar[25]:, :] = pd.Timestamp("2022-12-31")
    return pd.concat(
        {
            "NET_PROFIT_EXCL_MIN_INT_INC": actual_profit,
            "REPORT_PERIOD": actual_period,
        },
        axis=1,
        names=["field", "asset_code"],
    )


def _ev_indicator_panel(
    calendar: pd.DatetimeIndex,
    asset_codes: list[str],
) -> pd.DataFrame:
    """生成一只正倍数股票和一只负倍数股票的企业价值序列。"""
    date_position = np.arange(len(calendar), dtype="float64")[:, None]
    primary_multiple = np.column_stack(
        [10.0 + date_position[:, 0] * 0.001, np.full(len(calendar), -5.0)]
    )
    secondary_multiple = np.column_stack(
        [11.0 + date_position[:, 0] * 0.001, np.full(len(calendar), -4.0)]
    )
    fields = {
        "s_val_ev1": pd.DataFrame(
            np.column_stack(
                [1_000.0 + date_position[:, 0], 1_500.0 + date_position[:, 0]]
            ),
            index=calendar,
            columns=asset_codes,
        ),
        "s_val_ev2": pd.DataFrame(
            np.column_stack(
                [950.0 + date_position[:, 0], 1_450.0 + date_position[:, 0]]
            ),
            index=calendar,
            columns=asset_codes,
        ),
        "s_val_evtoebitda": pd.DataFrame(
            primary_multiple,
            index=calendar,
            columns=asset_codes,
        ),
        "s_val_evtoebitda2": pd.DataFrame(
            secondary_multiple,
            index=calendar,
            columns=asset_codes,
        ),
    }
    return pd.concat(fields, axis=1, names=["field", "asset_code"])


def _repurchase_records(calendar: pd.DatetimeIndex) -> pd.DataFrame:
    """生成更新日晚于公告日的两条回购明细。"""
    return pd.DataFrame(
        {
            "asset_code": ["000001.SZ", "000002.SZ"],
            "source_date": [calendar[28], calendar[28]],
            "OPDATE": [calendar[30], calendar[30]],
            "STATUS": ["实施完成", "终止"],
            "QTY": [1_000_000.0, 500_000.0],
            "EXP_QTY": [1_000_000.0, 1_000_000.0],
            "REPURCHASE_FUNDS_RATIO": [100.0, 30.0],
            "REPURCHASE_SHARES_RATIO": [100.0, 50.0],
            "STOCK_REPO_OBJECTIVE_CODE": ["注销", "股权激励"],
        }
    )


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


def _constant_state(
    calendar: pd.DatetimeIndex,
    asset_codes: list[str],
    field_values: tuple[object, object],
) -> pd.DataFrame:
    """生成从首个预告日开始可见的常量状态。"""
    contains_text = any(isinstance(field_value, str) for field_value in field_values)
    state_dtype = "object" if contains_text else "float64"
    state = pd.DataFrame(
        np.nan,
        index=calendar,
        columns=asset_codes,
        dtype=state_dtype,
    )
    state.loc[calendar[10]:, :] = field_values
    return state


if __name__ == "__main__":
    unittest.main()
