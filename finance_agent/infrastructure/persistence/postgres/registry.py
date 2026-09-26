"""PostgreSQL stores 的惰性单例组合入口。"""

from __future__ import annotations

from finance_agent.infrastructure.persistence.postgres.auth_store import PostgresAuthStore
from finance_agent.infrastructure.persistence.postgres.portfolio_store import PostgresPortfolioStore
from finance_agent.infrastructure.persistence.postgres.product_store import PostgresProductLibrary

_user_store: PostgresAuthStore | None = None
_portfolio_store: PostgresPortfolioStore | None = None
_product_library: PostgresProductLibrary | None = None


def _connection_factory():
    from finance_agent.infrastructure.settings import get_postgres_connection_factory

    return get_postgres_connection_factory()


def get_user_store() -> PostgresAuthStore:
    global _user_store
    if _user_store is None:
        _user_store = PostgresAuthStore(_connection_factory())
    return _user_store


def get_portfolio_store() -> PostgresPortfolioStore:
    global _portfolio_store
    if _portfolio_store is None:
        _portfolio_store = PostgresPortfolioStore(_connection_factory())
    return _portfolio_store


def get_product_library() -> PostgresProductLibrary:
    global _product_library
    if _product_library is None:
        _product_library = PostgresProductLibrary(_connection_factory())
    return _product_library


__all__ = ["get_portfolio_store", "get_product_library", "get_user_store"]
