"""A 股分钟订单撮合、交易约束和费用计算。"""

from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd

from src.intraday.config import CostConfig, ExecutionConfig


@dataclass
class Order:
    """记录一个只在当日有效、可跨分钟部分成交的订单。"""

    order_id: int
    created_at: pd.Timestamp
    code: str
    side: str
    requested_shares: int
    remaining_shares: int
    status: str = "open"
    filled_shares: int = 0
    filled_notional: float = 0.0
    commission_charged: float = 0.0
    reject_reason: str | None = None


@dataclass(frozen=True)
class Fill:
    """记录一次分钟 bar 上的实际成交及分项费用。"""

    order_id: int
    timestamp: pd.Timestamp
    code: str
    side: str
    shares: int
    price: float
    notional: float
    commission: float
    stamp_duty: float
    transfer_fee: float
    total_cost: float


@dataclass
class Position:
    """记录总持仓及按买入日冻结的 T+1 股份。"""

    shares: int = 0
    lots_by_date: dict[pd.Timestamp, int] = field(default_factory=dict)

    def sellable_shares(self, trading_date: pd.Timestamp, enforce_t_plus_one: bool) -> int:
        if not enforce_t_plus_one:
            return self.shares
        date = pd.Timestamp(trading_date).normalize().tz_localize(None)
        return sum(shares for bought, shares in self.lots_by_date.items() if bought < date)

    def buy(self, trading_date: pd.Timestamp, shares: int) -> None:
        date = pd.Timestamp(trading_date).normalize().tz_localize(None)
        self.shares += shares
        self.lots_by_date[date] = self.lots_by_date.get(date, 0) + shares

    def sell(self, trading_date: pd.Timestamp, shares: int, enforce_t_plus_one: bool) -> None:
        if shares > self.sellable_shares(trading_date, enforce_t_plus_one):
            raise ValueError("卖出数量超过可卖持仓")
        remaining = shares
        for bought in sorted(self.lots_by_date):
            if enforce_t_plus_one and bought >= pd.Timestamp(trading_date).normalize().tz_localize(None):
                continue
            consumed = min(remaining, self.lots_by_date[bought])
            self.lots_by_date[bought] -= consumed
            remaining -= consumed
            if remaining == 0:
                break
        self.lots_by_date = {
            bought: quantity for bought, quantity in self.lots_by_date.items() if quantity > 0
        }
        self.shares -= shares


class ExecutionModel:
    """使用 bar VWAP、容量上限和不利滑点撮合订单。"""

    def __init__(self, execution: ExecutionConfig, costs: CostConfig) -> None:
        self.execution = execution
        self.costs = costs

    def match(
        self,
        order: Order,
        bar: pd.Series,
        cash: float,
        sellable_shares: int,
    ) -> Fill | None:
        """撮合单根 bar；无流动性、受限或不足一手时保留订单等待。"""
        if order.status not in {"open", "partially_filled"} or order.remaining_shares <= 0:
            return None
        if float(bar["volume"]) <= 0 or self._is_blocked_one_price_bar(order, bar):
            return None

        capacity = int(float(bar["volume"]) * self.execution.max_participation_rate)
        capacity = _round_down(capacity, self.execution.lot_size)
        available = capacity
        if order.side == "sell":
            available = min(available, sellable_shares)
        shares = min(order.remaining_shares, available)
        shares = _round_down(shares, self.execution.lot_size)
        if shares <= 0:
            return None

        price = self._execution_price(order.side, float(bar["vwap"]))
        if order.side == "buy":
            shares = self._affordable_shares(order, shares, price, cash, bar["timestamp"])
        if shares <= 0:
            return None
        return self._build_fill(order, bar["timestamp"], shares, price)

    def _execution_price(self, side: str, vwap: float) -> float:
        direction = 1 if side == "buy" else -1
        return vwap * (1 + direction * self.execution.slippage_bps / 10_000)

    def _affordable_shares(
        self,
        order: Order,
        candidate_shares: int,
        price: float,
        cash: float,
        timestamp: pd.Timestamp,
    ) -> int:
        shares = candidate_shares
        while shares > 0:
            preview = self._preview_fill(order, timestamp, shares, price)
            if preview.notional + preview.total_cost <= cash + 1e-9:
                return shares
            shares -= self.execution.lot_size
        return 0

    def _build_fill(
        self,
        order: Order,
        timestamp: pd.Timestamp,
        shares: int,
        price: float,
    ) -> Fill:
        fill = self._preview_fill(order, timestamp, shares, price)
        order.remaining_shares -= shares
        order.filled_shares += shares
        order.filled_notional += fill.notional
        order.commission_charged += fill.commission
        if order.remaining_shares == 0:
            order.status = "filled"
        else:
            order.status = "partially_filled"
        return fill

    def _preview_fill(
        self,
        order: Order,
        timestamp: pd.Timestamp,
        shares: int,
        price: float,
    ) -> Fill:
        notional = shares * price
        cumulative_notional = order.filled_notional + notional
        cumulative_commission = max(
            cumulative_notional * self.costs.commission_rate,
            self.costs.minimum_commission,
        )
        commission = max(0.0, cumulative_commission - order.commission_charged)
        stamp_duty = 0.0
        if order.side == "sell":
            boundary = pd.Timestamp("2023-08-28", tz=timestamp.tz)
            stamp_rate = (
                self.costs.stamp_duty_rate_from_20230828
                if timestamp >= boundary
                else self.costs.stamp_duty_rate_before_20230828
            )
            stamp_duty = notional * stamp_rate
        transfer_fee = notional * self.costs.transfer_fee_rate
        total_cost = commission + stamp_duty + transfer_fee
        return Fill(
            order_id=order.order_id,
            timestamp=timestamp,
            code=order.code,
            side=order.side,
            shares=shares,
            price=price,
            notional=notional,
            commission=commission,
            stamp_duty=stamp_duty,
            transfer_fee=transfer_fee,
            total_cost=total_cost,
        )

    def _is_blocked_one_price_bar(self, order: Order, bar: pd.Series) -> bool:
        if not self.execution.block_one_price_limit:
            return False
        is_one_price = float(bar["high"]) == float(bar["low"])
        if not is_one_price:
            return False
        if "limit_up" in bar and pd.notna(bar["limit_up"]):
            if order.side == "buy" and float(bar["close"]) >= float(bar["limit_up"]):
                return True
        if "limit_down" in bar and pd.notna(bar["limit_down"]):
            if order.side == "sell" and float(bar["close"]) <= float(bar["limit_down"]):
                return True
        return "limit_up" not in bar and "limit_down" not in bar


def _round_down(shares: int, lot_size: int) -> int:
    return max(0, int(shares) // lot_size * lot_size)
