"""管理后台测试：角色解析、上下架语义与用户总览授权。

用内存假存储与假库替代 PostgreSQL（沿用仓库既有"手写 fake + monkeypatch"惯例），
因此不依赖真实数据库即可覆盖：非管理员被拒、下架只挡买入不挡赎回、
下架商品不再出现在管理端列表之外的用户货架上。
"""

from __future__ import annotations

import asyncio
from contextlib import contextmanager

import pytest
from fastapi import HTTPException

from finance_agent.admin.service import AdminService
from finance_agent.api import routes as r
from finance_agent.api import admin_routes
from finance_agent.portfolio.errors import (
    NoPositionError,
    ProductNotFoundError,
    ProductOfflineError,
)
from finance_agent.portfolio.pricing import NavQuote
from finance_agent.portfolio.service import PortfolioDeps, PortfolioService


# ── 假存储与假库 ──────────────────────────────────────────────────

class _Request:
    def __init__(self, token: str = "admin-token"):
        self.headers = {"Authorization": f"Bearer {token}"}


class _FakeAuthStore:
    """内存用户表：只需覆盖管理后台用到的读与写。"""

    def __init__(self, users=None):
        self._users = users or {
            "CUST000001": {"customer_id": "CUST000001", "username": "jason",
                           "display_name": "jason", "created_at": "2026-09-04T20:00:31",
                           "is_admin": False},
            "CUST000002": {"customer_id": "CUST000002", "username": "admin",
                           "display_name": "admin", "created_at": "2026-09-17T10:00:00",
                           "is_admin": True},
        }

    def list_users(self):
        return [dict(row) for row in self._users.values()]

    def get_user_by_customer_id(self, customer_id):
        row = self._users.get(str(customer_id).upper())
        return dict(row) if row else None

    def is_admin(self, customer_id):
        row = self._users.get(str(customer_id).upper())
        return bool(row and row.get("is_admin"))

    def set_admin(self, customer_id, is_admin):
        row = self._users.get(str(customer_id).upper())
        if row is None:
            return False
        row["is_admin"] = bool(is_admin)
        return True


class _FakeLibrary:
    """内存产品库：上下架状态真正改变，供断言读取。"""

    def __init__(self, products):
        self._products = {code: dict(data) for code, data in products.items()}

    def _shape(self, code):
        raw = self._products.get(str(code).strip())
        if raw is None:
            return None
        return {
            "basic_info": {
                "code": str(code).strip(), "name": raw["name"],
                "type": raw.get("type", "fund"), "is_active": raw.get("is_active", True),
                "risk_level": raw.get("risk_level", ""), "company": "", "manager": "",
                "scale": None, "recommended_holding_period": "", "investment_target": "",
            },
            "performance": {"nav": raw.get("nav"), "as_of": raw.get("as_of", "2026-09-08"),
                            "return_1y": None, "max_drawdown": None, "sharpe_ratio": None},
            "fee": {"subscription_fee": raw.get("subscription_fee"),
                    "redemption_fee": raw.get("redemption_fee", "")},
        }

    def query_by_code(self, code):
        return self._shape(str(code).strip())

    def query_by_codes(self, codes):
        return [item for item in (self._shape(c) for c in codes) if item]

    def list_products(self, product_type="fund", include_inactive=False):
        return [
            {"code": code, "name": data["name"]}
            for code, data in self._products.items()
            if include_inactive or data.get("is_active", True)
        ]

    def set_product_active(self, code, active):
        raw = self._products.get(str(code).strip())
        if raw is None:
            return False
        raw["is_active"] = bool(active)
        return True


class _FakeNavSource:
    def __init__(self, navs):
        self._navs = navs

    def latest_nav(self, product_code):
        nav = self._navs.get(str(product_code).strip())
        return NavQuote(product_code=str(product_code), nav=nav, as_of="2026-09-08") if nav else None


class _FakeCursor:
    """占位游标：假存储在事务里只需要一个可传入的对象。"""

    def execute(self, *args, **kwargs):
        return None

    def fetchone(self):
        return None

    def close(self):
        pass


class _FakeConnection:
    """假连接：``cursor()`` 返回占位游标，与真实存储的事务形态一致。"""

    def cursor(self):
        return _FakeCursor()


class _FakePortfolioStore:
    """最小账户/持仓存储：有资金、无持仓。

    申购在走到商品校验前会先 ``ensure_account``，因此这里必须有账户行；
    持仓为空则让赎回止步于 ``NoPositionError``，正好用来验证"下架不挡赎回"。
    """

    def ensure_account(self, customer_id):
        return {"customer_id": str(customer_id).upper(), "cash_balance": 10000.0,
                "frozen_balance": 0.0, "total_deposit": 10000.0, "updated_at": None}

    def list_positions(self, customer_id):
        return []

    def realized_pnl_total(self, customer_id):
        return 0.0

    @contextmanager
    def transaction(self):
        yield _FakeConnection()

    def lock_account(self, cursor, customer_id):
        return self.ensure_account(customer_id)

    def get_position_row(self, cursor, customer_id, product_code):
        return None


PRODUCTS = {
    "110011": {"name": "易方达中小盘混合", "nav": 3.85, "subscription_fee": 1.5},
    "003003": {"name": "华夏现金增利货币A", "nav": 1.0, "subscription_fee": 0.0},
}


def _portfolio(library=None):
    return PortfolioService(PortfolioDeps(
        store=_FakePortfolioStore(),
        library=library or _FakeLibrary(PRODUCTS),
        nav_source=_FakeNavSource({"110011": 3.85, "003003": 1.0}),
    ))


# ── 角色解析 ──────────────────────────────────────────────────────

