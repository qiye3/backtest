"""合并腾讯一分钟K线与分时累计成交额，保留未复权价量口径。"""

from __future__ import annotations

import logging
from time import sleep

import pandas as pd
from curl_cffi import requests

RAW_COLUMNS = ["时间", "开盘", "收盘", "最高", "最低", "成交量", "成交额", "均价"]
SOURCE = "tencent.mkline+minute.query"
LOGGER = logging.getLogger(__name__)


def request_market_json(session: requests.Session, url: str, params: dict) -> dict:
    for attempt in range(4):
        try:
            # 控制请求节奏，减少连续请求触发限流。
            sleep(1.1)
            response = session.get(url, params=params, timeout=(10, 30))
            response.raise_for_status()
            return response.json()
        except requests.RequestsError:
            if attempt == 3:
                raise
            LOGGER.warning("行情请求中断，第 %d 次重试", attempt + 1)
            sleep(2 ** (attempt + 1))


def fetch_tencent_minutes(session: requests.Session, code: str) -> pd.DataFrame:
    symbol = code[-2:].lower() + code[:6]
    kline_payload = request_market_json(
        session,
        "https://ifzq.gtimg.cn/appstock/app/kline/mkline",
        {"param": f"{symbol},m1,,320"},
    )
    minute_payload = request_market_json(
        session,
        "https://ifzq.gtimg.cn/appstock/app/minute/query",
        {"code": symbol},
    )
    if kline_payload["code"] != 0 or minute_payload["code"] != 0:
        raise RuntimeError(f"{code} 腾讯行情接口返回异常状态")
    kline_rows = kline_payload["data"][symbol]["m1"]
    minute = minute_payload["data"][symbol]["data"]
    if not kline_rows or not minute["data"]:
        return pd.DataFrame(columns=RAW_COLUMNS)

    bars = pd.DataFrame(kline_rows).iloc[:, :6]
    bars.columns = ["时间", "开盘", "收盘", "最高", "最低", "成交量"]
    bars["时间"] = pd.to_datetime(bars["时间"], format="%Y%m%d%H%M")
    cumulative = pd.DataFrame([row.split() for row in minute["data"]])
    cumulative.columns = ["clock", "close", "volume", "amount"]
    cumulative["时间"] = pd.to_datetime(minute["date"] + cumulative["clock"], format="%Y%m%d%H%M")
    cumulative_amount = pd.to_numeric(cumulative["amount"])
    # 分时接口给出累计人民币成交额，差分后与同一结束时刻的K线成交量配对。
    cumulative["成交额"] = cumulative_amount.diff().fillna(cumulative_amount)
    current_bars = bars[bars["时间"].dt.strftime("%Y%m%d") == minute["date"]]
    result = current_bars.merge(
        cumulative[["时间", "成交额"]], on="时间", how="left", validate="one_to_one",
    )
    if result["成交额"].isna().any():
        raise ValueError(f"{code} K线与累计成交额缺少对应时刻")
    negative_amount = result["成交额"] < 0
    omitted_bars = result.loc[negative_amount, "时间"].dt.strftime("%Y-%m-%d %H:%M:%S").tolist()
    if omitted_bars:
        LOGGER.warning("%s 累计成交额回退，保留分钟缺口 %s", code, omitted_bars)
    # 记录累计成交额回退时刻，发布数据中保留该分钟缺口。
    result = result.loc[~negative_amount].copy()
    result["均价"] = 0.0
    result.attrs["omitted_bars"] = omitted_bars
    result.attrs["source"] = SOURCE
    return result[RAW_COLUMNS]
