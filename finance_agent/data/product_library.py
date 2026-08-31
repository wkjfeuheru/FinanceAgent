"""PostgreSQL 产品库存储入口。"""
from __future__ import annotations

from finance_agent.data.postgres_stores import PostgresProductLibrary


_product_library: PostgresProductLibrary | None = None


def get_product_library() -> PostgresProductLibrary:
    """返回唯一的 PostgreSQL 产品库存储。"""
    global _product_library
    if _product_library is None:
        from finance_agent.config import get_postgres_connection_factory

        _product_library = PostgresProductLibrary(get_postgres_connection_factory())
    return _product_library
