"""模拟交易接口的请求/响应模型。"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from finance_agent.portfolio.contracts import (
    AccountSnapshot,
    LiquidationResult,
    OrderView,
    PositionView,
    ProductView,
    TradeResult,
    TransactionView,
)


class DepositRequest(BaseModel):
    """充值请求。"""

    amount: float = Field(..., gt=0, description="充值金额（元）")
    # 幂等键：同一个键重复提交只入账一次，避免网络重试造成重复充值。
    idempotency_key: str = Field(default="", max_length=128, description="幂等键")


class OrderRequest(BaseModel):
    """下单请求（买入按金额/份额，卖出按份额或全部）。"""

    product_code: str = Field(..., min_length=1, max_length=32, description="商品代码")
    side: Literal["buy", "sell"] = Field(..., description="买卖方向")
    amount: float | None = Field(default=None, gt=0, description="买入金额（元）")
    shares: float | None = Field(default=None, gt=0, description="份额")
    all: bool = Field(default=False, description="卖出时是否全部赎回")
    idempotency_key: str = Field(default="", max_length=128, description="幂等键")


class LiquidationRequest(BaseModel):
    """一键清仓请求。"""

    idempotency_key: str = Field(default="", max_length=128, description="幂等键")


class ProductShelfResponse(BaseModel):
    """商品货架。"""

    products: list[ProductView] = Field(default_factory=list)
    simulated: bool = True


class PositionListResponse(BaseModel):
    """持仓列表。"""

    customer_id: str
    positions: list[PositionView] = Field(default_factory=list)
    account: AccountSnapshot
    simulated: bool = True


class OrderListResponse(BaseModel):
    """成交记录。"""

    customer_id: str
    orders: list[OrderView] = Field(default_factory=list)
    simulated: bool = True


class TransactionListResponse(BaseModel):
    """资金流水。"""

    customer_id: str
    transactions: list[TransactionView] = Field(default_factory=list)
    simulated: bool = True


class DepositResponse(BaseModel):
    """充值结果。"""

    transaction: TransactionView
    account: AccountSnapshot
    idempotent_replay: bool = False
    simulated: bool = True


class TradeResponse(TradeResult):
    """下单结果（继承成交契约，保持字段一致）。"""


class LiquidationResponse(LiquidationResult):
    """清仓结果（继承清仓契约，保持字段一致）。"""


__all__ = [
    "DepositRequest",
    "DepositResponse",
    "LiquidationRequest",
    "LiquidationResponse",
    "OrderListResponse",
    "OrderRequest",
    "PositionListResponse",
    "ProductShelfResponse",
    "TradeResponse",
    "TransactionListResponse",
]
