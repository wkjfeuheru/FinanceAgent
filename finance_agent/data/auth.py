"""PostgreSQL 认证存储入口。"""
from __future__ import annotations

from finance_agent.data.postgres_stores import PostgresAuthStore


_user_store: PostgresAuthStore | None = None


def get_user_store() -> PostgresAuthStore:
    """返回唯一的 PostgreSQL 认证存储。"""
    global _user_store
    if _user_store is None:
        from finance_agent.config import get_postgres_connection_factory

        _user_store = PostgresAuthStore(get_postgres_connection_factory())
    return _user_store
