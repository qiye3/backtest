"""用当日收盘价相对日内 VWAP 的强弱生成次日等权目标。"""

from __future__ import annotations

import pandas as pd

from src.intraday.strategy import DailyMinuteContext


class DailyVwapMomentumStrategy:
    """演示分钟日频策略接口，不代表推荐的投资策略。"""

    def __init__(self, selected_count: int = 2) -> None:
        if selected_count <= 0:
            raise ValueError("selected_count 必须为正整数")
        self.selected_count = selected_count

    def on_day_close(
        self,
        trading_date: pd.Timestamp,
        bars: pd.DataFrame,
        context: DailyMinuteContext,
    ) -> pd.DataFrame:
        del trading_date
        grouped = bars.groupby("code", sort=True)
        daily_close = grouped["close"].last()
        daily_amount = grouped["amount"].sum()
        daily_volume = grouped["volume"].sum()
        daily_vwap = daily_amount / daily_volume.replace(0, pd.NA)
        momentum = (daily_close / daily_vwap - 1).dropna().sort_values(ascending=False)
        selected_codes = momentum.head(self.selected_count).index

        targets = pd.DataFrame(
            {
                "code": context.universe_codes,
                "target_weight": 0.0,
            }
        )
        if len(selected_codes) > 0:
            selected_weight = 1.0 / len(selected_codes)
            targets.loc[targets["code"].isin(selected_codes), "target_weight"] = selected_weight
        return targets
