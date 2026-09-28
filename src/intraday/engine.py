"""把目标仓位、分钟行情和真实成交约束串成账户回测。"""

from __future__ import annotations

from dataclasses import asdict, dataclass

import numpy as np
import pandas as pd

from src.intraday.config import MinuteBacktestConfig
from src.intraday.execution import ExecutionModel, Fill, Order, Position


@dataclass
class BacktestResult:
    """保存可审计的订单、成交、持仓和净值明细。"""

    orders: pd.DataFrame
    fills: pd.DataFrame
    positions: pd.DataFrame
    nav: pd.DataFrame
    metrics: dict[str, float]


class MinuteBacktestEngine:
    """运行多头现金账户的分钟级目标仓位回测。"""

    def __init__(self, config: MinuteBacktestConfig) -> None:
        self.config = config
        self.execution = ExecutionModel(config.execution, config.costs)
        self.cash = config.account.initial_capital
        self.positions: dict[str, Position] = {}
        self.orders: list[Order] = []
        self.fills: list[Fill] = []
        self.last_prices: dict[str, float] = {}
        self.active_target_weights: dict[str, float] | None = None
        self._next_order_id = 1

    def run(
        self,
        bars: pd.DataFrame,
        targets: pd.DataFrame,
        corporate_actions: pd.DataFrame | None = None,
    ) -> BacktestResult:
        """按时间推进账户，信号只能影响其后至少一根 bar。"""
        market = _validate_bars(bars)
        if market.empty:
            raise ValueError("回测区间没有可用分钟行情")
        target_groups = {
            timestamp: group.set_index("code")["target_weight"].to_dict()
            for timestamp, group in targets.groupby("signal_timestamp", sort=True)
        }
        timeline = pd.Index(market["timestamp"].drop_duplicates().sort_values())
        activations = _activation_schedule(
            timeline,
            target_groups,
            self.config.execution.execution_delay_bars,
        )
        actions = _corporate_action_lookup(corporate_actions)
        nav_records: list[dict[str, object]] = []
        position_records: list[dict[str, object]] = []
        previous_date: pd.Timestamp | None = None

        for timestamp, minute_bars in market.groupby("timestamp", sort=True):
            trading_date = timestamp.tz_localize(None).normalize()
            is_new_trading_date = previous_date is None or trading_date != previous_date
            if is_new_trading_date:
                self._cancel_expired_orders()
                self._apply_corporate_actions(trading_date, actions)

            bars_by_code = minute_bars.set_index("code", drop=False)
            self.last_prices.update(minute_bars.set_index("code")["close"].to_dict())
            if is_new_trading_date and self.active_target_weights is not None:
                self._submit_rebalance_orders(
                    timestamp,
                    self.active_target_weights,
                    bars_by_code,
                )
            if timestamp in activations:
                for weights in activations[timestamp]:
                    self.active_target_weights = weights
                    self._submit_rebalance_orders(timestamp, weights, bars_by_code)
            if self.config.account.liquidate_at_end and timestamp == timeline[-1]:
                self.active_target_weights = {}
                self._submit_rebalance_orders(timestamp, {}, bars_by_code)

            self._match_orders(timestamp, trading_date, bars_by_code)
            if self.active_target_weights is not None and not self._has_open_orders():
                self.active_target_weights = None
            nav = self._portfolio_value()
            nav_records.append(
                {
                    "timestamp": timestamp,
                    "cash": self.cash,
                    "market_value": nav - self.cash,
                    "nav": nav,
                }
            )
            for code, position in sorted(self.positions.items()):
                if position.shares:
                    position_records.append(
                        {
                            "timestamp": timestamp,
                            "code": code,
                            "shares": position.shares,
                            "close": self.last_prices.get(code, np.nan),
                            "market_value": position.shares * self.last_prices.get(code, np.nan),
                        }
                    )
            previous_date = trading_date

        self._cancel_expired_orders()
        nav_frame = pd.DataFrame(nav_records)
        return BacktestResult(
            orders=pd.DataFrame([asdict(order) for order in self.orders]),
            fills=pd.DataFrame([asdict(fill) for fill in self.fills]),
            positions=pd.DataFrame(position_records),
            nav=nav_frame,
            metrics=_calculate_metrics(nav_frame, self.fills),
        )

    def _submit_rebalance_orders(
        self,
        timestamp: pd.Timestamp,
        target_weights: dict[str, float],
        bars_by_code: pd.DataFrame,
    ) -> None:
        self._cancel_open_orders("replaced_by_new_signal")
        nav = self._portfolio_value()
        all_codes = set(target_weights) | set(self.positions)
        candidates: list[tuple[str, str, int]] = []
        for code in sorted(all_codes):
            if code in bars_by_code.index:
                reference_price = float(bars_by_code.loc[code, "vwap"])
            else:
                reference_price = self.last_prices.get(code, 0.0)
            if reference_price <= 0:
                continue
            target_shares = int(nav * target_weights.get(code, 0.0) / reference_price)
            target_shares = (
                target_shares // self.config.execution.lot_size
                * self.config.execution.lot_size
            )
            current_shares = self.positions.get(code, Position()).shares
            difference = target_shares - current_shares
            if difference:
                side = "buy" if difference > 0 else "sell"
                candidates.append((side, code, abs(difference)))
        for side, code, shares in sorted(candidates, key=lambda value: value[0] != "sell"):
            self.orders.append(
                Order(
                    order_id=self._next_order_id,
                    created_at=timestamp,
                    code=code,
                    side=side,
                    requested_shares=shares,
                    remaining_shares=shares,
                )
            )
            self._next_order_id += 1

    def _match_orders(
        self,
        timestamp: pd.Timestamp,
        trading_date: pd.Timestamp,
        bars_by_code: pd.DataFrame,
    ) -> None:
        for order in self.orders:
            if order.status not in {"open", "partially_filled"}:
                continue
            if order.created_at.date() != timestamp.date() or order.code not in bars_by_code.index:
                continue
            position = self.positions.setdefault(order.code, Position())
            sellable = position.sellable_shares(
                trading_date,
                self.config.execution.enforce_t_plus_one,
            )
            fill = self.execution.match(order, bars_by_code.loc[order.code], self.cash, sellable)
            if fill is None:
                continue
            self.fills.append(fill)
            if fill.side == "buy":
                self.cash -= fill.notional + fill.total_cost
                position.buy(trading_date, fill.shares)
            else:
                self.cash += fill.notional - fill.total_cost
                position.sell(
                    trading_date,
                    fill.shares,
                    self.config.execution.enforce_t_plus_one,
                )

    def _apply_corporate_actions(
        self,
        trading_date: pd.Timestamp,
        actions: dict[pd.Timestamp, list[dict[str, object]]],
    ) -> None:
        for action in actions.get(trading_date, []):
            code = str(action["code"])
            position = self.positions.get(code)
            if position is None or position.shares == 0:
                continue
            original_shares = position.shares
            self.cash += original_shares * float(action["cash_dividend_per_share"])
            ratio = float(action["share_ratio"])
            if ratio:
                position.lots_by_date = {
                    date: int(round(shares * (1 + ratio)))
                    for date, shares in position.lots_by_date.items()
                }
                position.shares = sum(position.lots_by_date.values())

    def _portfolio_value(self) -> float:
        market_value = sum(
            position.shares * self.last_prices.get(code, 0.0)
            for code, position in self.positions.items()
        )
        return self.cash + market_value

    def _cancel_expired_orders(self) -> None:
        self._cancel_open_orders("day_expired")

    def _cancel_open_orders(self, reason: str) -> None:
        for order in self.orders:
            if order.status in {"open", "partially_filled"}:
                order.status = "cancelled"
                order.reject_reason = reason

    def _has_open_orders(self) -> bool:
        return any(
            order.status in {"open", "partially_filled"}
            for order in self.orders
        )


