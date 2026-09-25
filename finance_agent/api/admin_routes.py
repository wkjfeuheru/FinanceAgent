"""管理后台 REST 接口：商品发行/下架与全站用户总览。

授权：所有路由都先经 ``_require_admin``（``finance_agent.api.routes``），
它把 Bearer token 解析成 customer_id，并校验其为管理员（白名单或库内角色）。
非管理员一律 403，前端据此隐藏入口。

设计约束：

- **复用既有口径**：账户数字来自 ``PortfolioService``，与用户自己的"账户"
  页面同源；管理后台不重算、不另立一套数。
- **下架是软状态**：``products.is_active=false`` 而非删除。删除会被
  ``orders.product_code`` 外键挡下，且会让历史成交失去可解释的标的。
- **只有买入被拦截**：下架商品的既有持仓仍可赎回，否则用户被困。
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Request

from finance_agent.admin.service import get_admin_service
from finance_agent.api.admin_schemas import (
    AdminProductListResponse,
    AdminProductUpsertRequest,
    AdminUserEntry,
    AdminUserListResponse,
    AdminUserPortfolioResponse,
)
from finance_agent.api.errors import http_500
from finance_agent.api.routes import _require_admin
from finance_agent.portfolio.errors import PortfolioError, ProductNotFoundError
from finance_agent.portfolio.service import SIMULATED_DISCLAIMER

router = APIRouter(prefix="/api/admin", tags=["admin"])


def _entry(row: dict[str, Any]) -> AdminUserEntry:
    return AdminUserEntry(
        customer_id=str(row.get("customer_id") or ""),
        username=str(row.get("username") or ""),
        display_name=str(row.get("display_name") or ""),
        created_at=str(row.get("created_at") or ""),
        is_admin=bool(row.get("is_admin")),
        account=row.get("account"),
    )


# ── 用户与持仓总览 ──────────────────────────────────────────────

@router.get("/users", response_model=AdminUserListResponse)
async def list_users(http_request: Request) -> AdminUserListResponse:
    """全部注册用户及其账户概览（资金、持仓市值、盈亏）。"""
    _require_admin(http_request)
    try:
        users = get_admin_service().list_users()
    except Exception as exc:  # noqa: BLE001 - 未预期失败显式暴露而非静默空列表
        raise http_500("读取用户列表", exc) from exc
    return AdminUserListResponse(users=[_entry(row) for row in users])


@router.get("/users/{customer_id}/portfolio", response_model=AdminUserPortfolioResponse)
async def get_user_portfolio(http_request: Request, customer_id: str) -> AdminUserPortfolioResponse:
    """指定用户的账户与持仓明细。"""
    _require_admin(http_request)
    try:
        payload = get_admin_service().get_user_portfolio(customer_id)
    except Exception as exc:  # noqa: BLE001
        raise http_500("读取用户持仓", exc) from exc
    if not payload.get("exists"):
        raise HTTPException(status_code=404, detail=f"用户 {customer_id} 不存在")
    return AdminUserPortfolioResponse(
        customer_id=str(customer_id).upper(),
        user=_entry({**payload["user"], "account": payload.get("account")}),
        account=payload.get("account"),
        positions=payload.get("positions") or [],
    )


# ── 商品发行与上下架 ────────────────────────────────────────────

@router.get("/products", response_model=AdminProductListResponse)
async def list_products(http_request: Request, product_type: str = "fund") -> AdminProductListResponse:
    """完整货架（含已下架商品），供管理端编辑与重新上架。"""
    _require_admin(http_request)
    try:
        products = get_admin_service().list_products(product_type)
    except Exception as exc:  # noqa: BLE001
        raise http_500("读取商品列表", exc) from exc
    return AdminProductListResponse(products=products)


@router.post("/products", status_code=201)
async def upsert_product(
    http_request: Request, payload: AdminProductUpsertRequest,
) -> dict[str, Any]:
    """新增或更新商品（发行/编辑）。已存在的代码按传入字段覆盖。"""
    _require_admin(http_request)
    try:
        product = get_admin_service().upsert_product(payload.model_dump())
    except ProductNotFoundError as exc:
        raise HTTPException(status_code=400, detail=exc.message) from exc
    except PortfolioError as exc:
        # 净值非正一类的入参问题属于调用方错误，不该报 500。
        raise HTTPException(status_code=400, detail=exc.message) from exc
    except Exception as exc:  # noqa: BLE001
        raise http_500("保存商品", exc) from exc
    return {"product": product.model_dump(mode="json"), "disclaimer": SIMULATED_DISCLAIMER}


@router.post("/products/{code}/offline")
async def offline_product(http_request: Request, code: str) -> dict[str, Any]:
    """下架商品：不可再申购，既有持仓仍可赎回。

    返回更新后的货架视图，让前端无需再发一次详情请求。
    """
    _require_admin(http_request)
    try:
        product = get_admin_service().set_product_active(code, False)
    except ProductNotFoundError as exc:
        raise HTTPException(status_code=404, detail=exc.message) from exc
    except Exception as exc:  # noqa: BLE001
        raise http_500("下架", exc) from exc
    return {"product": product.model_dump(mode="json"), "message": f"商品 {code} 已下架"}


@router.post("/products/{code}/publish")
async def publish_product(http_request: Request, code: str) -> dict[str, Any]:
    """重新上架商品。"""
    _require_admin(http_request)
    try:
        product = get_admin_service().set_product_active(code, True)
    except ProductNotFoundError as exc:
        raise HTTPException(status_code=404, detail=exc.message) from exc
    except Exception as exc:  # noqa: BLE001
        raise http_500("上架", exc) from exc
    return {"product": product.model_dump(mode="json"), "message": f"商品 {code} 已上架"}


__all__ = ["router"]
