"""构造董监高交易强度、聚集行为和历史信息质量因子。"""

from __future__ import annotations

import numpy as np
import pandas as pd

from factors.second_batch_factors.code.event_utils import (
    move_to_next_trading_day,
    normalize_ratio,
    numeric_column,
    records_to_panel,
    text_contains_any,
)
from src.data.market_data import MarketData

INSIDER_TRADE_FACTORS = {
    "insider_net_buy_intensity_60d",
    "clustered_insider_buying_60d",
    "insider_buy_event",
    "insider_sell_event",
    "insider_trade_price_gap",
    "insider_remaining_holding_ratio",
    "insider_trade_reason_group",
    "historical_insider_signal_quality",
}

BUY_KEYWORDS = ("买入", "增持", "购入", "buy", "increase")
SELL_KEYWORDS = ("卖出", "减持", "出售", "sell", "decrease")
MANAGER_KEYWORDS = ("本人", "董事", "监事", "高管", "经理", "director", "manager")
PASSIVE_REASON_KEYWORDS = (
    "股权激励",
    "行权",
    "司法",
    "继承",
    "离婚",
    "协议转让",
    "被动",
    "incentive",
    "judicial",
)


def calculate_insider_trade_factor(
    factor_name: str,
    market_data: MarketData,
) -> pd.DataFrame:
    """根据固定名称计算一个董监高交易因子。"""
    records = _prepare_insider_records(market_data)
    active_records = records.loc[records["is_direct_manager"] & ~records["is_passive"]]

    if factor_name == "insider_net_buy_intensity_60d":
        signed_intensity = active_records["direction"] * active_records[
            "circulating_ratio"
        ]
        daily_flow = records_to_panel(
            active_records,
            signed_intensity,
            market_data,
            aggregation="sum",
            forward_fill=False,
        ).fillna(0.0)
        return daily_flow.rolling(window="60D", min_periods=1).sum()
    if factor_name == "clustered_insider_buying_60d":
        buy_records = active_records.loc[active_records["direction"].eq(1.0)]
        return _clustered_buying_panel(buy_records, market_data)
    if factor_name == "insider_buy_event":
        buy_records = active_records.loc[active_records["direction"].eq(1.0)]
        return records_to_panel(
            buy_records,
            pd.Series(1.0, index=buy_records.index),
            market_data,
            aggregation="max",
            forward_fill=False,
        )
    if factor_name == "insider_sell_event":
        sell_records = active_records.loc[active_records["direction"].eq(-1.0)]
        return records_to_panel(
            sell_records,
            pd.Series(1.0, index=sell_records.index),
            market_data,
            aggregation="max",
            forward_fill=False,
        )
    if factor_name == "insider_trade_price_gap":
        market_price = numeric_column(active_records, "change_period_avg_price")
        trade_price = numeric_column(active_records, "trade_avg_price")
        price_gap = active_records["direction"] * (
            trade_price / market_price.replace(0.0, np.nan) - 1.0
        )
        return records_to_panel(
            active_records,
            price_gap,
            market_data,
            aggregation="mean",
            forward_fill=True,
        )
    if factor_name == "insider_remaining_holding_ratio":
        remaining_ratio = normalize_ratio(active_records["holder_quantity_new_ratio"])
        return records_to_panel(
            active_records,
            remaining_ratio,
            market_data,
            aggregation="max",
            forward_fill=True,
        )
    if factor_name == "insider_trade_reason_group":
        reason_scores = _reason_scores(records)
        return records_to_panel(
            records,
            reason_scores,
            market_data,
            aggregation="mean",
            forward_fill=True,
        )
    if factor_name == "historical_insider_signal_quality":
        return _historical_signal_quality(active_records, market_data)
    raise ValueError(f"未知董监高交易因子: {factor_name}")