@pytest.fixture()
def roles(monkeypatch):
    """装一个库内有角色的 store，并清空白名单。"""
    store = _FakeAuthStore()
    monkeypatch.setattr(r, "get_user_store", lambda: store)
    monkeypatch.setattr(r, "ADMIN_CUSTOMER_IDS", set())
    return store


def test_db_role_grants_admin_without_whitelist(roles):
    """库内 is_admin=true 即可成为管理员，无需环境变量白名单。"""
    assert r._is_admin("CUST000002") is True
    assert r._is_admin("cust000002") is True
    assert r._is_admin("CUST000001") is False


def test_whitelist_still_grants_admin(monkeypatch):
    """白名单与库内角色取并集：改配置即可授权的既有运维方式继续可用。"""
    monkeypatch.setattr(r, "get_user_store", lambda: _FakeAuthStore())
    monkeypatch.setattr(r, "ADMIN_CUSTOMER_IDS", {"CUST000001"})

    assert r._is_admin("CUST000001") is True


def test_role_lookup_failure_fails_closed(monkeypatch):
    """角色查询异常时必须按"非管理员"处理，不能让库故障变成提权。"""
    class _Broken:
        def is_admin(self, customer_id):
            raise RuntimeError("db down")

    monkeypatch.setattr(r, "get_user_store", lambda: _Broken())
    monkeypatch.setattr(r, "ADMIN_CUSTOMER_IDS", set())

    assert r._is_admin("CUST000002") is False


def test_demoted_user_loses_admin(roles):
    """把用户降级后，其管理员权限立即消失（不依赖重启或缓存）。"""
    roles.set_admin("CUST000002", False)

    assert r._is_admin("CUST000002") is False


# ── 授权门禁 ──────────────────────────────────────────────────────

def test_non_admin_cannot_list_users(monkeypatch):
    """普通用户调用管理接口被 403 拦下。"""
    monkeypatch.setattr(r, "get_user_store", lambda: _FakeAuthStore())
    monkeypatch.setattr(r, "ADMIN_CUSTOMER_IDS", set())
    monkeypatch.setattr(r, "_require_customer_id", lambda request: "CUST000001")

    with pytest.raises(HTTPException) as exc:
        asyncio.run(admin_routes.list_users(_Request()))
    assert exc.value.status_code == 403


def test_admin_can_list_users_through_route(monkeypatch):
    """管理员经路由拿到用户总览。"""
    store = _FakeAuthStore()
    monkeypatch.setattr(r, "get_user_store", lambda: store)
    monkeypatch.setattr(r, "_require_customer_id", lambda request: "CUST000002")
    monkeypatch.setattr(admin_routes, "get_admin_service",
                        lambda: AdminService(auth_store=store, portfolio=_portfolio()))

    response = asyncio.run(admin_routes.list_users(_Request()))

    assert {item.customer_id for item in response.users} == {"CUST000001", "CUST000002"}
    assert response.users[1].is_admin is True


# ── 用户总览 ──────────────────────────────────────────────────────

def test_admin_lists_users_with_account_snapshot():
    """用户列表带账户口径，且与用户端同源（都由 PortfolioService 计算）。"""
    service = AdminService(auth_store=_FakeAuthStore(), portfolio=_portfolio())

    users = {row["customer_id"]: row for row in service.list_users()}

    assert set(users) == {"CUST000001", "CUST000002"}
    assert users["CUST000002"]["is_admin"] is True
    snapshot = users["CUST000001"]["account"]
    assert snapshot is not None
    assert snapshot.customer_id == "CUST000001"


def test_user_portfolio_reports_missing_user():
    """不存在的用户返回 exists=False，而不是伪造一个空账户。"""
    service = AdminService(auth_store=_FakeAuthStore(), portfolio=_portfolio())

    payload = service.get_user_portfolio("CUST999999")

    assert payload["exists"] is False
    assert payload["account"] is None


# ── 上下架 ────────────────────────────────────────────────────────

def test_offline_removes_product_from_user_shelf_but_keeps_admin_view():
    library = _FakeLibrary(PRODUCTS)
    service = AdminService(auth_store=_FakeAuthStore(), portfolio=_portfolio(library))

    service.set_product_active("110011", False)

    user_codes = [item.code for item in service.portfolio.list_products()]
    admin_codes = [item.code for item in service.list_products()]
    assert "110011" not in user_codes
    assert "110011" in admin_codes


def test_offline_blocks_buy_but_allows_sell():
    """下架只挡买入：既有持仓必须还能赎回，否则用户被困。"""
    library = _FakeLibrary(PRODUCTS)
    library.set_product_active("110011", False)
    service = _portfolio(library)

    with pytest.raises(ProductOfflineError):
        service.buy("CUST000001", "110011", amount=1000.0)

    # 赎回走的是商品存在性 + 持仓校验，不应再撞上下架拦截。
    with pytest.raises(NoPositionError):
        service.sell("CUST000001", "110011", shares=10.0)


def test_reactivating_restores_tradability():
    library = _FakeLibrary(PRODUCTS)
    service = AdminService(auth_store=_FakeAuthStore(), portfolio=_portfolio(library))

    service.set_product_active("110011", False)
    product = service.set_product_active("110011", True)

    assert product.is_active is True
    assert product.tradable is True
    assert "product_offline" not in product.limitations


def test_offline_unknown_product_raises_not_found():
    service = AdminService(auth_store=_FakeAuthStore(), portfolio=_portfolio())

    with pytest.raises(ProductNotFoundError):
        service.set_product_active("000000", False)


def test_active_product_view_exposes_is_active():
    service = _portfolio()

    shelf = {item.code: item for item in service.list_products()}
    assert shelf["110011"].is_active is True
    assert shelf["110011"].tradable is True
