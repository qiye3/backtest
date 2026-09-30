"""把目标仓位、分钟行情和真实成交约束串成账户回测。"""

from __future__ import annotations

from collections.abc import Iterable
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
        self._unresolved_target_codes: set[str] = set()
        self._next_order_id = 1
        self._previous_date: pd.Timestamp | None = None

    def run(
        self,
        bars: pd.DataFrame,
        targets: pd.DataFrame,
        corporate_actions: pd.DataFrame | None = None,
    ) -> BacktestResult:
        """兼容内存行情调用；生产长区间应使用 :meth:`run_stream`。"""
        return self.run_stream([bars], targets, corporate_actions)

    def run_stream(
        self,
        daily_bars: Iterable[pd.DataFrame],
        targets: pd.DataFrame,
        corporate_actions: pd.DataFrame | None = None,
    ) -> BacktestResult:
        """逐日推进账户，信号只能影响其后至少一根 bar。"""
        target_scheduler = _TargetScheduler(
            targets,
            self.config.execution.execution_delay_bars,
        )
        actions = _corporate_action_lookup(corporate_actions)
        nav_records: list[dict[str, object]] = []
        position_records: list[dict[str, object]] = []
        saw_market_data = False

        for market, is_final_batch in _with_final_marker(daily_bars):
            validated_market = _validate_bars(market)
            if validated_market.empty:
                continue
            saw_market_data = True
            timestamps = validated_market["timestamp"].drop_duplicates().sort_values()
            final_timestamp = timestamps.iloc[-1] if is_final_batch else None
            self._process_market_batch(
                validated_market,
                target_scheduler,
                actions,
                final_timestamp,
                nav_records,
                position_records,
            )

        if not saw_market_data:
            raise ValueError("回测区间没有可用分钟行情")
        self._cancel_expired_orders()
        nav_frame = pd.DataFrame(nav_records)
        return BacktestResult(
            orders=pd.DataFrame([asdict(order) for order in self.orders]),
            fills=pd.DataFrame([asdict(fill) for fill in self.fills]),
            positions=pd.DataFrame(position_records),
            nav=nav_frame,
            metrics=_calculate_metrics(
                nav_frame,
                self.orders,
                self.fills,
                self.config.account.initial_capital,
            ),
        )

    def _process_market_batch(
        self,
        market: pd.DataFrame,
        target_scheduler: _TargetScheduler,
        actions: dict[pd.Timestamp, list[dict[str, object]]],
        final_timestamp: pd.Timestamp | None,
        nav_records: list[dict[str, object]],
        position_records: list[dict[str, object]],
    ) -> None:
        for timestamp, minute_bars in market.groupby("timestamp", sort=True):
            trading_date = timestamp.tz_localize(None).normalize()
            is_new_trading_date = (
                self._previous_date is None or trading_date != self._previous_date
            )
            if is_new_trading_date:
                self._start_trading_day(timestamp, trading_date, minute_bars, actions)

            bars_by_code = minute_bars.set_index("code", drop=False)
            self.last_prices.update(minute_bars.set_index("code")["close"].to_dict())
            if is_new_trading_date and self.active_target_weights is not None:
                self._submit_rebalance_orders(
                    timestamp,
                    self.active_target_weights,
                    bars_by_code,
                )
            elif (
                self.active_target_weights is not None
                and self._unresolved_target_codes.intersection(bars_by_code.index)
                and not self._has_open_orders()
            ):
                # 股票在信号时点缺 bar、稍后恢复时，不等到下一交易日再下单。
                self._submit_rebalance_orders(
                    timestamp,
                    self.active_target_weights,
                    bars_by_code,
                )

            for target_weights in target_scheduler.activations_at(timestamp):
                self.active_target_weights = target_weights
                self._unresolved_target_codes.clear()
                self._submit_rebalance_orders(timestamp, target_weights, bars_by_code)

            if self.config.account.liquidate_at_end and timestamp == final_timestamp:
                self.active_target_weights = {}
                self._unresolved_target_codes.clear()
                self._submit_rebalance_orders(timestamp, {}, bars_by_code)

            self._match_orders(timestamp, trading_date, bars_by_code)
            if not self._has_open_orders() and not self._unresolved_target_codes:
                self.active_target_weights = None
            self._append_account_records(timestamp, nav_records, position_records)
            self._previous_date = trading_date

    def _start_trading_day(
        self,
        timestamp: pd.Timestamp,
        trading_date: pd.Timestamp,
        minute_bars: pd.DataFrame,
        actions: dict[pd.Timestamp, list[dict[str, object]]],
    ) -> None:
        self._cancel_expired_orders()
        self._apply_corporate_actions(trading_date, actions)
        # 当日第一分钟价格要在重新计算目标股数前进入估值。
        self.last_prices.update(minute_bars.set_index("code")["close"].to_dict())

    def _append_account_records(
        self,
        timestamp: pd.Timestamp,
        nav_records: list[dict[str, object]],
        position_records: list[dict[str, object]],
    ) -> None:
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

    def _submit_rebalance_orders(
        self,
        timestamp: pd.Timestamp,
        target_weights: dict[str, float],
        bars_by_code: pd.DataFrame,
    ) -> None:
        self._cancel_open_orders("replaced_by_new_signal")
        self._unresolved_target_codes.clear()
        nav = self._portfolio_value()
        all_codes = set(target_weights) | set(self.positions)
        candidates: list[tuple[str, str, int]] = []
        for code in sorted(all_codes):
            current_shares = self.positions.get(code, Position()).shares
            target_weight = target_weights.get(code, 0.0)
            reference_price = self._reference_price(code, bars_by_code)
            if reference_price <= 0:
                if current_shares > 0 or target_weight > 0:
                    self._unresolved_target_codes.add(code)
                continue
            target_shares = int(nav * target_weight / reference_price)
            target_shares = (
                target_shares // self.config.execution.lot_size
                * self.config.execution.lot_size
            )
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

    def _reference_price(self, code: str, bars_by_code: pd.DataFrame) -> float:
        if code in bars_by_code.index:
            return float(bars_by_code.loc[code, "vwap"])
        return self.last_prices.get(code, 0.0)

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

            bonus_shares = int(round(original_shares * float(action["share_ratio"])))
            position.add_action_shares(trading_date, bonus_shares)

            rights_ratio = float(action.get("rights_ratio", 0.0))
            if rights_ratio == 0 or self.config.account.rights_issue_policy == "ignore":
                continue
            rights_shares = int(original_shares * rights_ratio)
            rights_cost = rights_shares * float(action.get("rights_price", 0.0))
            if rights_cost > self.cash + 1e-9:
                raise ValueError(
                    f"{trading_date.date()} {code} 配股需要 {rights_cost:.2f}，"
                    f"账户现金仅 {self.cash:.2f}"
                )
            self.cash -= rights_cost
            position.add_action_shares(trading_date, rights_shares)

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


