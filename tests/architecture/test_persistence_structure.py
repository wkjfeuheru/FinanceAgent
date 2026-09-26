"""Guard shared persistence seams (Task 4).

Stores, the runtime repository and the FAQ repository must share one connection /
transaction implementation, and the SQL migration order must live in exactly one
place. Schema must be applied once per instance, not per business call.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]


def test_every_persistence_adapter_shares_one_transaction_implementation() -> None:
    from finance_agent.infrastructure.persistence.postgres.transaction import TransactionRunner
    from finance_agent.infrastructure.persistence.postgres.auth_store import PostgresAuthStore
    from finance_agent.infrastructure.persistence.postgres.business_store import PostgresBusinessStore
    from finance_agent.infrastructure.persistence.postgres.portfolio_store import PostgresPortfolioStore
    from finance_agent.infrastructure.persistence.postgres.product_store import PostgresProductLibrary
    from finance_agent.infrastructure.persistence.postgres.runtime_repository import PostgresRuntimeRepository
    from finance_agent.infrastructure.persistence.postgres.faq_repository import PostgresFaqRepository
    from finance_agent.infrastructure.persistence.postgres.async_run_repository import PostgresAsyncRunRepository

    for cls in (
        PostgresBusinessStore,
        PostgresAuthStore,
        PostgresPortfolioStore,
        PostgresProductLibrary,
        PostgresRuntimeRepository,
        PostgresFaqRepository,
        PostgresAsyncRunRepository,
    ):
        assert cls._transaction is TransactionRunner.transaction, (
            f"{cls.__name__} must reuse TransactionRunner.transaction"
        )


def test_migration_order_is_declared_once() -> None:
    from finance_agent.infrastructure.persistence.postgres import migrations as postgres_migrations

    names = [step.name for step in postgres_migrations.MIGRATIONS]
    assert names, "migration list must not be empty"
    # 种子脚本 007 不含结构声明，不应进入迁移序列。
    assert "007_product_seed.sql" not in names
    # 主题清理迁移必须在序列末尾，且历史迁移保持编号连续。
    assert names[-1] == "014_remove_theme_features.sql"
    numbers = sorted(int(name[:3]) for name in names)
    assert numbers == sorted(numbers)

    # 序列是结构迁移的唯一事实源：每个脚本只出现一次。
    assert len(names) == len(set(names))


def test_schema_is_applied_once_per_store_instance() -> None:
    from finance_agent.infrastructure.persistence.postgres.business_store import PostgresBusinessStore

    class _Cursor:
        def __init__(self) -> None:
            self.statements: list[str] = []
            self.description: list = []

        def execute(self, statement: str, params=()) -> None:
            self.statements.append(statement)

        def fetchone(self):
            return None

        def fetchall(self):
            return []

        def close(self) -> None:
            pass

    class _Connection:
        def __init__(self) -> None:
            self.cursor_instance = _Cursor()

        def cursor(self):
            return self.cursor_instance

        def commit(self) -> None:
            pass

        def rollback(self) -> None:
            pass

        def close(self) -> None:
            pass

    connections: list[_Connection] = []

    def factory():
        connection = _Connection()
        connections.append(connection)
        return connection

    store = PostgresBusinessStore(factory)
    store.get_profile("CUST1")
    store.get_conversation_messages("conv-1", 10)
    store.list_conversations("CUST1")

    # 首次业务调用完成一次建表（建表自身占一条连接），后续三次业务调用各一条，
    # 且不得重复执行 DDL。
    assert len(connections) == 4
    schema_runs = [c for c in connections if any("CREATE TABLE" in s for s in c.cursor_instance.statements)]
    assert len(schema_runs) == 1, "schema must be applied exactly once per instance"


def test_migration_runner_applies_every_script_in_order() -> None:
    from finance_agent.infrastructure.persistence.postgres.migrations import MIGRATIONS
    from finance_agent.infrastructure.persistence.postgres.transaction import TransactionRunner

    class _Cursor:
        def __init__(self) -> None:
            self.seen: list[str] = []
            self.description: list = []

        def execute(self, statement: str, params=()) -> None:
            for step in MIGRATIONS:
                if statement == step.sql:
                    self.seen.append(step.name)

        def close(self) -> None:
            pass

    class _Connection:
        def __init__(self) -> None:
            self.cursor_instance = _Cursor()

        def cursor(self):
            return self.cursor_instance

        def commit(self) -> None:
            pass

        def rollback(self) -> None:
            pass

        def close(self) -> None:
            pass

    connection = _Connection()
    runner = TransactionRunner(lambda: connection)
    from finance_agent.infrastructure.persistence.postgres import migrations as postgres_migrations

    postgres_migrations.run_migrations(runner)

    assert connection.cursor_instance.seen == [step.name for step in MIGRATIONS]


def test_no_module_defines_its_own_transaction_body() -> None:
    """除 shared runner 外，其它持久化模块不得各自内联 commit/rollback。"""
    offenders: list[str] = []
    targets = (
        REPO_ROOT / "finance_agent" / "infrastructure" / "persistence" / "postgres" / "auth_store.py",
        REPO_ROOT / "finance_agent" / "infrastructure" / "persistence" / "postgres" / "runtime_repository.py",
        REPO_ROOT / "finance_agent" / "infrastructure" / "persistence" / "postgres" / "faq_repository.py",
    )
    for path in targets:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name == "_transaction":
                offenders.append(f"{path.relative_to(REPO_ROOT)}:{node.lineno}")
    assert offenders == [], (
        "transaction bodies must live only in postgres_transaction.TransactionRunner:\n"
        + "\n".join(offenders)
    )


def test_faq_domain_repository_is_a_port_and_postgres_code_lives_in_data() -> None:
    domain_path = REPO_ROOT / "finance_agent" / "domains" / "faq" / "repository.py"
    adapter_path = REPO_ROOT / "finance_agent" / "infrastructure" / "persistence" / "postgres" / "faq_repository.py"
    domain_tree = ast.parse(domain_path.read_text(encoding="utf-8"))
    adapter_tree = ast.parse(adapter_path.read_text(encoding="utf-8"))

    domain_classes = {
        node.name for node in domain_tree.body if isinstance(node, ast.ClassDef)
    }
    adapter_classes = {
        node.name for node in adapter_tree.body if isinstance(node, ast.ClassDef)
    }
    data_imports = [
        node.module
        for node in domain_tree.body
        if isinstance(node, ast.ImportFrom)
        and node.module
        and node.module.startswith("finance_agent.infrastructure.persistence.postgres")
    ]
    data_imports.extend(
        alias.name
        for node in domain_tree.body
        if isinstance(node, ast.Import)
        for alias in node.names
        if alias.name.startswith("finance_agent.infrastructure.persistence.postgres")
    )

    assert data_imports == [], "FAQ domain ports must not import infrastructure adapters"
    assert domain_classes == {"FaqRepository", "AsyncRunRepository"}
    assert "PostgresFaqRepository" in adapter_classes
    adapter_bases = {
        base.id
        for node in adapter_tree.body
        if isinstance(node, ast.ClassDef)
        for base in node.bases
        if isinstance(base, ast.Name)
    }
    assert "_PostgresRepository" in adapter_bases
    async_path = REPO_ROOT / "finance_agent" / "infrastructure" / "persistence" / "postgres" / "async_run_repository.py"
    async_tree = ast.parse(async_path.read_text(encoding="utf-8"))
    async_classes = {node.name for node in async_tree.body if isinstance(node, ast.ClassDef)}
    assert "PostgresAsyncRunRepository" in async_classes


def test_schema_application_never_re_enters_overridable_transaction() -> None:
    """``_apply_schema`` 不得调用 ``self.transaction()`` / ``self._ensure_schema()``。

    ``_schema_lock`` 是不可重入的 ``threading.Lock``，而
    ``PostgresPortfolioStore.transaction()`` 会在入口调用 ``_ensure_schema()``。
    若迁移再走 ``self.transaction()``，同一线程会二次申请同一把锁 —— 永久死锁。
    这个 bug 曾让持仓/账户接口把整个事件循环卡死，前端商品、持仓页全部取不到数据。
    """
    path = (
        REPO_ROOT / "finance_agent" / "infrastructure" / "persistence"
        / "postgres" / "connection.py"
    )
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    targets = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef) and node.name == "_apply_schema"
    ]
    assert len(targets) == 1, "connection.py must define exactly one _apply_schema"
    observed = targets[0]
    offenders = [
        call.func.attr
        for call in ast.walk(observed)
        if isinstance(call, ast.Call)
        and isinstance(call.func, ast.Attribute)
        and isinstance(call.func.value, ast.Name)
        and call.func.value.id == "self"
        and call.func.attr in {"transaction", "_ensure_schema"}
    ]
    assert offenders == [], (
        "_apply_schema 必须用原始 TransactionRunner 跑迁移，"
        f"不能经过会被子类覆写的入口（发现：{offenders}）"
    )
