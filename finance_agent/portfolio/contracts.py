"""模拟交易的不可变领域契约。

与 ``finance_agent/research/contracts.py`` 同风格：``frozen=True`` +
``extra="forbid"``，让"账户面板"和"agent 持仓问答"消费同一份结构，杜绝两处
各自算数。
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

Side = Literal["buy", "sell"]


class SourcedValue(BaseModel):
    """带来源与截止日的数值；用于净值等可溯源字段。"""

    model_config = ConfigDict(frozen=True, extra="forbid")

    value: float | None = None
    source: str = "unavailable"
    as_of: str = ""


class ProductView(BaseModel):
    """商品货架上的一项（含用于购买决策的费率与最新净值）。"""

    model_config = ConfigDict(frozen=True, extra="forbid")

    code: str
    name: str
    type: str = "fund"
    risk_level: str = ""
    company: str = ""
    manager: str = ""
    scale: float | None = None
    nav: SourcedValue = Field(default_factory=SourcedValue)
    return_1y: float | None = None
    max_drawdown: float | None = None
    sharpe_ratio: float | None = None
    subscription_fee: float | None = None
    redemption_fee: str = ""
    recommended_holding_period: str = ""
    investment_target: str = ""
    #: 上架状态；false 时不可申购，但既有持仓仍可赎回。
    is_active: bool = True
    tradable: bool = False
    limitations: list[str] = Field(default_factory=list)


class PositionView(BaseModel):
    """一笔持仓及其按最新净值计算的浮动盈亏。"""

    model_config = ConfigDict(frozen=True, extra="forbid")

    product_code: str
    product_name: str = ""
    shares: float = 0.0
    cost_amount: float = 0.0
    avg_cost: float = 0.0
    nav: float | None = None
    nav_as_of: str = ""
    market_value: float | None = None
    unrealized_pnl: float | None = None
    return_rate: float | None = None
    weight: float | None = None
    opened_at: datetime | None = None
    updated_at: datetime | None = None
    pricing_status: Literal["priced", "unavailable"] = "priced"
    limitations: list[str] = Field(default_factory=list)


class OrderView(BaseModel):
    """一条已成交的委托记录。"""

    model_config = ConfigDict(frozen=True, extra="forbid")

    order_id: str
    product_code: str
    product_name: str = ""
    side: Side
    shares: float
    price: float
    gross_amount: float
    fee: float
    net_amount: float
    realized_pnl: float | None = None
    fee_limitations: list[str] = Field(default_factory=list)
    created_at: datetime | None = None


class TransactionView(BaseModel):
    """一条资金流水。"""

    model_config = ConfigDict(frozen=True, extra="forbid")

    txn_id: str
    kind: Literal["deposit", "buy", "sell", "fee"]
    amount: float
    balance_after: float
    ref_id: str = ""
    note: str = ""
    created_at: datetime | None = None


class AccountSnapshot(BaseModel):
    """账户数据面板的口径。

    ``market_value_complete=False`` 时 ``market_value`` 只覆盖可定价的持仓，
    缺失的商品代码登记在 ``pricing_issues`` 里 —— 不把市值静默算小。
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    customer_id: str
    cash_balance: float = 0.0
    frozen_balance: float = 0.0
    market_value: float = 0.0
    total_assets: float = 0.0
    total_deposit: float = 0.0
    total_pnl: float = 0.0
    total_pnl_pct: float | None = None
    realized_pnl: float = 0.0
    position_pnl: float = 0.0
    position_cost: float = 0.0
    position_count: int = 0
    market_value_complete: bool = True
    pricing_issues: list[str] = Field(default_factory=list)
    updated_at: datetime | None = None
    simulated: bool = True
    disclaimer: str = "模拟交易数据，不构成投资建议。"


class TradeResult(BaseModel):
    """一次成交的结果（下单/清仓共用）。"""

    model_config = ConfigDict(frozen=True, extra="forbid")

    order: OrderView
    account: AccountSnapshot
    position: PositionView | None = None
    idempotent_replay: bool = False


class LiquidationResult(BaseModel):
    """一键清仓的汇总结果。"""

    model_config = ConfigDict(frozen=True, extra="forbid")

    orders: list[OrderView] = Field(default_factory=list)
    cleared_codes: list[str] = Field(default_factory=list)
    failed: dict[str, str] = Field(default_factory=dict)
    total_cash_in: float = 0.0
    total_realized_pnl: float = 0.0
    account: AccountSnapshot


__all__ = [
    "AccountSnapshot",
    "LiquidationResult",
    "OrderView",
    "PositionView",
    "ProductView",
    "Side",
    "SourcedValue",
    "TradeResult",
    "TransactionView",
]
