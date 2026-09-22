"""管理后台业务层。

与 ``finance_agent.portfolio.service`` 的关系：模拟交易的口径（账户、持仓、
盈亏）只能有一份实现，因此本模块**不重算**任何数字，只做管理视角的聚合
（跨用户的账户概览）与商品上下架这类运维写入。

授权不在这里判断：调用方（``finance_agent.api.admin_routes``）必须先确认
调用者是管理员，本模块的方法假定调用已被授权。
"""

from __future__ import annotations

from typing import Any

from finance_agent.portfolio.contracts import AccountSnapshot, ProductView
from finance_agent.portfolio.errors import ProductNotFoundError
from finance_agent.portfolio.service import PortfolioService, get_portfolio_service


class AdminService:
    """管理后台的读与运维写。

    依赖通过构造参数注入，便于测试替换：``auth_store`` 提供用户表，
    ``portfolio`` 提供商品与账户口径。
    """

    def __init__(self, auth_store: Any = None, portfolio: PortfolioService | None = None) -> None:
        self._auth_store = auth_store
        self._portfolio = portfolio

    @property
    def auth_store(self) -> Any:
        if self._auth_store is not None:
            return self._auth_store
        from finance_agent.data.auth import get_user_store

        return get_user_store()

    @property
    def portfolio(self) -> PortfolioService:
        if self._portfolio is not None:
            return self._portfolio
        return get_portfolio_service()

    # ── 用户与持仓 ───────────────────────────────────────────────

    def list_users(self) -> list[dict[str, Any]]:
        """全部用户及其账户概览（资金、持仓数量）。

        账户数字由 ``PortfolioService.get_account`` 提供，与用户自己在"账户"
        页面看到的完全一致 —— 管理视角不另立口径。
        """
        users: list[dict[str, Any]] = []
        for row in self.auth_store.list_users():
            customer_id = str(row.get("customer_id") or "")
            snapshot = self._account_snapshot(customer_id)
            users.append({
                **row,
                "account": snapshot,
            })
        return users

    def get_user_portfolio(self, customer_id: str) -> dict[str, Any]:
        """单个用户的账户与持仓明细。

        用户不存在时抛 ``ProductNotFoundError`` 语义之外的错误不合适，这里
        直接返回带 ``exists=False`` 的结构，交由路由决定状态码。
        """
        user = self.auth_store.get_user_by_customer_id(customer_id)
        if user is None:
            return {"exists": False, "user": None, "account": None, "positions": []}
        snapshot = self._account_snapshot(customer_id)
        positions = self.portfolio.list_positions(customer_id)
        return {
            "exists": True,
            "user": user,
            "account": snapshot,
            "positions": positions,
        }

    def _account_snapshot(self, customer_id: str) -> AccountSnapshot | None:
        """读取账户口径；单个用户读取失败不拖垮整个列表。"""
        if not customer_id:
            return None
        try:
            return self.portfolio.get_account(customer_id)
        except Exception:  # noqa: BLE001 - 单个账户异常不应让管理列表整体失败
            return None

    # ── 商品上下架 ───────────────────────────────────────────────

    def list_products(self, product_type: str = "fund") -> list[ProductView]:
        """含下架商品在内的完整货架（管理视角）。"""
        return self.portfolio.list_products(product_type, include_inactive=True)

    def set_product_active(self, code: str, active: bool) -> ProductView:
        """上架/下架商品；返回更新后的货架视图。

        商品不存在时抛 ``ProductNotFoundError``，路由据此返回 404。
        """
        normalized = str(code).strip()
        if not normalized:
            raise ProductNotFoundError("请提供商品代码")
        if self.portfolio.library.query_by_code(normalized) is None:
            raise ProductNotFoundError(f"商品 {normalized} 不存在")
        updated = self.portfolio.library.set_product_active(normalized, active)
        if not updated:
            raise ProductNotFoundError(f"商品 {normalized} 不存在")
        return self.portfolio.get_product(normalized)

    def upsert_product(self, data: dict[str, Any]) -> ProductView:
        """新增或更新商品（发行/编辑）。

        ``upsert_product`` 只覆盖传入的列，未传的列保持原值；新建时用列默认值。
        保存后回读货架视图，让调用方拿到与用户端一致的字段口径。
        """
        code = str(data.get("code", "")).strip()
        if not code or not str(data.get("name", "")).strip():
            raise ProductNotFoundError("商品代码与名称不能为空")
        if not self.portfolio.library.upsert_product(data):
            raise ProductNotFoundError("商品保存失败：代码与名称不能为空")
        return self.portfolio.get_product(code)


_admin_service: AdminService | None = None


def get_admin_service() -> AdminService:
    """返回唯一的管理后台服务实例。"""
    global _admin_service
    if _admin_service is None:
        _admin_service = AdminService()
    return _admin_service


__all__ = ["AdminService", "get_admin_service"]
