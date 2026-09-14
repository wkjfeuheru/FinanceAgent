"""FAQ 和异步运行持久化的数据库契约。"""

from finance_agent.data.postgres_schema import HYBRID_ORCHESTRATION_SCHEMA_SQL
from finance_agent.faq.repository import PostgresAsyncRunRepository
from finance_agent.orchestrator.contracts import AsyncJobRef


def test_faq_schema_contains_versioned_vector_chunks():
    """避免迁移遗漏 pgvector 或 FAQ 分块索引需要的列。"""
    schema_sql = HYBRID_ORCHESTRATION_SCHEMA_SQL

    assert "CREATE EXTENSION IF NOT EXISTS vector" in schema_sql
    assert "finance.faq_documents" in schema_sql
    assert "finance.faq_chunks" in schema_sql
    assert "finance.faq_index_versions" in schema_sql
    assert "embedding vector(512)" in schema_sql
    assert "content_hash" in schema_sql
    assert "source_path" in schema_sql
    assert "chunk_ordinal" in schema_sql
    assert "to_tsvector" in schema_sql
    assert "vector_cosine_ops" in schema_sql


def test_async_jobs_schema_keeps_idempotency_and_resume_identifiers():
    """避免异步恢复丢失任务标识或允许重复的幂等键。"""
    schema_sql = HYBRID_ORCHESTRATION_SCHEMA_SQL

    assert "finance.async_jobs" in schema_sql
    for column in ("job_id", "thread_id", "run_id", "task_id", "status", "idempotency_key", "result_ref"):
        assert column in schema_sql
    assert "UNIQUE (idempotency_key)" in schema_sql


class _AsyncCursor:
    def __init__(self, row: tuple | None = None) -> None:
        self.row = row
        self.statements: list[tuple[str, tuple]] = []

    def execute(self, statement: str, params: tuple = ()) -> None:
        self.statements.append((statement, params))

    def fetchone(self) -> tuple | None:
        return self.row

    def close(self) -> None:
        pass


class _AsyncConnection:
    def __init__(self, row: tuple | None = None) -> None:
        self.cursor_instance = _AsyncCursor(row)
        self.committed = False

    def cursor(self) -> _AsyncCursor:
        return self.cursor_instance

    def commit(self) -> None:
        self.committed = True

    def rollback(self) -> None:
        pass

    def close(self) -> None:
        pass


def test_async_run_repository_scopes_job_lookup_to_customer():
    """防止异步任务引用按 job_id 读取时跨客户泄露。"""
    connection = _AsyncConnection(("job-1", "quant", "queued", "celery-1"))
    repository = PostgresAsyncRunRepository(lambda: connection)
    job = AsyncJobRef(job_id="job-1", kind="quant", status="queued", task_id="celery-1")

    repository.save_job_ref(
        customer_id="CUST1",
        thread_id="v1:CUST1:conv-1",
        run_id="run-1",
        job=job,
        idempotency_key="run-1:celery-1",
    )
    loaded = repository.get_job_ref("job-1", "CUST1")

    assert loaded == job
    statements = connection.cursor_instance.statements
    insert_statement = next(statement for statement, _ in statements if "INSERT INTO finance.async_jobs" in statement)
    lookup_statement, lookup_params = next(
        item for item in statements if "SELECT job_id, kind, status, task_id" in item[0]
    )
    assert "ON CONFLICT (idempotency_key)" in insert_statement
    assert "customer_id = %s" in lookup_statement
    assert lookup_params == ("job-1", "CUST1")
    assert connection.committed is True
