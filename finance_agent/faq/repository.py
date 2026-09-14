"""FAQ 索引与异步运行引用的 PostgreSQL 仓储边界。"""

from __future__ import annotations

import json
from contextlib import contextmanager
from typing import Any, Iterator, Protocol, Sequence
from uuid import uuid4

from finance_agent.orchestrator.contracts import AsyncJobRef


class FaqRepository(Protocol):
    """FAQ 索引发布和查询的持久化边界。"""

    def publish_index(
        self,
        *,
        index_version: str,
        documents: Sequence[dict[str, Any]],
        chunks: Sequence[dict[str, Any]],
    ) -> None: ...

    def search(
        self,
        *,
        query_embedding: Sequence[float],
        query_text: str,
        limit: int,
    ) -> list[dict[str, Any]]: ...


class AsyncRunRepository(Protocol):
    def save_job_ref(
        self,
        *,
        customer_id: str,
        thread_id: str,
        run_id: str,
        job: AsyncJobRef,
        idempotency_key: str,
    ) -> None: ...

    def get_job_ref(self, job_id: str, customer_id: str) -> AsyncJobRef | None: ...


class _PostgresRepository:
    def __init__(self, connection_factory) -> None:
        self._connection_factory = connection_factory
        self._schema_ready = False

    @contextmanager
    def _transaction(self) -> Iterator[Any]:
        connection = self._connection_factory()
        try:
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def _ensure_schema(self) -> None:
        if self._schema_ready:
            return
        from finance_agent.data.postgres_schema import HYBRID_ORCHESTRATION_SCHEMA_SQL

        with self._transaction() as connection:
            cursor = connection.cursor()
            try:
                cursor.execute(HYBRID_ORCHESTRATION_SCHEMA_SQL)
            finally:
                cursor.close()
        self._schema_ready = True


