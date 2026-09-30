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
    blocked_bars: int = 0
    last_block_reason: str | None = None


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
        normalized_date = pd.Timestamp(trading_date).normalize().tz_localize(None)
        for bought in sorted(self.lots_by_date):
            if enforce_t_plus_one and bought >= normalized_date:
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

    def add_action_shares(self, trading_date: pd.Timestamp, shares: int) -> None:
        """登记送转或配股新增股份；新增股份从事件日开始重新遵守 T+1。"""
        if shares <= 0:
            return
        self.buy(trading_date, shares)


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
        """撮合单根 bar；受限或不足一手时保留订单等待。"""
        if order.status not in {"open", "partially_filled"} or order.remaining_shares <= 0:
            return None
        blocked_reason = self._blocked_reason(order, bar)
        if blocked_reason is not None:
            order.blocked_bars += 1
            order.last_block_reason = blocked_reason
            return None

        capacity = int(float(bar["volume"]) * self.execution.max_participation_rate)
        capacity = _round_down(capacity, self.execution.lot_size)
        available = capacity
        if order.side == "sell":
            available = min(available, sellable_shares)
        shares = min(order.remaining_shares, available)
        shares = _round_down(shares, self.execution.lot_size)
        if shares <= 0:
            order.blocked_bars += 1
            order.last_block_reason = "insufficient_capacity_or_sellable_shares"
            return None

        price = self._execution_price(order.side, bar)
        if order.side == "buy":
            shares = self._affordable_shares(order, shares, price, cash, bar["timestamp"])
        if shares <= 0:
            order.blocked_bars += 1
            order.last_block_reason = "insufficient_cash"
            return None
        return self._build_fill(order, bar["timestamp"], shares, price)

    def _blocked_reason(self, order: Order, bar: pd.Series) -> str | None:
        if "is_suspended" in bar and pd.notna(bar["is_suspended"]):
            if bool(bar["is_suspended"]):
                return "suspended"
        if float(bar["volume"]) <= 0:
            return "zero_volume"
        if self._is_blocked_one_price_bar(order, bar):
            return "one_price_limit"
        return None

    def _execution_price(self, side: str, bar: pd.Series) -> float:
        direction = 1 if side == "buy" else -1
        impacted_price = float(bar["vwap"]) * (
            1 + direction * self.execution.slippage_bps / 10_000
        )
        # 任何真实成交都应落在该分钟已经出现过的价格区间内。
        return min(max(impacted_price, float(bar["low"])), float(bar["high"]))

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
        order.last_block_reason = None
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
        has_limit_up = "limit_up" in bar and pd.notna(bar["limit_up"])
        has_limit_down = "limit_down" in bar and pd.notna(bar["limit_down"])
        if has_limit_up or has_limit_down:
            if order.side == "buy" and has_limit_up:
                return float(bar["close"]) >= float(bar["limit_up"])
            if order.side == "sell" and has_limit_down:
                return float(bar["close"]) <= float(bar["limit_down"])
            return False
        # 没有精确涨跌停参考数据时保持保守，不猜测一字价格的方向。
        return True


def _round_down(shares: int, lot_size: int) -> int:
    return max(0, int(shares) // lot_size * lot_size)
