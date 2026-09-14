"""FAQ 混合检索的融合、阈值与结果契约。"""

from __future__ import annotations

from typing import Any, Sequence

import pytest

from finance_agent.faq.contracts import FaqSearchResult
from finance_agent.faq.retriever import FaqRetriever


class _FakeEmbedding:
    dimension = 512
    descriptor = "fake:512:normalized"

    def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        return [[0.0] * self.dimension for _ in texts]

    def embed_query(self, text: str) -> list[float]:
        return [0.0] * self.dimension


class _FakeRepository:
    """按向量距离与关键词得分直接返回候选，避免真实数据库依赖。"""

    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self._rows = rows
        self.searches: list[dict[str, Any]] = []

    def search(self, *, query_embedding, query_text, limit) -> list[dict[str, Any]]:
        self.searches.append(
            {"query_embedding": list(query_embedding), "query_text": query_text, "limit": limit}
        )
        return [dict(row) for row in self._rows]


def _row(chunk_id: str, faq_id: str, vector_distance: float, keyword_score: float = 0.0) -> dict[str, Any]:
    return {
        "chunk_id": chunk_id,
        "faq_id": faq_id,
        "index_version": "index-1",
        "source_path": "docs/faq/trading-rules.md",
        "content": f"{faq_id} 的答案内容",
        "vector_distance": vector_distance,
        "keyword_score": keyword_score,
    }


def test_retriever_returns_not_found_below_threshold():
    """低相似度候选不得作为 FAQ 证据返回。"""
    repository = _FakeRepository([_row("c1", "FAQ-100", vector_distance=1.8)])
    retriever = FaqRetriever(repository, _FakeEmbedding(), min_score=0.3)

    result = retriever.search("如何绕过涨跌停？")

    assert isinstance(result, FaqSearchResult)
    assert result.status == "not_found"
    assert result.matches == []


def test_retriever_returns_matches_with_provenance():
    """可靠命中必须携带 FAQ ID、分块 ID、分数、索引版本与来源路径。"""
    repository = _FakeRepository([_row("c1", "FAQ-001", vector_distance=0.05, keyword_score=0.4)])
    retriever = FaqRetriever(repository, _FakeEmbedding(), min_score=0.3)

    result = retriever.search("什么是保证收益？")

    assert result.status == "found"
    assert len(result.matches) == 1
    match = result.matches[0]
    assert match.faq_id == "FAQ-001"
    assert match.chunk_id == "c1"
    assert match.index_version == "index-1"
    assert match.source_path == "docs/faq/trading-rules.md"
    assert match.score == pytest.approx(0.95)
    assert repository.searches[0]["limit"] == 12


def test_retriever_fuses_vector_and_keyword_ranks():
    """同时命中向量与关键词的分块应排在仅单通道命中的分块之前。"""
    repository = _FakeRepository(
        [
            _row("vector_only", "FAQ-002", vector_distance=0.02, keyword_score=0.0),
            _row("both", "FAQ-003", vector_distance=0.04, keyword_score=0.9),
            _row("keyword_only", "FAQ-004", vector_distance=0.30, keyword_score=0.5),
        ]
    )
    retriever = FaqRetriever(repository, _FakeEmbedding(), min_score=0.3, top_k=4)

    result = retriever.search("分红与送股")

    assert result.status == "found"
    assert [match.chunk_id for match in result.matches][0] == "both"


def test_retriever_limits_matches_to_top_k():
    rows = [_row(f"c{i}", f"FAQ-{i:03d}", vector_distance=0.01 * i) for i in range(1, 8)]
    retriever = FaqRetriever(_FakeRepository(rows), _FakeEmbedding(), min_score=0.0, top_k=4)

    result = retriever.search("投资规则")

    assert len(result.matches) == 4
