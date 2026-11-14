"""中证1000沪深 A 股竞价交易委托数量规则（限价、现金多头）。

规则约束**委托数量**；交易所对合法委托的部分成交可以是任意正整数股。
模拟价按股票 0.01 元最小报价单位取向交易人不利方向的价格。
"""

from __future__ import annotations

from dataclasses import dataclass

from src.intraday.targets import normalize_stock_code


@dataclass(frozen=True)
class ShareRules:
    """board 板块；min_order 最低委托量；step 递增股数；max_order 单笔上限。"""

    board: str
    min_buy: int
    buy_step: int
    min_sell: int
    sell_step: int
    max_order: int
    tick: float = 0.01


def share_rules(code: str) -> ShareRules:
    """当前只支持沪深普通A股：主板/创业板/科创板。"""
    code = normalize_stock_code(code)
    digits, exchange = code.split(".")
    if exchange == "SH" and digits.startswith(("688", "689")):
        return ShareRules("star", 200, 1, 200, 1, 100_000)
    if exchange == "SZ" and digits.startswith(("300", "301")):
        return ShareRules("chinext", 100, 100, 100, 100, 300_000)  # 深交所限价委托
    if exchange in {"SH", "SZ"}:
        return ShareRules("main", 100, 100, 100, 100, 1_000_000)
    raise ValueError(f"暂不支持该交易所委托规则: {code}")


def is_legal_order(
    code: str, side: str, shares: int, *, sellable_at_submit: int | None = None,
) -> bool:
    """对完整委托检验；卖出不足最低申报数量仅允许一次卖出全部剩余股份。"""
    rules = share_rules(code)
    if not isinstance(shares, int) or isinstance(shares, bool) or not (0 < shares <= rules.max_order):
        return False
    if side == "buy":
        return shares >= rules.min_buy and (shares - rules.min_buy) % rules.buy_step == 0
    if side != "sell":
        return False
    if sellable_at_submit is not None and shares > sellable_at_submit:
        return False
    if shares < rules.min_sell:
        return sellable_at_submit is not None and shares == sellable_at_submit
    if rules.sell_step == 1:
        return True
    if shares % rules.sell_step == 0:
        return True
    # 送转股或委托部分成交后的零股，随整数手一起一次性卖出；余仓应为整手。
    return (sellable_at_submit is not None
            and sellable_at_submit % rules.sell_step == shares % rules.sell_step
            and (sellable_at_submit - shares) % rules.sell_step == 0)


def planned_order_shares(code: str, side: str, desired: int, held: int = 0) -> int:
    """对目标与实际持仓的差额生成合法委托量，禁止因取整而反向超调。"""
    rules = share_rules(code)
    if desired <= 0:
        return 0
    if side == "buy":
        if desired < rules.min_buy:
            return 0
        return rules.min_buy + ((desired - rules.min_buy) // rules.buy_step) * rules.buy_step
    if side != "sell":
        raise ValueError(f"未知买卖方向: {side}")
    desired = min(desired, held)
    if desired == held:
        return desired
    if desired < rules.min_sell:
        return 0
    if rules.sell_step == 1:
        return desired
    return desired // rules.sell_step * rules.sell_step


def split_legal_orders(code: str, side: str, shares: int, *, sellable: int = 0) -> list[tuple[int, int | None]]:
    """在单笔上限内拆单，并返回每笔数量及用于零股判断的预留后可卖数。"""
    rules = share_rules(code)
    if shares <= 0:
        return []
    pieces: list[tuple[int, int | None]] = []
    left = shares
    available = sellable
    while left:
        qty = min(left, rules.max_order)
        if left > qty and left - qty < (rules.min_buy if side == "buy" else rules.min_sell):
            qty -= (rules.min_buy if side == "buy" else rules.min_sell) - (left - qty)
        if side == "buy" and rules.buy_step > 1:
            qty = qty // rules.buy_step * rules.buy_step
        if side == "sell" and rules.sell_step > 1 and qty != left:
            qty = qty // rules.sell_step * rules.sell_step
        if qty <= 0:
            raise ValueError(f"无法拆分合规委托: {code}, {side}, {shares}")
        reference = available if side == "sell" else None
        if not is_legal_order(code, side, qty, sellable_at_submit=reference):
            raise ValueError(f"非法委托数量: {code} {side} {qty}; 可卖={reference}")
        pieces.append((qty, reference))
        left -= qty
        if side == "sell":
            available -= qty
    return pieces
