"""A 股分钟订单撮合、交易约束和费用计算。"""

from __future__ import annotations

from dataclasses import dataclass, field
import math

import pandas as pd

from src.intraday.config import CostConfig, ExecutionConfig
from src.intraday.market_rules import is_legal_order, share_rules


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
    sellable_at_submit: int | None = None


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
    """使用分钟 VWAP、成交量容量、涨跌停方向和不利滑点撮合订单。"""

    def __init__(self, execution: ExecutionConfig, costs: CostConfig) -> None:
        self.execution = execution
        self.costs = costs

    def match(
        self,
        order: Order,
        bar: pd.Series,
        cash: float,
        sellable_shares: int,
        *,
        capacity_override: int | None = None,
    ) -> Fill | None:
        """完整委托必须合法；成交数量可小于最小委托量（交易所部分成交）。"""
        if order.status not in {"open", "partially_filled"} or order.remaining_shares <= 0:
            return None
        # 委托可能直接由外部实盘适配器创建，不能只依赖 engine 的拆单校验。
        # 订单总量须合法；随后每分钟的部分成交数量不再按整手取整。
        if order.filled_shares == 0 and not is_legal_order(
            order.code,
            order.side,
            order.requested_shares,
            sellable_at_submit=(
                order.sellable_at_submit
                if order.sellable_at_submit is not None
                else sellable_shares if order.side == "sell" else None
            ),
        ):
            raise ValueError(
                f"非法 A 股委托: {order.code} {order.side} {order.requested_shares} 股"
            )
        blocked_reason = self._blocked_reason(order, bar)
        if blocked_reason is not None:
            order.blocked_bars += 1
            order.last_block_reason = blocked_reason
            return None

        shares = self._candidate_shares(order, bar, sellable_shares, capacity_override)
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

    def quote_buy(
        self, order: Order, bar: pd.Series, *, capacity_override: int | None = None,
    ) -> tuple[int, float] | None:
        """非破坏性报价：合法买单的部分成交可以为任意整数股。"""
        if order.side != "buy" or order.status not in {"open", "partially_filled"}:
            return None
        if self._blocked_reason(order, bar) is not None:
            return None
        shares = self._candidate_shares(order, bar, 0, capacity_override)
        if shares <= 0:
            return None
        return shares, self._execution_price("buy", bar)

    def buy_cost(self, order: Order, shares: int, price: float, timestamp: pd.Timestamp) -> float:
        """包含该订单累计最低佣金影响的预计现金支出；不改变订单。"""
        if shares <= 0:
            return 0.0
        preview = self._preview_fill(order, timestamp, shares, price)
        return preview.notional + preview.total_cost

    def affordable_buy_shares(
        self, order: Order, candidate_shares: int, price: float, cash: float,
        timestamp: pd.Timestamp,
    ) -> int:
        """买单在给定预算中可成交的股数（部分成交不要求整手）。"""
        return self._affordable_shares(order, candidate_shares, price, cash, timestamp)

    def _candidate_shares(
        self, order: Order, bar: pd.Series, sellable: int,
        capacity_override: int | None = None,
    ) -> int:
        capacity = (int(float(bar["volume"]) * self.execution.max_participation_rate)
                    if capacity_override is None else capacity_override)
        # 最小申报数量已在订单创建时检查；真实成交可能不足100或200股。
        if order.side == "sell":
            return max(0, min(order.remaining_shares, capacity, sellable))
        return max(0, min(order.remaining_shares, capacity))

    def _blocked_reason(self, order: Order, bar: pd.Series) -> str | None:
        if self.execution.require_daily_limit_data and not (
            _valid_limit(bar, "limit_up") and _valid_limit(bar, "limit_down")
        ):
            return "missing_daily_limit_data"
        if "is_suspended" in bar and pd.notna(bar["is_suspended"]):
            if bool(bar["is_suspended"]):
                return "suspended"
        if any(
            not math.isfinite(float(bar[name])) or float(bar[name]) <= 0
            for name in ("vwap", "close", "high", "low")
        ):
            return "invalid_price"
        if not math.isfinite(float(bar["volume"])) or float(bar["volume"]) <= 0:
            return "zero_volume"
        if order.side == "buy" and _valid_limit(bar, "limit_up"):
            if float(bar["close"]) >= float(bar["limit_up"]) - 1e-6:
                return "buy_at_limit_up"
        if order.side == "sell" and _valid_limit(bar, "limit_down"):
            if float(bar["close"]) <= float(bar["limit_down"]) + 1e-6:
                return "sell_at_limit_down"
        missing_direction_limit = not _valid_limit(
            bar, "limit_up" if order.side == "buy" else "limit_down"
        )
        if (
            self.execution.block_one_price_limit
            and missing_direction_limit
            and float(bar["high"]) == float(bar["low"])
        ):
            # 缺少日度涨跌停价时，无法辨别一字价是否封板，双向保守拦截。
            return "one_price_without_limit_data"
        return None

    def _execution_price(self, side: str, bar: pd.Series) -> float:
        direction = 1 if side == "buy" else -1
        impacted_price = float(bar["vwap"]) * (
            1 + direction * self.execution.slippage_bps / 10_000
        )
        if _valid_limit(bar, "limit_up"):
            impacted_price = min(impacted_price, float(bar["limit_up"]))
        if _valid_limit(bar, "limit_down"):
            impacted_price = max(impacted_price, float(bar["limit_down"]))
        # A 股 0.01 元报价单位，买入向上取整、卖出向下取整（对交易人不利）。
        # 如日涨跌停价本身有效，则也位于合法价格网格上。
        tick = 0.01
        if side == "buy":
            cents = math.ceil(impacted_price / tick - 1e-9)
        else:
            cents = math.floor(impacted_price / tick + 1e-9)
        # 测试或数据源若给出非tick对齐的涨跌停价，也必须在合法价格网格内。
        if _valid_limit(bar, "limit_up"):
            cents = min(cents, math.floor(float(bar["limit_up"]) / tick + 1e-9))
        if _valid_limit(bar, "limit_down"):
            cents = max(cents, math.ceil(float(bar["limit_down"]) / tick - 1e-9))
        if cents <= 0:
            raise ValueError("有效委托价格必须为正")
        return round(cents * tick, 2)

    def _affordable_shares(
        self,
        order: Order,
        candidate_shares: int,
        price: float,
        cash: float,
        timestamp: pd.Timestamp,
    ) -> int:
        # 佣金含最低收费，二分查找确保费用后现金非负。
        low, high = 0, max(0, candidate_shares)
        while low < high:
            mid = (low + high + 1) // 2
            preview = self._preview_fill(order, timestamp, mid, price)
            if preview.notional + preview.total_cost <= cash + 1e-9:
                low = mid
            else:
                high = mid - 1
        return low

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



def _valid_limit(bar: pd.Series, name: str) -> bool:
    return (
        name in bar and pd.notna(bar[name])
        and math.isfinite(float(bar[name])) and float(bar[name]) > 0
    )
