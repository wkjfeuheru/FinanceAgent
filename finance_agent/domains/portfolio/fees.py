"""模拟交易的费率解析与费用计算。

``finance.products`` 的两个费率列编码不同，但都表示"百分比数字"：

- ``subscription_fee`` 是 ``double precision``：``1.5`` 表示 1.5%；
- ``redemption_fee`` 是 ``varchar(64)``：``'0.5%'`` 表示 0.5%，``'0'`` 表示免费。

``to_rate`` 把两种编码统一折算为**小数费率**（1.5% -> ``0.015``）。费率为
``None``/空串时返回 ``None`` —— 由调用方登记 ``fee_unavailable:*`` 限制项，
不静默按 0 处理。
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

#: 基金份额保留两位小数（与代销渠道一致）。
SHARE_PRECISION = 2


def to_rate(value: Any) -> float | None:
    """把百分比编码统一折成小数费率；未披露返回 ``None``。"""
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value) / 100.0
    text = str(value).strip()
    if not text:
        return None
    if text.endswith("%"):
        text = text[:-1].strip()
        if not text:
            return None
    try:
        rate = float(text)
    except ValueError:
        return None
    if not math.isfinite(rate):
        return None
    return rate / 100.0


def round_shares(shares: float) -> float:
    """份额向下取整到两位小数。

    向下而非四舍五入：申购时先按金额算份额，向上取整会让实际扣款超过用户
    申请金额，凭空多扣钱。

    加一个极小 epsilon 吸收二进制浮点表示误差：已经是两位小数的值（例如
    ``9852.21``）在乘 100 后可能落到 ``985220.9999999999``，直接 floor 会把它
    错误地砍到 ``9852.20``。epsilon 远小于 0.01 的最小份额单位，因此不会把
    ``0.999`` 这类真实的向下取整变成进位。
    """
    if shares <= 0:
        return 0.0
    scaled = shares * 10**SHARE_PRECISION
    return math.floor(scaled + 1e-9) / 10**SHARE_PRECISION


def round_money(amount: float) -> float:
    """金额保留两位小数。"""
    return round(amount + 0.0, 2)


@dataclass(frozen=True)
class SubscriptionBreakdown:
    """一笔申购的资金拆解（外扣法）。"""

    fee_rate: float
    fee: float
    shares: float
    invested: float
    cash_out: float
    limitations: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class RedemptionBreakdown:
    """一笔赎回的资金拆解。"""

    fee_rate: float
    fee: float
    gross: float
    cash_in: float
    limitations: list[str] = field(default_factory=list)


def subscription_by_amount(
    amount: float, nav: float, fee_rate: float | None, *, field_name: str = "subscription_fee",
) -> SubscriptionBreakdown:
    """按申购金额计算费用与份额（外扣法）。

    外扣法：``净申购金额 = 申购金额 / (1 + 费率)``，``申购费用 = 申购金额 - 净申购金额``。
    份额按两位小数向下取整后**反算实际投入**，因此 ``cash_out <= amount``，
    不会出现扣款超过申请金额的情况。
    """
    rate = 0.0 if fee_rate is None else fee_rate
    limitations: list[str] = []
    if fee_rate is None:
        limitations.append(f"fee_unavailable:{field_name}")
    net_invested = amount / (1.0 + rate) if rate else amount
    fee = round_money(amount - net_invested)
    shares = round_shares(net_invested / nav)
    invested = round_money(shares * nav)
    return SubscriptionBreakdown(
        fee_rate=rate,
        fee=fee,
        shares=shares,
        invested=invested,
        cash_out=round_money(invested + fee),
        limitations=limitations,
    )


def subscription_by_shares(
    shares: float, nav: float, fee_rate: float | None, *, field_name: str = "subscription_fee",
) -> SubscriptionBreakdown:
    """按申购份额计算费用与扣款（份额已知时按比例前收费）。"""
    rate = 0.0 if fee_rate is None else fee_rate
    limitations: list[str] = []
    if fee_rate is None:
        limitations.append(f"fee_unavailable:{field_name}")
    gross = round_money(shares * nav)
    fee = round_money(gross * rate)
    return SubscriptionBreakdown(
        fee_rate=rate,
        fee=fee,
        shares=round_shares(shares),
        invested=gross,
        cash_out=round_money(gross + fee),
        limitations=limitations,
    )


def redemption(
    shares: float, nav: float, fee_rate: float | None, *, field_name: str = "redemption_fee",
) -> RedemptionBreakdown:
    """按赎回份额计算赎回费与到账金额。"""
    rate = 0.0 if fee_rate is None else fee_rate
    limitations: list[str] = []
    if fee_rate is None:
        limitations.append(f"fee_unavailable:{field_name}")
    gross = round_money(shares * nav)
    fee = round_money(gross * rate)
    return RedemptionBreakdown(
        fee_rate=rate,
        fee=fee,
        gross=gross,
        cash_in=round_money(gross - fee),
        limitations=limitations,
    )


__all__ = [
    "RedemptionBreakdown",
    "SHARE_PRECISION",
    "SubscriptionBreakdown",
    "redemption",
    "round_money",
    "round_shares",
    "subscription_by_amount",
    "subscription_by_shares",
    "to_rate",
]