class PostgresFaqRepository(_PostgresRepository):
    """FAQ 版本发布和候选查询的 PostgreSQL 实现。"""

    def publish_index(
        self,
        *,
        index_version: str,
        documents: Sequence[dict[str, Any]],
        chunks: Sequence[dict[str, Any]],
    ) -> None:
        """在同一事务写入完整版本，再切换活跃版本。"""
        if not index_version:
            raise ValueError("index_version is required")
        self._ensure_schema()
        with self._transaction() as connection:
            cursor = connection.cursor()
            try:
                cursor.execute(
                    """INSERT INTO finance.faq_index_versions (index_version, is_active)
                       VALUES (%s, false)
                       ON CONFLICT (index_version) DO UPDATE SET is_active = false""",
                    (index_version,),
                )
                for document in documents:
                    cursor.execute(
                        """INSERT INTO finance.faq_documents
                           (document_id, index_version, faq_id, source_path, content_hash)
                           VALUES (%s, %s, %s, %s, %s)
                           ON CONFLICT (index_version, faq_id) DO UPDATE SET
                             source_path = EXCLUDED.source_path,
                             content_hash = EXCLUDED.content_hash""",
                        (
                            str(document.get("document_id") or uuid4()),
                            index_version,
                            document["faq_id"],
                            document["source_path"],
                            document["content_hash"],
                        ),
                    )
                for chunk in chunks:
                    embedding = list(chunk["embedding"])
                    if len(embedding) != 512:
                        raise ValueError("FAQ embedding must contain 512 dimensions")
                    cursor.execute(
                        """INSERT INTO finance.faq_chunks
                           (chunk_id, index_version, faq_id, source_path, chunk_ordinal, content,
                            content_hash, embedding, is_active)
                           VALUES (%s, %s, %s, %s, %s, %s, %s, %s::vector, false)
                           ON CONFLICT (index_version, faq_id, chunk_ordinal) DO UPDATE SET
                             source_path = EXCLUDED.source_path,
                             content = EXCLUDED.content,
                             content_hash = EXCLUDED.content_hash,
                             embedding = EXCLUDED.embedding,
                             is_active = false""",
                        (
                            str(chunk.get("chunk_id") or uuid4()),
                            index_version,
                            chunk["faq_id"],
                            chunk["source_path"],
                            chunk["chunk_ordinal"],
                            chunk["content"],
                            chunk["content_hash"],
                            json.dumps(embedding),
                        ),
                    )
                cursor.execute(
                    "UPDATE finance.faq_chunks SET is_active = false WHERE index_version <> %s",
                    (index_version,),
                )
                cursor.execute(
                    "UPDATE finance.faq_index_versions SET is_active = false WHERE index_version <> %s",
                    (index_version,),
                )
                cursor.execute(
                    "UPDATE finance.faq_chunks SET is_active = true WHERE index_version = %s",
                    (index_version,),
                )
                cursor.execute(
                    "UPDATE finance.faq_index_versions SET is_active = true WHERE index_version = %s",
                    (index_version,),
                )
            finally:
                cursor.close()

    def search(
        self,
        *,
        query_embedding: Sequence[float],
        query_text: str,
        limit: int,
    ) -> list[dict[str, Any]]:
        """返回向量与关键词两个通道各 limit 条的候选并集，融合由调用层决定。"""
        if len(query_embedding) != 512:
            raise ValueError("FAQ query embedding must contain 512 dimensions")
        if limit < 1:
            return []
        self._ensure_schema()
        with self._transaction() as connection:
            cursor = connection.cursor()
            try:
                cursor.execute(
                    """WITH vector_candidates AS (
                           SELECT chunk_id, faq_id, index_version, source_path, content,
                                  embedding <=> %s::vector AS vector_distance,
                                  NULL::double precision AS keyword_score
                           FROM finance.faq_chunks
                           WHERE is_active
                           ORDER BY embedding <=> %s::vector
                           LIMIT %s
                       ), keyword_candidates AS (
                           SELECT chunk_id, faq_id, index_version, source_path, content,
                                  embedding <=> %s::vector AS vector_distance,
                                  ts_rank_cd(search_text, websearch_to_tsquery('simple', %s)) AS keyword_score
                           FROM finance.faq_chunks
                           WHERE is_active
                             AND search_text @@ websearch_to_tsquery('simple', %s)
                           ORDER BY keyword_score DESC
                           LIMIT %s
                       )
                       SELECT DISTINCT ON (chunk_id)
                              chunk_id, faq_id, index_version, source_path, content,
                              vector_distance, keyword_score
                       FROM (
                           SELECT * FROM vector_candidates
                           UNION ALL
                           SELECT * FROM keyword_candidates
                       ) combined
                       ORDER BY chunk_id, vector_distance""",
                    (
                        json.dumps(list(query_embedding)),
                        json.dumps(list(query_embedding)),
                        limit,
                        json.dumps(list(query_embedding)),
                        query_text,
                        query_text,
                        limit,
                    ),
                )
                rows = cursor.fetchall()
                columns = [description[0] for description in (cursor.description or [])]
            finally:
                cursor.close()
        return [dict(zip(columns, row)) for row in rows]


class PostgresAsyncRunRepository(_PostgresRepository):
    """异步任务的可恢复引用仓储。"""

    def save_job_ref(
        self,
        *,
        customer_id: str,
        thread_id: str,
        run_id: str,
        job: AsyncJobRef,
        idempotency_key: str,
    ) -> None:
        self._ensure_schema()
        with self._transaction() as connection:
            cursor = connection.cursor()
            try:
                cursor.execute(
                    """INSERT INTO finance.async_jobs
                       (job_id, customer_id, thread_id, run_id, task_id, kind, status, idempotency_key, result_ref)
                       VALUES (%s, %s, %s, %s, %s, %s, %s, %s, '')
                       ON CONFLICT (idempotency_key) DO UPDATE SET
                         job_id = EXCLUDED.job_id,
                         thread_id = EXCLUDED.thread_id,
                         run_id = EXCLUDED.run_id,
                         task_id = EXCLUDED.task_id,
                         kind = EXCLUDED.kind,
                         status = EXCLUDED.status,
                         updated_at = now()""",
                    (job.job_id, customer_id, thread_id, run_id, job.task_id, job.kind, job.status, idempotency_key),
                )
            finally:
                cursor.close()

    def get_job_ref(self, job_id: str, customer_id: str) -> AsyncJobRef | None:
        self._ensure_schema()
        with self._transaction() as connection:
            cursor = connection.cursor()
            try:
                cursor.execute(
                    """SELECT job_id, kind, status, task_id
                       FROM finance.async_jobs
                       WHERE job_id = %s AND customer_id = %s""",
                    (job_id, customer_id),
                )
                row = cursor.fetchone()
            finally:
                cursor.close()
        if row is None:
            return None
        return AsyncJobRef(job_id=row[0], kind=row[1], status=row[2], task_id=row[3])
