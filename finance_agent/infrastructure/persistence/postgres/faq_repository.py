"""PostgreSQL FAQ 索引仓储。"""

from __future__ import annotations

import json
from typing import Any, Sequence
from uuid import uuid4

from finance_agent.infrastructure.persistence.postgres.connection import _PostgresRepository


class PostgresFaqRepository(_PostgresRepository):
    """FAQ 版本发布和候选查询的 PostgreSQL 实现。"""

    def _ensure_schema(self) -> None:
        # 先建不依赖 pgvector 的元数据表，再建向量分块表；缺扩展时给出修复提示。
        super()._ensure_schema()
        if self._vector_ready:
            return
        from finance_agent.infrastructure.persistence.postgres.schema import (
            FAQ_BIGRAM_SCHEMA_SQL,
            FAQ_QA_PAIR_SCHEMA_SQL,
            FAQ_VECTOR_SCHEMA_SQL,
        )

        with self._transaction() as connection:
            cursor = connection.cursor()
            try:
                cursor.execute(FAQ_VECTOR_SCHEMA_SQL)
                # 中文关键词检索需要的二元组函数、生成列与索引（见 migrations/010）。
                cursor.execute(FAQ_BIGRAM_SCHEMA_SQL)
                # 在二元组函数创建后，为已有数据补齐显式问答字段和加权索引。
                cursor.execute(FAQ_QA_PAIR_SCHEMA_SQL)
            except Exception as exc:
                message = str(exc)
                if "vector" in message and (
                    "is not available" in message or "vector.control" in message
                ):
                    raise RuntimeError(
                        "PostgreSQL 缺少 pgvector 扩展，FAQ 索引与检索不可用。"
                        "请安装 pgvector（例如 postgresql-15-pgvector）并在业务库执行 "
                        "CREATE EXTENSION vector; 后重试。"
                    ) from exc
                raise
            finally:
                cursor.close()
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

        关键词通道使用**归一化二元组**（见 migrations/010）：PostgreSQL 的 simple 配置
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


__all__ = ["PostgresFaqRepository"]
