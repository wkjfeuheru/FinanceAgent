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

    def save_pending_outcome(
        self,
        *,
        customer_id: str,
        thread_id: str,
        run_id: str,
        conversation_id: str,
        job_id: str,
        outcome: dict[str, Any],
    ) -> None: ...

    def get_pending_outcome(self, job_id: str, customer_id: str) -> dict[str, Any] | None: ...

    def delete_pending_outcome(self, job_id: str) -> None: ...


class _PostgresRepository:
    def __init__(self, connection_factory) -> None:
        self._connection_factory = connection_factory
        self._schema_ready = False
        self._vector_ready = False

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
        """建表：元数据与异步任务表不依赖 pgvector（`async_jobs` 只在此处需要）。"""
        if self._schema_ready:
            return
        from finance_agent.data.postgres_schema import apply_postgres_schema

        with self._transaction() as connection:
            apply_postgres_schema(connection, include_faq=False, include_seed=False)
        self._schema_ready = True


class PostgresFaqRepository(_PostgresRepository):
    """FAQ 版本发布和候选查询的 PostgreSQL 实现。"""

    def _ensure_schema(self) -> None:
        # 与 migrate CLI 同一份清单；缺 pgvector 时 apply_postgres_schema 给出修复提示。
        if self._schema_ready and self._vector_ready:
            return
        from finance_agent.data.postgres_schema import apply_postgres_schema

        with self._transaction() as connection:
            apply_postgres_schema(connection, include_faq=True, include_seed=False)
        self._schema_ready = True
        self._vector_ready = True

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
                           (chunk_id, index_version, faq_id, source_path, chunk_ordinal,
                            question, answer, embedding_text, content, content_hash, embedding, is_active)
                           VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::vector, false)
                           ON CONFLICT (index_version, faq_id, chunk_ordinal) DO UPDATE SET
                              source_path = EXCLUDED.source_path,
                              question = EXCLUDED.question,
                              answer = EXCLUDED.answer,
                              embedding_text = EXCLUDED.embedding_text,
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
                            chunk["question"],
                            chunk["answer"],
                            chunk["embedding_text"],
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
        """返回向量与关键词两个通道各 limit 条的候选并集，融合由调用层决定。

        关键词通道使用**归一化二元组**（见 sql/010）：PostgreSQL 的 simple 配置
        不切中文，直接对原文检索会 0 命中。两个通道的结果按 (chunk_id, 通道)
        原样返回、**不做 DISTINCT ON 去重**——去重会按向量距离保留单行，把同一
        分块的关键词得分覆盖成 NULL，使融合时的关键词信号整条丢失；合并交给
        调用层按 chunk_id 归并。
        """
        if len(query_embedding) != 512:
            raise ValueError("FAQ query embedding must contain 512 dimensions")
        if limit < 1:
            return []
        self._ensure_schema()
        embedding_literal = json.dumps(list(query_embedding))
        with self._transaction() as connection:
            cursor = connection.cursor()
            try:
                cursor.execute(
                    """WITH vector_candidates AS (
                           SELECT chunk_id, faq_id, index_version, source_path, question, answer,
                                   embedding <=> %s::vector AS vector_distance,
                                  NULL::double precision AS keyword_score,
                                  0 AS channel
                           FROM finance.faq_chunks
                           WHERE is_active
                           ORDER BY embedding <=> %s::vector
                           LIMIT %s
                       ), keyword_candidates AS (
                           SELECT chunk_id, faq_id, index_version, source_path, question, answer,
                                   embedding <=> %s::vector AS vector_distance,
                                   ts_rank_cd(search_qa_bigrams,
                                              websearch_to_tsquery('simple', finance.faq_bigrams(%s))) AS keyword_score,
                                  1 AS channel
                           FROM finance.faq_chunks
                           WHERE is_active
                              AND search_qa_bigrams @@ websearch_to_tsquery('simple', finance.faq_bigrams(%s))
                           ORDER BY keyword_score DESC
                           LIMIT %s
                       )
                       SELECT chunk_id, faq_id, index_version, source_path, question, answer,
                              vector_distance, keyword_score, channel
                       FROM (
                           SELECT * FROM vector_candidates
                           UNION ALL
                           SELECT * FROM keyword_candidates
                       ) combined
                       ORDER BY chunk_id, channel""",
                    (
                        embedding_literal,
                        embedding_literal,
                        limit,
                        embedding_literal,
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

    def list_job_refs(self, thread_id: str) -> list[AsyncJobRef]:
        """列出某线程下的异步任务引用，供恢复协调器扫描。"""
        self._ensure_schema()
        with self._transaction() as connection:
            cursor = connection.cursor()
            try:
                cursor.execute(
                    """SELECT job_id, kind, status, task_id
                       FROM finance.async_jobs
                       WHERE thread_id = %s
                       ORDER BY created_at""",
                    (thread_id,),
                )
                rows = cursor.fetchall()
            finally:
                cursor.close()
        return [
            AsyncJobRef(job_id=row[0], kind=row[1], status=row[2], task_id=row[3])
            for row in rows
        ]

    def save_pending_outcome(
        self,
        *,
        customer_id: str,
        thread_id: str,
        run_id: str,
        conversation_id: str,
        job_id: str,
        outcome: dict[str, Any],
        code: str = "",
    ) -> None:
        """落库一条待完成的领域结论快照（按 job_id 幂等 upsert）。

        以 ``job_id`` 为主键：一次领域执行提交的每个量化任务各一行，共享同一份
        结论快照；重复写入（同 job 重试）只更新，不产生多行。``code`` 记录该
        job 对应的标的，恢复时据此把指标合并回 ``technical_analysis[code]``。
        """
        if not job_id:
            raise ValueError("pending outcome requires a job_id")
        task_id = str(outcome.get("task_id") or "")
        if not task_id:
            raise ValueError("pending outcome requires a task_id")
        self._ensure_schema()
        with self._transaction() as connection:
            cursor = connection.cursor()
            try:
                cursor.execute(
                    """INSERT INTO finance.pending_outcomes
                       (job_id, task_id, code, customer_id, thread_id, run_id, conversation_id, outcome)
                       VALUES (%s, %s, %s, %s, %s, %s, %s, %s::jsonb)
                       ON CONFLICT (job_id) DO UPDATE SET
                         task_id = EXCLUDED.task_id,
                         code = EXCLUDED.code,
                         customer_id = EXCLUDED.customer_id,
                         thread_id = EXCLUDED.thread_id,
                         run_id = EXCLUDED.run_id,
                         conversation_id = EXCLUDED.conversation_id,
                         outcome = EXCLUDED.outcome,
                         updated_at = now()""",
                    (
                        job_id, task_id, code, customer_id, thread_id,
                        run_id, conversation_id, json.dumps(outcome, ensure_ascii=False),
                    ),
                )
            finally:
                cursor.close()

    def get_pending_outcome(self, job_id: str, customer_id: str) -> dict[str, Any] | None:
        """取回待完成结论快照；按 customer_id 隔离，非本人任务返回 None。"""
        return self._load_pending_outcome(job_id, customer_id=customer_id)

    def get_pending_outcome_by_job(self, job_id: str) -> dict[str, Any] | None:
        """按 job_id 取快照（不校验归属）；仅供编排进程内部恢复使用。"""
        return self._load_pending_outcome(job_id, customer_id="")

    def _load_pending_outcome(
        self, job_id: str, *, customer_id: str
    ) -> dict[str, Any] | None:
        self._ensure_schema()
        with self._transaction() as connection:
            cursor = connection.cursor()
            try:
                if customer_id:
                    cursor.execute(
                        """SELECT outcome, task_id, code, conversation_id, thread_id, run_id
                           FROM finance.pending_outcomes
                           WHERE job_id = %s AND customer_id = %s""",
                        (job_id, customer_id),
                    )
                else:
                    cursor.execute(
                        """SELECT outcome, task_id, code, conversation_id, thread_id, run_id
                           FROM finance.pending_outcomes
                           WHERE job_id = %s""",
                        (job_id,),
                    )
                row = cursor.fetchone()
            finally:
                cursor.close()
        if row is None:
            return None
        outcome = row[0]
        if isinstance(outcome, str):
            outcome = json.loads(outcome)
        return {
            "outcome": outcome,
            "task_id": row[1],
            "code": row[2],
            "conversation_id": row[3],
            "thread_id": row[4],
            "run_id": row[5],
        }

    def delete_pending_outcome(self, job_id: str) -> None:
        """删除该 job 的快照行（该 job 已收尾）。"""
        self._ensure_schema()
        with self._transaction() as connection:
            cursor = connection.cursor()
            try:
                cursor.execute(
                    "DELETE FROM finance.pending_outcomes WHERE job_id = %s", (job_id,)
                )
            finally:
                cursor.close()

    def list_pending_outcomes_for_task(self, task_id: str) -> list[dict[str, Any]]:
        """列出同一领域任务下仍待完成的 job 行（判定该结论是否可收尾）。"""
        self._ensure_schema()
        with self._transaction() as connection:
            cursor = connection.cursor()
            try:
                cursor.execute(
                    """SELECT job_id, code, outcome, conversation_id
                       FROM finance.pending_outcomes
                       WHERE task_id = %s
                       ORDER BY created_at""",
                    (task_id,),
                )
                rows = cursor.fetchall()
            finally:
                cursor.close()
        results: list[dict[str, Any]] = []
        for row in rows:
            outcome = row[2]
            if isinstance(outcome, str):
                outcome = json.loads(outcome)
            results.append(
                {
                    "job_id": row[0], "code": row[1],
                    "outcome": outcome, "conversation_id": row[3],
                }
            )
        return results

    def list_pending_outcomes(self, thread_id: str) -> list[dict[str, Any]]:
        """列出某线程下全部待完成结论快照（供批量恢复/观测）。"""
        self._ensure_schema()
        with self._transaction() as connection:
            cursor = connection.cursor()
            try:
                cursor.execute(
                    """SELECT job_id, task_id, outcome, conversation_id
                       FROM finance.pending_outcomes
                       WHERE thread_id = %s
                       ORDER BY created_at""",
                    (thread_id,),
                )
                rows = cursor.fetchall()
            finally:
                cursor.close()
        results: list[dict[str, Any]] = []
        for row in rows:
            outcome = row[2]
            if isinstance(outcome, str):
                outcome = json.loads(outcome)
            results.append(
                {
                    "job_id": row[0], "task_id": row[1],
                    "outcome": outcome, "conversation_id": row[3],
                }
            )
        return results
