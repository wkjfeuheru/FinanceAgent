"""PostgreSQL 业务存储入口。"""
from __future__ import annotations

from finance_agent.infrastructure.persistence.postgres.business_store import PostgresBusinessStore


_database: PostgresBusinessStore | None = None


def get_database() -> PostgresBusinessStore:
    """返回唯一的 PostgreSQL 业务存储。"""
    global _database
    if _database is None:
        from finance_agent.infrastructure.settings import get_postgres_connection_factory

        _database = PostgresBusinessStore(get_postgres_connection_factory())
    return _database
