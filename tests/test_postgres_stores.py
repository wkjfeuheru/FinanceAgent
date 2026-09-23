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
    from finance_agent.orchestrator.persistence import database as db
    from finance_agent.data.postgres_stores import PostgresBusinessStore

    monkeypatch.setattr(
        "finance_agent.config.get_postgres_connection_factory",
        lambda: _RecordingFactory(),
    )
    db._database = None
    try:
        assert isinstance(db.get_database(), PostgresBusinessStore)
    finally:
        db._database = None


def test_get_user_store_switches_to_postgres(monkeypatch):
    from finance_agent.data import auth
    from finance_agent.data.postgres_stores import PostgresAuthStore

    monkeypatch.setattr(
        "finance_agent.config.get_postgres_connection_factory",
        lambda: _RecordingFactory(),
    )
    auth._user_store = None
    try:
        assert isinstance(auth.get_user_store(), PostgresAuthStore)
    finally:
        auth._user_store = None


def test_postgres_stores_use_percent_placeholders():
    from finance_agent.data.postgres_stores import PostgresBusinessStore

    factory = _RecordingFactory()
    store = PostgresBusinessStore(factory)
    store.save_profile({"customer_id": "CUST001", "stock_codes": [], "confirmed_facts": {}})

    statements = [s for c in factory.connections for s in c.cursor_instance.statements]
    assert any("%s" in s and "finance.user_profiles" in s for s in statements)
    assert not any("?" in s for s in statements)
