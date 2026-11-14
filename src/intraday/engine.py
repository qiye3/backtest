"""把目标仓位、分钟行情和真实成交约束串成账户回测。"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import asdict, dataclass

import numpy as np
import pandas as pd

from src.intraday.config import MinuteBacktestConfig
from src.intraday.execution import ExecutionModel, Fill, Order, Position
from src.intraday.market_rules import planned_order_shares, share_rules, split_legal_orders


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
        # 只扫描在途订单，历史订单仍保存在 orders 供结果审计。
        self._open_orders: dict[int, Order] = {}
        self.fills: list[Fill] = []
        self.last_prices: dict[str, float] = {}
        self._last_price_date: dict[str, pd.Timestamp] = {}
        self.active_target_weights: dict[str, float] | None = None
        self._unresolved_target_codes: set[str] = set()
        self._next_order_id = 1
        self._previous_date: pd.Timestamp | None = None
        self._fixed_pending_codes: set[str] = set()
        self._fixed_retry_days_used = 0
        self._fixed_execute_today = False
        self._fixed_orders_submitted = False
        self._fixed_window_closed = False
        self._last_applied_signal_timestamp: pd.Timestamp | None = None

    def export_state(self) -> dict[str, object]:
        """导出日终可续跑账户状态；未成交订单当日到期，不跨日携带。"""
        if self._open_orders:
            raise RuntimeError("必须在当日成交窗口关闭后才能保存账户状态")
        return {
            "version": 1,
            "previous_date": _state_date(self._previous_date),
            "cash": float(self.cash),
            "positions": {
                code: {
                    "shares": int(position.shares),
                    "lots_by_date": {str(day.date()): int(quantity)
                                     for day, quantity in position.lots_by_date.items()},
                }
                for code, position in sorted(self.positions.items()) if position.shares
            },
            "last_prices": {code: float(price) for code, price in self.last_prices.items()},
            "last_price_dates": {
                code: _state_date(day) for code, day in self._last_price_date.items()
            },
            "active_target_weights": self.active_target_weights,
            "pending_target_codes": sorted(self._fixed_pending_codes),
            "retry_days_used": self._fixed_retry_days_used,
            "last_applied_signal_timestamp": (
                self._last_applied_signal_timestamp.isoformat()
                if self._last_applied_signal_timestamp is not None else None
            ),
            "next_order_id": self._next_order_id,
        }

    def import_state(self, state: dict[str, object]) -> None:
        """恢复前一日账户状态。仅允许在新创建的引擎中恢复。"""
        if self._previous_date is not None or self.orders or self.fills:
            raise ValueError("账户已经开始运行，不能再导入旧状态")
        if state.get("version") != 1:
            raise ValueError("不兼容的账户状态版本")
        self.cash = float(state["cash"])
        self.positions = {}
        for code, raw in state["positions"].items():
            lots = {pd.Timestamp(day): int(shares)
                    for day, shares in raw["lots_by_date"].items()}
            position = Position(shares=int(raw["shares"]), lots_by_date=lots)
            if sum(lots.values()) != position.shares:
                raise ValueError(f"{code} 账户状态中的持仓股数与买入批次不一致")
            self.positions[code] = position
        self.last_prices = {str(code): float(price)
                            for code, price in state["last_prices"].items()}
        self._last_price_date = {
            str(code): pd.Timestamp(day) for code, day in state["last_price_dates"].items()
        }
        self.active_target_weights = (
            None if state["active_target_weights"] is None else
            {str(code): float(weight)
             for code, weight in state["active_target_weights"].items()}
        )
        self._fixed_pending_codes = set(state["pending_target_codes"])
        self._fixed_retry_days_used = int(state["retry_days_used"])
        self._last_applied_signal_timestamp = (
            pd.Timestamp(state["last_applied_signal_timestamp"])
            if state["last_applied_signal_timestamp"] else None
        )
        self._next_order_id = int(state["next_order_id"])
        self._previous_date = (
            pd.Timestamp(state["previous_date"]) if state["previous_date"] else None
        )

    def run(
        self,
        bars: pd.DataFrame,
        targets: pd.DataFrame,
        corporate_actions: pd.DataFrame | None = None,
        *, record_frequency: str = "minute",
    ) -> BacktestResult:
        """兼容内存行情调用；正式分层可只保存日终账户快照。"""
        return self.run_stream([bars], targets, corporate_actions, record_frequency=record_frequency)

    def run_stream(
        self,
        daily_bars: Iterable[pd.DataFrame],
        targets: pd.DataFrame,
        corporate_actions: pd.DataFrame | None = None,
        *, record_frequency: str = "minute",
    ) -> BacktestResult:
        """逐日推进账户；固定窗口模式只允许此前交易日的信号执行。"""
        if record_frequency not in {"minute", "daily"}:
            raise ValueError("record_frequency 仅支持 minute 或 daily")
        scheduler = _FixedDayTargetScheduler(
            targets, after_timestamp=self._last_applied_signal_timestamp,
        )
        actions = _corporate_action_lookup(corporate_actions)
        nav_records: list[dict[str, object]] = []
        position_records: list[dict[str, object]] = []
        saw_market_data = False

        for market in daily_bars:
            validated_market = _validate_bars(market)
            if validated_market.empty:
                continue
            saw_market_data = True
            self._process_market_batch(
                validated_market,
                scheduler,
                actions,
                nav_records,
                position_records,
                record_frequency=record_frequency,
            )

        if not saw_market_data:
            raise ValueError("回测区间没有可用分钟行情")
        self._close_fixed_window()
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
        scheduler: _FixedDayTargetScheduler,
        actions: dict[pd.Timestamp, list[dict[str, object]]],
        nav_records: list[dict[str, object]],
        position_records: list[dict[str, object]],
        *, record_frequency: str,
    ) -> None:
        # 日终记录不影响逐分钟的订单撮合，避免构建大量无用的持仓快照。
        if record_frequency == "daily":
            dates = market["timestamp"].dt.tz_localize(None).dt.normalize()
            last_times = market.groupby(dates)["timestamp"].max().to_dict()
        else:
            last_times = {}
        for timestamp, minute_bars in market.groupby("timestamp", sort=True):
            trading_date = timestamp.tz_localize(None).normalize()
            if self._previous_date is None or trading_date != self._previous_date:
                if self._previous_date is not None:
                    self._close_fixed_window()
                self._start_trading_day(trading_date, actions)
                self._start_fixed_day(trading_date, scheduler)

            bars_by_code = minute_bars.set_index("code", drop=False)
            # 必须先处理委托，再更新当前分钟价格，杜绝用当前未完成的 bar 下单。
            self._process_fixed_minute(timestamp, trading_date, bars_by_code)
            self._observe_prices(trading_date, minute_bars)
            if record_frequency == "minute" or timestamp == last_times.get(trading_date):
                self._append_account_records(timestamp, nav_records, position_records)
            self._previous_date = trading_date

    def _observe_prices(self, trading_date: pd.Timestamp, bars: pd.DataFrame) -> None:
        self.last_prices.update(bars.set_index("code")["close"].to_dict())
        self._last_price_date.update({code: trading_date for code in bars["code"]})

    def _start_fixed_day(
        self, trading_date: pd.Timestamp, scheduler: _FixedDayTargetScheduler,
    ) -> None:
        activation = scheduler.activation_for_day(trading_date)
        new_weights = activation[1] if activation is not None else None
        if activation is not None:
            self._last_applied_signal_timestamp = activation[0]
        self._fixed_orders_submitted = False
        self._fixed_window_closed = False
        if new_weights is not None:
            self.active_target_weights = new_weights
            self._fixed_pending_codes = set(new_weights) | {
                code for code, position in self.positions.items() if position.shares > 0
            }
            self._fixed_retry_days_used = 0
            self._fixed_execute_today = bool(self._fixed_pending_codes)
        elif (
            self._fixed_pending_codes
            and self._fixed_retry_days_used < self.config.execution.retry_unfilled_days
        ):
            self._fixed_retry_days_used += 1
            self._fixed_execute_today = True
        else:
            self._fixed_execute_today = False
            self._fixed_pending_codes.clear()

    def _process_fixed_minute(
        self, timestamp: pd.Timestamp, trading_date: pd.Timestamp,
        bars_by_code: pd.DataFrame,
    ) -> None:
        clock = timestamp.strftime("%H:%M:%S")
        setting = self.config.execution
        if clock > setting.window_end:
            self._close_fixed_window()
            return
        if (
            self._fixed_execute_today and not self._fixed_orders_submitted
            and setting.order_time <= clock <= setting.window_end
        ):
            assert self.active_target_weights is not None
            # 即使整市场10:00这一根bar缺失，也记录预定的10:00发单时刻。
            scheduled_at = pd.Timestamp(
                f"{trading_date.date()} {setting.order_time}", tz=timestamp.tz,
            )
            self._submit_rebalance_orders(
                scheduled_at, self.active_target_weights, bars_by_code,
                only_codes=self._fixed_pending_codes, use_previous_prices=True,
            )
            self._fixed_orders_submitted = True
        if setting.window_start <= clock <= setting.window_end:
            self._match_orders(timestamp, trading_date, bars_by_code)

    def _close_fixed_window(self) -> None:
        if self._fixed_window_closed:
            return
        if self._fixed_execute_today:
            self._fixed_pending_codes = self._unresolved_target_codes | {
                order.code for order in self._open_orders.values()
            }
        self._cancel_open_orders("window_expired")
        self._unresolved_target_codes.clear()
        self._fixed_window_closed = True

    def _start_trading_day(
        self,
        trading_date: pd.Timestamp,
        actions: dict[pd.Timestamp, list[dict[str, object]]],
    ) -> None:
        self._cancel_open_orders("day_expired")
        self._apply_corporate_actions(trading_date, actions)

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
        *,
        only_codes: set[str] | None = None,
        use_previous_prices: bool = False,
    ) -> None:
        self._cancel_open_orders("replaced_by_new_signal")
        self._unresolved_target_codes.clear()
        nav = self._portfolio_value()
        all_codes = set(target_weights) | set(self.positions)
        order_date = timestamp.tz_localize(None).normalize()
        if only_codes is not None:
            all_codes &= only_codes
        candidates: list[tuple[str, str, int]] = []
        for code in sorted(all_codes):
            current_shares = self.positions.get(code, Position()).shares
            target_weight = target_weights.get(code, 0.0)
            if use_previous_prices:
                # 09:31 可用前一交易日的已知收盘价；其他时刻需有当日此前成交的报价。
                has_today_quote = self._last_price_date.get(code) == order_date
                has_previous_close = (
                    self._last_price_date.get(code) is not None
                    and self._last_price_date[code] < order_date
                )
                reference_price = (
                    self.last_prices.get(code, 0.0)
                    if has_today_quote or (timestamp.strftime("%H:%M:%S") == "09:31:00" and has_previous_close)
                    else 0.0
                )
            else:
                reference_price = self._reference_price(code, bars_by_code)
            if not np.isfinite(reference_price) or reference_price <= 0:
                if current_shares > 0 or target_weight > 0:
                    if use_previous_prices and timestamp.strftime("%H:%M:%S") == "09:31:00":
                        raise ValueError(f"{order_date.date()} 09:31 发单缺少 {code} 前日已知收盘价")
                    self._unresolved_target_codes.add(code)
                continue
            target_shares = int(nav * target_weight / reference_price)
            difference = target_shares - current_shares
            if difference == 0:
                continue
            side = "buy" if difference > 0 else "sell"
            # 约束的是交易所的原始委托股数，持仓本身允许部分成交产生零股。
            shares = planned_order_shares(code, side, abs(difference), held=current_shares)
            if shares:
                candidates.append((side, code, shares))
        for side, code, shares in sorted(
            candidates, key=lambda value: (value[0] != "sell", value[1])
        ):
            holding = self.positions.get(code, Position())
            sellable = holding.sellable_shares(order_date, self.config.execution.enforce_t_plus_one)
            if side == "sell":
                # 已持仓但当日不可卖的数量不允许进入委托。
                shares = planned_order_shares(code, "sell", min(shares, sellable), held=sellable)
            if shares <= 0:
                continue
            for quantity, reserved_sellable in split_legal_orders(
                code, side, shares, sellable=sellable,
            ):
                order = Order(
                    order_id=self._next_order_id,
                    created_at=timestamp,
                    code=code,
                    side=side,
                    requested_shares=quantity,
                    remaining_shares=quantity,
                    sellable_at_submit=reserved_sellable,
                )
                self.orders.append(order)
                self._open_orders[order.order_id] = order
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
        active_orders = [
            order for order in self._open_orders.values()
            if order.created_at.date() == timestamp.date()
            and order.code in bars_by_code.index
        ]
        # 一个标的一根分钟K线总成交量参与率只允许使用一次，拆单不得放大容量。
        remaining_capacity = {
            code: int(max(0, float(bar["volume"])) * self.config.execution.max_participation_rate)
            for code, bar in bars_by_code.iterrows()
        }
        buy_cash_at_bar_start = max(0.0, self.cash)
        for order in (order for order in active_orders if order.side == "sell"):
            position = self.positions.setdefault(order.code, Position())
            sellable = position.sellable_shares(
                trading_date, self.config.execution.enforce_t_plus_one,
            )
            fill = self.execution.match(
                order, bars_by_code.loc[order.code], self.cash, sellable,
                capacity_override=remaining_capacity[order.code],
            )
            if fill is None:
                continue
            self.fills.append(fill)
            remaining_capacity[order.code] -= fill.shares
            self.cash += fill.notional - fill.total_cost
            position.sell(trading_date, fill.shares, self.config.execution.enforce_t_plus_one)
            if order.status == "filled":
                self._open_orders.pop(order.order_id)

        buys = [order for order in active_orders if order.side == "buy"]
        budgets = self._allocate_buy_budgets(
            buys, bars_by_code, buy_cash_at_bar_start, remaining_capacity,
        )
        for order in buys:
            fill = self.execution.match(
                order, bars_by_code.loc[order.code],
                min(self.cash, budgets.get(order.order_id, 0.0)), 0,
                capacity_override=remaining_capacity[order.code],
            )
            if fill is None:
                continue
            self.fills.append(fill)
            remaining_capacity[order.code] -= fill.shares
            self.cash -= fill.notional + fill.total_cost
            self.positions.setdefault(order.code, Position()).buy(trading_date, fill.shares)
            if order.status == "filled":
                self._open_orders.pop(order.order_id)

    def _allocate_buy_budgets(
        self, buys: list[Order], bars_by_code: pd.DataFrame, cash: float,
        remaining_capacity: dict[str, int] | None = None,
    ) -> dict[int, float]:
        """先按需求比例分配，再分配整数股余款，不按股票代码优先耗尽现金。"""
        quotes: dict[int, tuple[Order, int, float, float, pd.Timestamp]] = {}
        if remaining_capacity is None:
            remaining_capacity = {
                code: int(float(bar["volume"]) * self.config.execution.max_participation_rate)
                for code, bar in bars_by_code.iterrows()
            }
        available_capacity = remaining_capacity.copy()
        for order in buys:
            bar = bars_by_code.loc[order.code]
            quote = self.execution.quote_buy(
                order, bar, capacity_override=available_capacity[order.code],
            )
            if quote is None:
                continue
            shares, price = quote
            available_capacity[order.code] -= shares
            required = self.execution.buy_cost(order, shares, price, bar["timestamp"])
            quotes[order.order_id] = (order, shares, price, required, bar["timestamp"])

        total_required = sum(quote[3] for quote in quotes.values())
        if not quotes or cash <= 0:
            return {}
        if total_required <= cash + 1e-9:
            return {order_id: quote[3] for order_id, quote in quotes.items()}

        allocations: dict[int, int] = {}
        costs: dict[int, float] = {}
        for order_id, (order, available, price, required, timestamp) in quotes.items():
            budget = cash * required / total_required
            shares = self.execution.affordable_buy_shares(
                order, available, price, budget, timestamp,
            )
            allocations[order_id] = shares
            costs[order_id] = self.execution.buy_cost(order, shares, price, timestamp)

        cash_left = cash - sum(costs.values())
        # 每笔只补配整股，小余款不会改变原始委托数量的合法性。
        while True:
            candidates = []
            for order_id, (order, available, price, required, timestamp) in quotes.items():
                if allocations[order_id] >= available:
                    continue
                next_cost = self.execution.buy_cost(
                    order, allocations[order_id] + 1, price, timestamp,
                )
                incremental = next_cost - costs[order_id]
                if incremental > cash_left + 1e-9:
                    continue
                target_budget = cash * required / total_required
                # 缺口比例最大的买单优先；平局按代码排序。
                shortage = (target_budget - costs[order_id]) / max(incremental, 1e-12)
                candidates.append((-shortage, order.code, order_id, next_cost, incremental))
            if not candidates:
                break
            _, _, order_id, next_cost, increment = min(candidates)
            allocations[order_id] += 1
            costs[order_id] = next_cost
            cash_left -= increment
        return costs

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
        market_value = 0.0
        for code, position in self.positions.items():
            if position.shares <= 0:
                continue
            price = self.last_prices.get(code)
            if price is None or not np.isfinite(price) or price <= 0:
                raise ValueError(f"持仓 {code} 缺少可用估值价格，不能将持仓按零估值")
            market_value += position.shares * price
        return self.cash + market_value

    def _cancel_open_orders(self, reason: str) -> None:
        for order in self._open_orders.values():
            order.status = "cancelled"
            order.reject_reason = reason
        self._open_orders.clear()





class _FixedDayTargetScheduler:
    """只在信号日期之后的交易日激活日频目标，避免当天收盘信号回看成交。"""

    def __init__(
        self, targets: pd.DataFrame, after_timestamp: pd.Timestamp | None = None,
    ) -> None:
        self.signals = [
            (timestamp, group.set_index("code")["target_weight"].to_dict())
            for timestamp, group in targets.groupby("signal_timestamp", sort=True)
            if after_timestamp is None or timestamp > after_timestamp
        ]
        self.next_index = 0

    def activation_for_day(
        self, trading_date: pd.Timestamp,
    ) -> tuple[pd.Timestamp, dict[str, float]] | None:
        latest = None
        while self.next_index < len(self.signals):
            timestamp, weights = self.signals[self.next_index]
            if timestamp.tz_localize(None).normalize() >= trading_date:
                break
            latest = (timestamp, weights)
            self.next_index += 1
        return latest


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
    average_nav = float(daily.mean())
    return {
        "initial_nav": float(initial_capital),
        "initial_unit_nav": 1.0,
        "final_unit_nav": float(daily.iloc[-1] / initial_capital),
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


def _state_date(value: pd.Timestamp | None) -> str | None:
    return None if value is None else str(value.date())
