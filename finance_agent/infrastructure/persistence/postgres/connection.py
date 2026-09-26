"""共享 PostgreSQL store 基础能力与行/JSON 转换工具。"""

from __future__ import annotations

import hashlib
import json
import threading
from typing import Any

from finance_agent.infrastructure.persistence.postgres.migrations import run_migrations
from finance_agent.infrastructure.persistence.postgres.transaction import TransactionRunner

TOKEN_TTL_SECONDS = 7 * 24 * 3600


def _hash_password(password: str, salt: str) -> str:
    return hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 100_000).hex()


def _json_loads(value: Any) -> Any:
    """将 jsonb 返回的 dict/list 或 JSON 字符串统一为 Python 对象。"""
    if value is None or isinstance(value, (dict, list)):
        return value
    try:
        return json.loads(value)
    except (TypeError, ValueError):
        return value


def _dict_rows(cursor: Any, rows: list[Any]) -> list[dict[str, Any]]:
    """按 cursor.description 将元组行转换为 dict。"""
    columns = [desc[0] for desc in (cursor.description or [])]
    return [dict(zip(columns, row)) for row in rows]


def is_unique_violation(exc: BaseException) -> bool:
    """识别 PostgreSQL unique_violation（SQLSTATE 23505）及其包装异常。"""
    current: BaseException | None = exc
    seen: set[int] = set()
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        if str(getattr(current, "sqlstate", "") or "") == "23505":
            return True
        try:
            from psycopg.errors import UniqueViolation

            if isinstance(current, UniqueViolation):
                return True
        except ImportError:
            pass
        current = current.__cause__ or current.__context__
    text = str(exc).lower()
    return "duplicate" in text and "unique" in text


class UniqueConstraintError(Exception):
    """测试与适配层用来模拟 PostgreSQL unique_violation（SQLSTATE 23505）。"""

    sqlstate = "23505"


class _PostgresBaseStore:
    """共享的事务与建表能力。

    事务实现直接复用 ``TransactionRunner.transaction``（提交/回滚只有一处）；
    建表走 ``run_migrations`` 的唯一迁移序列，避免每个 store 各自内联一份 DDL
    清单与事务语义。
    """

    #: 兼容既有 ``self._transaction()`` 调用点；实现来自共享 runner。
    _transaction = TransactionRunner.transaction
    transaction = TransactionRunner.transaction

    def __init__(self, connection_factory):
        self._connection_factory = connection_factory
        self._schema_ready = False
        # 建表是懒加载且只应执行一次；不同会话现在可并发进入，无锁时
        # 两个线程可能同时跑 DDL，在 Postgres 目录表上竞争。
        self._schema_lock = threading.Lock()

    def _ensure_schema(self) -> None:
        if self._schema_ready:
            return
        with self._schema_lock:
            if self._schema_ready:
                return
            self._apply_schema()

    def _apply_schema(self) -> None:
        # 迁移必须走**原始** runner，不能用 ``self``：子类可以覆写 ``transaction()``
        # 并在其中调用 ``_ensure_schema()``（``PostgresPortfolioStore`` 就是如此），
        # 而 ``_schema_lock`` 是不可重入的 ``threading.Lock`` —— 同线程二次申请会
        # 永久死锁。曾因此让整个 API 事件循环卡死（持仓/账户页取不到数据）。
        run_migrations(TransactionRunner(self._connection_factory))
        self._schema_ready = True


class _PostgresRepository:
    """Shared transaction and lazy schema seam for focused repositories."""

    _transaction = TransactionRunner.transaction
    transaction = TransactionRunner.transaction

    def __init__(self, connection_factory) -> None:
        self._connection_factory = connection_factory
        self._schema_ready = False
        self._vector_ready = False

    def _ensure_schema(self) -> None:
        if self._schema_ready:
            return
        from finance_agent.infrastructure.persistence.postgres.schema import (
            HYBRID_ORCHESTRATION_SCHEMA_SQL,
        )

        with self._transaction() as connection:
            cursor = connection.cursor()
            try:
                cursor.execute(HYBRID_ORCHESTRATION_SCHEMA_SQL)
            finally:
                cursor.close()
        self._schema_ready = True


__all__ = [
    "TOKEN_TTL_SECONDS",
    "_PostgresBaseStore",
    "_PostgresRepository",
    "_dict_rows",
    "_hash_password",
    "_json_loads",
]
