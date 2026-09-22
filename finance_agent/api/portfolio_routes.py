"""模拟交易 REST 接口（商品展示、购买、持仓、清仓、账户面板）。

设计要点：

- **身份只来自 Bearer token**：路径里不带 ``customer_id``，从根上消除越权读写，
  与既有 ``/api/profile/{customer_id}`` 的路径式鉴权形成互补。
- **写入只经此处**：Agent 对话领域只能读账户与持仓，下单与充值必须走本路由，
  与"投顾不代客操作"的既有取向一致。
- 所有响应标注"模拟交易"，不构成投资建议。
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Request

from finance_agent.api.portfolio_schemas import (
    DepositRequest,
    DepositResponse,
    LiquidationRequest,
    LiquidationResponse,
    OrderListResponse,
    OrderRequest,
    PositionListResponse,
    ProductShelfResponse,
    TradeResponse,
    TransactionListResponse,
)
from finance_agent.api.routes import _require_customer_id
from finance_agent.portfolio.contracts import ProductView
from finance_agent.portfolio.errors import (
    InsufficientFundsError,
    InsufficientSharesError,
    InvalidAmountError,
    NoPositionError,
    PortfolioError,
    PricingUnavailableError,
    ProductNotFoundError,
    ProductOfflineError,
)
from finance_agent.portfolio.service import PortfolioService, get_portfolio_service

router = APIRouter(prefix="/api/portfolio", tags=["portfolio"])

# 业务异常 → HTTP 状态码。价格与资金类冲突用 409，入参问题用 400，找不到用 404。
_STATUS_BY_ERROR: dict[type[PortfolioError], int] = {
    ProductNotFoundError: 404,
    InvalidAmountError: 400,
    PricingUnavailableError: 409,
    InsufficientFundsError: 409,
    InsufficientSharesError: 409,
    NoPositionError: 409,
    # 下架是与当前商品状态冲突（而非入参格式错误），与其余状态冲突同为 409。
    ProductOfflineError: 409,
}


def get_service() -> PortfolioService:
    """获取模拟交易服务实例（延迟构造，便于测试替换）。"""
    return get_portfolio_service()


def _fail(exc: PortfolioError) -> HTTPException:
    status = _STATUS_BY_ERROR.get(type(exc), 400)
    return HTTPException(status_code=status, detail=f"{exc.message}（{exc.code}）")


def _guard(action: str, call: Any) -> Any:
    """统一把业务异常映射为 HTTP 错误，其余异常按 500 上报。"""
    try:
        return call()
    except PortfolioError as exc:
        raise _fail(exc) from exc
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001 - 未预期失败要显式暴露而非静默成功
        raise HTTPException(status_code=500, detail=f"{action}失败：{exc}") from exc


# ── 商品展示 ────────────────────────────────────────────────────

@router.get("/products", response_model=ProductShelfResponse)
async def list_products(http_request: Request, product_type: str = "fund") -> ProductShelfResponse:
    """商品货架；取不到净值的商品照常展示但标记为不可交易。"""
    _require_customer_id(http_request)
    products: list[ProductView] = _guard(
        "读取商品货架", lambda: get_service().list_products(product_type)
    )
    return ProductShelfResponse(products=products)


@router.get("/products/{code}", response_model=ProductView)
async def get_product(http_request: Request, code: str) -> ProductView:
    """单个商品详情（含费率与最新净值）。"""
    _require_customer_id(http_request)
    return _guard("读取商品", lambda: get_service().get_product(code))


# ── 账户数据面板 ────────────────────────────────────────────────

@router.get("/account")
async def get_account(http_request: Request) -> dict[str, Any]:
    """账户数据面板口径（总资产/可用资金/持仓市值/累计盈亏）。"""
    customer_id = _require_customer_id(http_request)
    snapshot = _guard("读取账户", lambda: get_service().get_account(customer_id))
    return snapshot.model_dump(mode="json")


@router.get("/positions", response_model=PositionListResponse)
async def list_positions(http_request: Request) -> PositionListResponse:
    """持仓明细，含最新净值、市值、浮动盈亏与占比。"""
    customer_id = _require_customer_id(http_request)
    service = get_service()
    positions = _guard("读取持仓", lambda: service.list_positions(customer_id))
    account = _guard("读取账户", lambda: service.get_account(customer_id))
    return PositionListResponse(
        customer_id=str(customer_id).upper(), positions=positions, account=account,
    )


# ── 充值 ────────────────────────────────────────────────────────

@router.post("/deposit", response_model=DepositResponse)
async def deposit(http_request: Request, payload: DepositRequest) -> DepositResponse:
    """充值虚拟资金；同一 ``idempotency_key`` 重复提交只入账一次。"""
    customer_id = _require_customer_id(http_request)
    txn, account, replay = _guard(
        "充值",
        lambda: get_service().deposit(
            customer_id, payload.amount, idempotency_key=payload.idempotency_key,
        ),
    )
    return DepositResponse(transaction=txn, account=account, idempotent_replay=replay)


# ── 下单 ────────────────────────────────────────────────────────

@router.post("/orders", response_model=TradeResponse)
async def create_order(http_request: Request, payload: OrderRequest) -> TradeResponse:
    """买入或卖出。买入需提供 ``amount`` 或 ``shares`` 之一；卖出提供 ``shares`` 或 ``all``。"""
    customer_id = _require_customer_id(http_request)
    service = get_service()

    def _place() -> Any:
        if payload.side == "buy":
            return service.buy(
                customer_id, payload.product_code,
                amount=payload.amount, shares=payload.shares,
                idempotency_key=payload.idempotency_key,
            )
        if payload.amount is not None:
            raise InvalidAmountError("卖出请使用份额（shares）或全部赎回（all）")
        return service.sell(
            customer_id, payload.product_code,
            shares=payload.shares, all_shares=payload.all,
            idempotency_key=payload.idempotency_key,
        )

    return TradeResponse(**_guard("下单", _place).model_dump())


@router.post("/liquidate", response_model=LiquidationResponse)
async def liquidate(http_request: Request, payload: LiquidationRequest) -> LiquidationResponse:
    """一键清仓：逐个商品全额赎回；无法定价的商品只登记失败，不伪造成交。"""
    customer_id = _require_customer_id(http_request)
    result = _guard("清仓", lambda: get_service().liquidate_all(customer_id))
    return LiquidationResponse(**result.model_dump())


# ── 记录 ────────────────────────────────────────────────────────

@router.get("/orders", response_model=OrderListResponse)
async def list_orders(http_request: Request, limit: int = 100) -> OrderListResponse:
    """成交记录（含费用与已实现盈亏）。"""
    customer_id = _require_customer_id(http_request)
    orders = _guard("读取成交记录", lambda: get_service().list_orders(customer_id, limit))
    return OrderListResponse(customer_id=str(customer_id).upper(), orders=orders)


@router.get("/transactions", response_model=TransactionListResponse)
async def list_transactions(http_request: Request, limit: int = 100) -> TransactionListResponse:
    """资金流水。"""
    customer_id = _require_customer_id(http_request)
    items = _guard("读取资金流水", lambda: get_service().list_transactions(customer_id, limit))
    return TransactionListResponse(customer_id=str(customer_id).upper(), transactions=items)


__all__ = ["get_service", "router"]