def _prepare_insider_records(market_data: MarketData) -> pd.DataFrame:
    """清理内部人交易记录、识别方向并从公告后下一交易日生效。"""
    records = market_data.get_records("major_holder_trade").copy()
    records["source_date"] = pd.to_datetime(
        records["source_date"],
        errors="coerce",
    ).dt.normalize()
    records["effective_date"] = move_to_next_trading_day(
        records["source_date"],
        market_data.calendar,
    )
    records["direction"] = _trade_directions(records["transact_type"])
    records["circulating_ratio"] = normalize_ratio(
        records["transact_quantity_circulating_ratio"]
    )
    relation_text = (
        records["holder_type"].astype("string").fillna("")
        + " "
        + records["manager_relation"].astype("string").fillna("")
        + " "
        + records["holder_manager_relation"].astype("string").fillna("")
    )
    records["is_direct_manager"] = text_contains_any(
        relation_text,
        MANAGER_KEYWORDS,
    )
    reason_text = (
        records["trade_reason_name"].astype("string").fillna("")
        + " "
        + records["trade_detail"].astype("string").fillna("")
    )
    records["is_passive"] = text_contains_any(
        reason_text,
        PASSIVE_REASON_KEYWORDS,
    )
    deduplication_columns = [
        "asset_code",
        "source_date",
        "transact_startdate",
        "transact_enddate",
        "holder_name",
        "transact_type",
        "transact_quantity",
        "trade_avg_price",
    ]
    records = records.sort_values(["asset_code", "source_date"]).drop_duplicates(
        subset=deduplication_columns,
        keep="last",
    )
    return records.dropna(subset=["asset_code", "effective_date", "direction"])


def _trade_directions(transact_type: pd.Series) -> pd.Series:
    """把可解释的买卖文本映射为正负方向，未知代码保持缺失。"""
    direction = pd.Series(np.nan, index=transact_type.index, dtype="float64")
    textual_type = transact_type.astype("string").str.contains(
        r"[A-Za-z一-龥]",
        regex=True,
        na=False,
    )
    buy_mask = text_contains_any(transact_type, BUY_KEYWORDS)
    sell_mask = text_contains_any(transact_type, SELL_KEYWORDS)
    direction.loc[textual_type & buy_mask] = 1.0
    direction.loc[textual_type & sell_mask] = -1.0
    return direction


def _clustered_buying_panel(
    buy_records: pd.DataFrame,
    market_data: MarketData,
) -> pd.DataFrame:
    """逐日统计此前 60 个自然日内至少主动买入一次的不同主体。"""
    output = pd.DataFrame(
        0.0,
        index=market_data.calendar,
        columns=market_data.membership.columns,
    )
    grouped_records = buy_records.dropna(subset=["holder_name"]).groupby(
        ["asset_code", "holder_name"],
        sort=False,
    )
    for (asset_code, _), holder_records in grouped_records:
        if asset_code not in output.columns:
            continue
        holder_events = pd.Series(0.0, index=market_data.calendar)
        effective_dates = holder_records["effective_date"].dropna().unique()
        holder_events.loc[effective_dates] = 1.0
        output[asset_code] += holder_events.rolling(
            window="60D",
            min_periods=1,
        ).max()
    return output


def _reason_scores(records: pd.DataFrame) -> pd.Series:
    """将主动买卖和被动交易映射为有经济含义的事件分数。"""
    scores = records["direction"].copy()
    scores.loc[records["is_passive"]] = 0.0
    scores.loc[~records["is_direct_manager"]] *= 0.5
    return scores


def _historical_signal_quality(
    active_records: pd.DataFrame,
    market_data: MarketData,
) -> pd.DataFrame:
    """在事件后 60 个交易日走完时累计方向调整后的实际收益。"""
    adjusted_close = market_data.get_panel(
        "stock_quote",
        "S_DQ_ADJCLOSE",
    ).astype("float64")
    matured_records = active_records.copy()
    maturity_dates = pd.Series(pd.NaT, index=matured_records.index, dtype="datetime64[ns]")
    signal_quality = pd.Series(np.nan, index=matured_records.index, dtype="float64")
    for record_index, record in matured_records.iterrows():
        event_position = market_data.calendar.get_indexer([record["effective_date"]])[0]
        maturity_position = event_position + 60
        if event_position < 0 or maturity_position >= len(market_data.calendar):
            continue
        asset_code = record["asset_code"]
        start_price = adjusted_close.iloc[event_position][asset_code]
        end_price = adjusted_close.iloc[maturity_position][asset_code]
        if pd.isna(start_price) or pd.isna(end_price) or start_price <= 0:
            continue
        maturity_dates.loc[record_index] = market_data.calendar[maturity_position]
        realized_return = end_price / start_price - 1.0
        signal_quality.loc[record_index] = record["direction"] * realized_return

    matured_records["maturity_date"] = maturity_dates
    quality_events = records_to_panel(
        matured_records,
        signal_quality,
        market_data,
        aggregation="mean",
        forward_fill=False,
        date_column="maturity_date",
    )
    return quality_events.expanding(min_periods=1).mean()
