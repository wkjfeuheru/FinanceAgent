"""部署包装契约：统一 migrate 顺序、Compose 进程模型。"""

from __future__ import annotations

from pathlib import Path

from finance_agent.infrastructure.persistence.postgres.schema import (
    FAQ_SCHEMA_APPLY_ORDER,
    SCHEMA_APPLY_ORDER,
    SEED_SCHEMA_FILES,
    VECTOR_EXTENSION_SQL,
    _load_sql,
    apply_postgres_schema,
)

ROOT = Path(__file__).resolve().parents[2]


class _FakeCursor:
    def __init__(self) -> None:
        self.statements: list[str] = []

    def execute(self, sql: str, params: tuple = ()) -> None:
        self.statements.append(sql)

    def close(self) -> None:
        pass


class _FakeConnection:
    def __init__(self) -> None:
        self.cursor_instance = _FakeCursor()
        self.committed = False
        self.rolled_back = False
        self.closed = False

    def cursor(self) -> _FakeCursor:
        return self.cursor_instance

    def commit(self) -> None:
        self.committed = True

    def rollback(self) -> None:
        self.rolled_back = True

    def close(self) -> None:
        self.closed = True


def test_apply_postgres_schema_executes_in_canonical_order():
    """migrate / 懒建表共用同一函数：先结构，再 vector 扩展，再 FAQ。"""
    connection = _FakeConnection()
    apply_postgres_schema(connection, include_faq=True, include_seed=False)

    seen = connection.cursor_instance.statements
    core = [_load_sql(name) for name in SCHEMA_APPLY_ORDER]
    faq = [_load_sql(name) for name in FAQ_SCHEMA_APPLY_ORDER]
    assert seen[: len(core)] == core
    assert seen[len(core)] == VECTOR_EXTENSION_SQL
    assert seen[len(core) + 1 :] == faq


def test_apply_postgres_schema_seed_is_opt_in():
    connection = _FakeConnection()
    apply_postgres_schema(connection, include_faq=True, include_seed=True)
    assert connection.cursor_instance.statements[-1] == _load_sql(SEED_SCHEMA_FILES[0])


def test_apply_postgres_schema_can_skip_faq():
    connection = _FakeConnection()
    apply_postgres_schema(connection, include_faq=False, include_seed=False)
    seen = connection.cursor_instance.statements
    assert seen == [_load_sql(name) for name in SCHEMA_APPLY_ORDER]
    assert VECTOR_EXTENSION_SQL not in seen


def test_migrate_main_commits_on_success(monkeypatch):
    connection = _FakeConnection()
    monkeypatch.setattr(
        "finance_agent.infrastructure.settings.get_postgres_connection_factory",
        lambda: (lambda: connection),
    )
    from finance_agent.cli.migrate import main

    assert main([]) == 0
    assert connection.committed is True
    assert connection.closed is True
    assert connection.cursor_instance.statements[0] == _load_sql(SCHEMA_APPLY_ORDER[0])
    assert VECTOR_EXTENSION_SQL in connection.cursor_instance.statements


def test_migrate_main_exits_nonzero_on_failure(monkeypatch, capsys):
    def _boom():
        raise RuntimeError("POSTGRES_PASSWORD 或 POSTGRES_DSN 必须配置")

    monkeypatch.setattr("finance_agent.infrastructure.settings.get_postgres_connection_factory", _boom)
    from finance_agent.cli.migrate import main

    assert main(["--seed"]) == 1
    captured = capsys.readouterr()
    assert "schema apply 失败" in captured.err


def _load_compose(text: str) -> dict:
    try:
        import yaml
    except ImportError:
        yaml = None
    if yaml is not None:
        data = yaml.safe_load(text)
        assert isinstance(data, dict)
        return data
    services: dict[str, dict] = {}
    in_services = False
    current = None
    for raw in text.splitlines():
        line = raw.rstrip()
        if not in_services:
            if line.startswith("services:"):
                in_services = True
            continue
        if line and not line.startswith(" ") and line.endswith(":"):
            break
        if line.startswith("  ") and not line.startswith("    ") and line.endswith(":"):
            current = line.strip().rstrip(":")
            services[current] = {}
            continue
        if current is not None and "command:" in line:
            services[current]["command"] = line.split("command:", 1)[1].strip()
    return {"services": services}


def test_compose_declares_process_model_and_api_binds_all_interfaces():
    text = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")
    data = _load_compose(text)
    services = data["services"]
    for name in ("postgres", "redis", "migrate", "api", "celery", "web"):
        assert name in services, f"docker-compose.yml 缺少服务 {name}"
    api = services["api"]
    command = api.get("command")
    if isinstance(command, list):
        command_text = " ".join(str(part) for part in command)
    else:
        command_text = str(command or "")
    assert "0.0.0.0" in command_text
    assert "uvicorn" in command_text
    celery = services["celery"]
    celery_cmd = celery.get("command")
    celery_text = " ".join(str(part) for part in celery_cmd) if isinstance(celery_cmd, list) else str(celery_cmd or "")
    assert "finance.quant" in celery_text
    assert "finance_agent.infrastructure.jobs.celery_app:celery_app" in celery_text


def test_dockerfile_installs_from_lock_and_listens_publicly():
    dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")
    assert "requirements.lock" in dockerfile
    assert "--host 0.0.0.0" in dockerfile or '"0.0.0.0"' in dockerfile
    assert "DEEPSEEK_API_KEY" not in dockerfile


def test_diagnose_schema_files_follow_migrate_order():
    from finance_agent.cli.diagnose_schema_drift import SCHEMA_FILES

    assert "007_product_seed.sql" not in SCHEMA_FILES
    assert "012_faq_qa_pair_columns.sql" in SCHEMA_FILES
    assert SCHEMA_FILES == list(SCHEMA_APPLY_ORDER) + list(FAQ_SCHEMA_APPLY_ORDER)
