"""PostgreSQL 模拟交易存储入口。"""
from __future__ import annotations

from finance_agent.data.postgres_stores import PostgresPortfolioStore


_portfolio_store: PostgresPortfolioStore | None = None


def get_portfolio_store() -> PostgresPortfolioStore:
    """返回唯一的 PostgreSQL 模拟交易存储。"""
    global _portfolio_store
    if _portfolio_store is None:
        from finance_agent.config import get_postgres_connection_factory

        _portfolio_store = PostgresPortfolioStore(get_postgres_connection_factory())
    return _portfolio_store
