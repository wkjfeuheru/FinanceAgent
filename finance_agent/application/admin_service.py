"""管理后台业务层。

与 ``finance_agent.domains.portfolio.service`` 的关系：模拟交易的口径（账户、持仓、
盈亏）只能有一份实现，因此本模块**不重算**任何数字，只做管理视角的聚合
（跨用户的账户概览）与商品上下架这类运维写入。

授权不在这里判断：调用方（``finance_agent.api.routers.admin``）必须先确认
调用者是管理员，本模块的方法假定调用已被授权。
"""

from __future__ import annotations

from typing import Any

from finance_agent.domains.portfolio.contracts import AccountSnapshot, ProductView
from finance_agent.domains.portfolio.errors import InvalidAmountError, ProductNotFoundError
from finance_agent.domains.portfolio.service import PortfolioService
from finance_agent.application.portfolio_service import get_portfolio_service

#: 商品业绩字段（``finance.product_performance``）在请求里的键名。
#: 净值和收益率是"每天在变"的数据，与商品静态字段分开存表，这里负责在
#: 保存商品之后把它们一并落库 —— 否则管理端新发的商品永远没有净值可展示。
_PERFORMANCE_FIELDS = (
    "nav", "return_1m", "return_3m", "return_6m", "return_1y", "return_3y",
    "max_drawdown", "volatility", "sharpe_ratio",
)


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
        from finance_agent.infrastructure.persistence.postgres.registry import get_user_store

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

        随请求一起提交的净值/收益率写入业绩区块。业绩字段全空时不触碰
        ``product_performance`` —— 编辑商品名顺手写进一条空净值，会让货架上
        出现一个"有净值但值为空"的假象。
        """
        code = str(data.get("code", "")).strip()
        if not code or not str(data.get("name", "")).strip():
            raise ProductNotFoundError("商品代码与名称不能为空")
        if not self.portfolio.library.upsert_product(data):
            raise ProductNotFoundError("商品保存失败：代码与名称不能为空")
        self._write_performance(code, data)
        return self.portfolio.get_product(code)

    def _write_performance(self, code: str, data: dict[str, Any]) -> None:
        """把请求里的业绩字段写成一条 ``product_performance`` 记录。

        语义与商品表一致：**只覆盖传入的字段，未传的沿用上一条**。业绩表按
        ``(product_code, id DESC)`` 取最新一条且只追加不更新，所以如果编辑商品
        时只改近一年收益、没重填净值，新行必须继承旧净值 —— 否则最新行变成
        ``nav=NULL``，会把一个本来可申购的商品默默变成"缺净值"。
        """
        performance = {field: data.get(field) for field in _PERFORMANCE_FIELDS}
        nav_date = str(data.get("nav_date") or "").strip()
        if all(value is None for value in performance.values()) and not nav_date:
            return
        nav = performance.get("nav")
        if nav is not None and float(nav) <= 0:
            # 非正净值会被取价逻辑判为不可用，与其存进去当"有数据"，不如当场拒绝。
            raise InvalidAmountError("最新净值必须大于 0")

        current = (self.portfolio.library.query_by_code(code) or {}).get("performance") or {}
        merged = {
            field: (performance[field] if performance[field] is not None else current.get(field))
            for field in _PERFORMANCE_FIELDS
        }
        merged["update_date"] = nav_date or str(current.get("as_of") or "")
        if not self.portfolio.library.upsert_performance(code, merged):
            raise ProductNotFoundError(f"商品 {code} 的业绩数据保存失败")


_admin_service: AdminService | None = None


def get_admin_service() -> AdminService:
    """返回唯一的管理后台服务实例。"""
    global _admin_service
    if _admin_service is None:
        _admin_service = AdminService()
    return _admin_service


__all__ = ["AdminService", "get_admin_service"]