class _TargetScheduler:
    """在流式时间线上按严格晚于信号的 bar 数激活目标。"""

    def __init__(self, targets: pd.DataFrame, delay_bars: int) -> None:
        self.delay_bars = delay_bars
        self.signals = [
            (timestamp, group.set_index("code")["target_weight"].to_dict())
            for timestamp, group in targets.groupby("signal_timestamp", sort=True)
        ]
        self._next_signal_index = 0
        self._waiting: list[tuple[int, dict[str, float]]] = []

    def activations_at(self, timestamp: pd.Timestamp) -> list[dict[str, float]]:
        while self._next_signal_index < len(self.signals):
            signal_timestamp, weights = self.signals[self._next_signal_index]
            if signal_timestamp >= timestamp:
                break
            self._waiting.append((self.delay_bars, weights))
            self._next_signal_index += 1

        activated: list[dict[str, float]] = []
        still_waiting: list[tuple[int, dict[str, float]]] = []
        for remaining_bars, weights in self._waiting:
            remaining_after_current_bar = remaining_bars - 1
            if remaining_after_current_bar == 0:
                activated.append(weights)
            else:
                still_waiting.append((remaining_after_current_bar, weights))
        self._waiting = still_waiting
        return activated


def _with_final_marker(
    daily_bars: Iterable[pd.DataFrame],
) -> Iterable[tuple[pd.DataFrame, bool]]:
    iterator = iter(daily_bars)
    try:
        current = next(iterator)
    except StopIteration:
        return
    for following in iterator:
        yield current, False
        current = following
    yield current, True


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
    for column in ("rights_ratio", "rights_price"):
        if column not in normalized:
            normalized[column] = 0.0
    return {
        date: group.to_dict("records")
        for date, group in normalized.groupby("date", sort=True)
    }


def _calculate_metrics(
    nav: pd.DataFrame,
    orders: list[Order],
    fills: list[Fill],
    initial_capital: float,
) -> dict[str, float]:
    if nav.empty:
        return {}
    series = nav.set_index("timestamp")["nav"]
    daily = series.groupby(series.index.normalize()).last()
    daily_returns = daily.pct_change()
    daily_returns.iloc[0] = daily.iloc[0] / initial_capital - 1
    total_return = series.iloc[-1] / initial_capital - 1
    running_max = pd.concat(
        [pd.Series([initial_capital]), series.reset_index(drop=True)],
        ignore_index=True,
    ).cummax()
    drawdown_values = pd.concat(
        [pd.Series([initial_capital]), series.reset_index(drop=True)],
        ignore_index=True,
    ) / running_max - 1
    annualized_volatility = daily_returns.std(ddof=1) * np.sqrt(252)
    annualized_return = (1 + total_return) ** (252 / max(len(daily), 1)) - 1
    sharpe = 0.0
    if len(daily_returns) > 1 and daily_returns.std(ddof=1) > 0:
        sharpe = daily_returns.mean() / daily_returns.std(ddof=1) * np.sqrt(252)

    requested_shares = sum(order.requested_shares for order in orders)
    filled_shares = sum(fill.shares for fill in fills)
    turnover_notional = sum(fill.notional for fill in fills)
    average_nav = float(series.mean())
    return {
        "initial_nav": float(initial_capital),
        "final_nav": float(series.iloc[-1]),
        "total_return": float(total_return),
        "annualized_return": float(annualized_return),
        "annualized_volatility": float(annualized_volatility),
        "sharpe_ratio": float(sharpe),
        "max_drawdown": float(drawdown_values.min()),
        "turnover_notional": float(turnover_notional),
        "turnover_rate": float(turnover_notional / average_nav) if average_nav > 0 else 0.0,
        "requested_shares": float(requested_shares),
        "filled_shares": float(filled_shares),
        "fill_ratio": float(filled_shares / requested_shares) if requested_shares else 0.0,
        "commission": float(sum(fill.commission for fill in fills)),
        "stamp_duty": float(sum(fill.stamp_duty for fill in fills)),
        "transfer_fee": float(sum(fill.transfer_fee for fill in fills)),
        "transaction_cost": float(sum(fill.total_cost for fill in fills)),
    }
