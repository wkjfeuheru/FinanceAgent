"""PostgreSQL 存储迁移测试（getter 切换 + SQL 占位符）。"""


class _FakeCursor:
    def __init__(self):
        self.statements = []
        self.description = []

    def execute(self, statement, params=()):
        self.statements.append(statement)

    def fetchone(self):
        return None

    def fetchall(self):
        return []

    def close(self):
        pass


class _FakeConnection:
    def __init__(self):
        self.cursor_instance = _FakeCursor()

    def cursor(self):
        return self.cursor_instance

    def commit(self):
        pass

    def rollback(self):
        pass

    def close(self):
        pass


class _RecordingFactory:
    def __init__(self):
        self.connections = []

    def __call__(self):
        conn = _FakeConnection()
        self.connections.append(conn)
        return conn


def test_get_database_switches_to_postgres(monkeypatch):
    from finance_agent.orchestration import persistence_database as db
    from finance_agent.infrastructure.persistence.postgres.business_store import PostgresBusinessStore

    monkeypatch.setattr(
        "finance_agent.infrastructure.settings.get_postgres_connection_factory",
        lambda: _RecordingFactory(),
    )
    db._database = None
    try:
        assert isinstance(db.get_database(), PostgresBusinessStore)
    finally:
        db._database = None


def test_get_user_store_switches_to_postgres(monkeypatch):
    from finance_agent.infrastructure.persistence.postgres import registry as auth
    from finance_agent.infrastructure.persistence.postgres.auth_store import PostgresAuthStore

    monkeypatch.setattr(
        "finance_agent.infrastructure.settings.get_postgres_connection_factory",
        lambda: _RecordingFactory(),
    )
    auth._user_store = None
    try:
        assert isinstance(auth.get_user_store(), PostgresAuthStore)
    finally:
        auth._user_store = None


def test_postgres_stores_use_percent_placeholders():
    from finance_agent.infrastructure.persistence.postgres.business_store import PostgresBusinessStore

    factory = _RecordingFactory()
    store = PostgresBusinessStore(factory)
    store.save_profile({"customer_id": "CUST001", "stock_codes": [], "confirmed_facts": {}})

    statements = [s for c in factory.connections for s in c.cursor_instance.statements]
    assert any("%s" in s and "finance.user_profiles" in s for s in statements)
    assert not any("?" in s for s in statements)


def test_ensure_schema_does_not_deadlock_when_transaction_is_overridden():
    """回归：子类覆写 transaction() 并在其中调用 _ensure_schema() 时不得自死锁。

    ``PostgresPortfolioStore.transaction()`` 会在入口 ``_ensure_schema()``；旧实现里
    ``_apply_schema`` 又通过 ``self.transaction()`` 跑迁移，于是同一线程二次申请
    不可重入的 ``_schema_lock`` —— 调用线程永久挂起。持仓/账户接口跑在事件循环上，
    因此这一个死锁会让整个 API（含 /api/health）都失去响应。
    """
    import threading

    from finance_agent.infrastructure.persistence.postgres.connection import _PostgresBaseStore

    class _OverrideStore(_PostgresBaseStore):
        """复刻 PostgresPortfolioStore 的事务入口形态。"""

        def transaction(self):
            self._ensure_schema()
            return self._transaction()

    factory = _RecordingFactory()
    store = _OverrideStore(factory)

    finished = threading.Event()

    def run():
        store._ensure_schema()
        finished.set()

    worker = threading.Thread(target=run, daemon=True)
    worker.start()
    worker.join(timeout=5)

    assert finished.is_set(), "首次 _ensure_schema() 挂起了：store 自死锁回归"
    assert store._schema_ready is True
    assert store._schema_lock.locked() is False
    statements = [s for c in factory.connections for s in c.cursor_instance.statements]
    assert statements, "迁移必须真的执行过一次"
