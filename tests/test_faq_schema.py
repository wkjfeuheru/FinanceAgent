"""FAQ 和异步运行持久化的数据库契约。"""

from finance_agent.data import postgres_schema
from finance_agent.data.postgres_schema import FAQ_VECTOR_SCHEMA_SQL, HYBRID_ORCHESTRATION_SCHEMA_SQL
from finance_agent.faq.repository import PostgresAsyncRunRepository, PostgresFaqRepository
from finance_agent.orchestrator.contracts import AsyncJobRef


def test_faq_metadata_schema_has_no_pgvector_dependency():
    """FAQ 元数据与异步任务表必须能在没有 pgvector 的库上创建。"""
    schema_sql = HYBRID_ORCHESTRATION_SCHEMA_SQL

    assert "CREATE EXTENSION" not in schema_sql
    assert "USING hnsw" not in schema_sql
    assert "finance.faq_chunks" not in schema_sql
    assert "finance.faq_documents" in schema_sql
    assert "finance.faq_index_versions" in schema_sql


def test_faq_vector_schema_contains_versioned_vector_chunks():
    """避免迁移遗漏 pgvector 或 FAQ 分块索引需要的列。"""
    schema_sql = FAQ_VECTOR_SCHEMA_SQL

    assert "CREATE EXTENSION IF NOT EXISTS vector" in schema_sql
    assert "finance.faq_chunks" in schema_sql
    assert "embedding vector(512)" in schema_sql
    assert "content_hash" in schema_sql
    assert "source_path" in schema_sql
    assert "chunk_ordinal" in schema_sql
    assert "to_tsvector" in schema_sql
    assert "vector_cosine_ops" in schema_sql
    assert "question text NOT NULL" in schema_sql
    assert "answer text NOT NULL" in schema_sql
    assert "embedding_text text NOT NULL" in schema_sql


def test_faq_qa_pair_migration_backfills_existing_chunks_and_weights_questions():
    """已有 content 数据必须无损升级，且问题关键词权重高于答案。"""
    schema_sql = postgres_schema.FAQ_QA_PAIR_SCHEMA_SQL

    assert "ADD COLUMN IF NOT EXISTS question text" in schema_sql
    assert "ADD COLUMN IF NOT EXISTS answer text" in schema_sql
    assert "ADD COLUMN IF NOT EXISTS embedding_text text" in schema_sql
    assert "UPDATE finance.faq_chunks" in schema_sql
    assert "ALTER COLUMN question SET NOT NULL" in schema_sql
    assert "ALTER COLUMN answer SET NOT NULL" in schema_sql
    assert "ALTER COLUMN embedding_text SET NOT NULL" in schema_sql
    assert "search_qa_bigrams" in schema_sql
    assert "setweight(to_tsvector('simple', finance.faq_bigrams(question)), 'A')" in schema_sql
    assert "setweight(to_tsvector('simple', finance.faq_bigrams(answer)), 'B')" in schema_sql


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
        self.description: list[tuple[str]] = []

    def execute(self, statement: str, params: tuple = ()) -> None:
        self.statements.append((statement, params))

    def fetchone(self) -> tuple | None:
        return self.row

    def fetchall(self) -> list[tuple]:
        return []

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


def test_bigram_migration_defines_chinese_keyword_search():
    """中文关键词检索依赖归一化二元组：simple 配置不切词，直接检索会 0 命中。"""
    from finance_agent.data.postgres_schema import FAQ_BIGRAM_SCHEMA_SQL

    assert "faq_bigrams" in FAQ_BIGRAM_SCHEMA_SQL
    assert "faq_normalize" in FAQ_BIGRAM_SCHEMA_SQL
    assert "search_bigrams" in FAQ_BIGRAM_SCHEMA_SQL
    assert "gin (search_bigrams)" in FAQ_BIGRAM_SCHEMA_SQL


def test_faq_repository_persists_and_reads_explicit_qa_fields():
    """仓储边界必须显式传递问答字段，不能再由 content 反向切割。"""
    connection = _AsyncConnection()
    repository = PostgresFaqRepository(lambda: connection)
    repository.publish_index(
        index_version="index-qa",
        documents=[
            {
                "document_id": "00000000-0000-0000-0000-000000000001",
                "faq_id": "FAQ-001",
                "source_path": "docs/faq/investment-basics.md",
                "content_hash": "hash",
            }
        ],
        chunks=[
            {
                "chunk_id": "00000000-0000-0000-0000-000000000002",
                "faq_id": "FAQ-001",
                "source_path": "docs/faq/investment-basics.md",
                "chunk_ordinal": 0,
                "question": "什么是保证收益？",
                "answer": "正规投资产品不会承诺保证收益。",
                "embedding_text": "问题：什么是保证收益？\n答案：正规投资产品不会承诺保证收益。",
                "content": "问题：什么是保证收益？\n答案：正规投资产品不会承诺保证收益。",
                "content_hash": "hash",
                "embedding": [1.0] + [0.0] * 511,
            }
        ],
    )
    repository.search(query_embedding=[0.0] * 512, query_text="保证收益", limit=4)

    statements = [statement for statement, _ in connection.cursor_instance.statements]
    insert = next(statement for statement in statements if "INSERT INTO finance.faq_chunks" in statement)
    search = next(statement for statement in statements if "WITH vector_candidates" in statement)
    assert "question, answer, embedding_text" in insert
    assert "question, answer" in search
    assert "search_qa_bigrams" in search