def _activation_schedule(
    timeline: pd.Index,
    target_groups: dict[pd.Timestamp, dict[str, float]],
    delay_bars: int,
) -> dict[pd.Timestamp, list[dict[str, float]]]:
    schedule: dict[pd.Timestamp, list[dict[str, float]]] = {}
    for signal_timestamp, weights in target_groups.items():
        first_later = timeline.searchsorted(signal_timestamp, side="right")
        activation_index = first_later + delay_bars - 1
        if activation_index >= len(timeline):
            continue
        activation = timeline[activation_index]
        schedule.setdefault(activation, []).append(weights)
    return schedule


def _validate_bars(bars: pd.DataFrame) -> pd.DataFrame:
    required = {"timestamp", "code", "open", "high", "low", "close", "volume", "vwap"}
    missing = required - set(bars)
    if missing:
        raise ValueError(f"分钟行情缺少字段: {sorted(missing)}")
    market = bars.copy()
    market["timestamp"] = pd.to_datetime(market["timestamp"])
    if market["timestamp"].dt.tz is None:
        raise ValueError("分钟行情 timestamp 必须带时区")
    if market.duplicated(["timestamp", "code"]).any():
        raise ValueError("分钟行情 timestamp 与 code 组合不能重复")
    return market.sort_values(["timestamp", "code"], kind="stable").reset_index(drop=True)


def _corporate_action_lookup(
    actions: pd.DataFrame | None,
) -> dict[pd.Timestamp, list[dict[str, object]]]:
    if actions is None or actions.empty:
        return {}
    normalized = actions.copy()
    normalized["date"] = pd.to_datetime(normalized["date"]).dt.normalize().dt.tz_localize(None)
    return {
        date: group.to_dict("records")
        for date, group in normalized.groupby("date", sort=True)
    }


def _calculate_metrics(nav: pd.DataFrame, fills: list[Fill]) -> dict[str, float]:
    if nav.empty:
        return {}
    series = nav.set_index("timestamp")["nav"]
    daily = series.groupby(series.index.normalize()).last()
    daily_returns = daily.pct_change().dropna()
    total_return = series.iloc[-1] / series.iloc[0] - 1
    running_max = series.cummax()
    max_drawdown = (series / running_max - 1).min()
    annualized_volatility = daily_returns.std(ddof=1) * np.sqrt(252)
    annualized_return = (1 + total_return) ** (252 / max(len(daily), 1)) - 1
    sharpe = 0.0
    if len(daily_returns) > 1 and daily_returns.std(ddof=1) > 0:
        sharpe = daily_returns.mean() / daily_returns.std(ddof=1) * np.sqrt(252)
    return {
        "initial_nav": float(series.iloc[0]),
        "final_nav": float(series.iloc[-1]),
        "total_return": float(total_return),
        "annualized_return": float(annualized_return),
        "annualized_volatility": float(annualized_volatility),
        "sharpe_ratio": float(sharpe),
        "max_drawdown": float(max_drawdown),
        "turnover_notional": float(sum(fill.notional for fill in fills)),
        "transaction_cost": float(sum(fill.total_cost for fill in fills)),
    }
