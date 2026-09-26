"""FAQ 混合检索的融合、阈值与结果契约。"""

from __future__ import annotations

from typing import Any, Sequence

import pytest

from finance_agent.domains.faq.contracts import FaqSearchResult
from finance_agent.domains.faq.retriever import FaqRetriever


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
        "question": f"{faq_id} 的问题？",
        "answer": f"{faq_id} 的答案内容",
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
    assert match.question == "FAQ-001 的问题？"
    assert match.answer == "FAQ-001 的答案内容"
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


# ── 相对阈值：弱相关条目必须被甩开 ─────────────────────────────────────────

def test_relative_ratio_drops_weak_hits():
    """一问一答场景：只有与最佳命中接近的条目才算证据。

    复现真实缺陷——问“定投”时，弱相关的“分散投资”(0.30) 曾与正确条目
    (0.82) 一起返回，模型会挑错条目作答。
    """
    repository = _FakeRepository([
        _row("c-good", "FAQ-004", vector_distance=0.18),   # 相似度 0.82
        _row("c-weak", "FAQ-005", vector_distance=0.70),   # 相似度 0.30
    ])
    retriever = FaqRetriever(repository, _FakeEmbedding(), min_score=0.57, relative_ratio=0.85)

    result = retriever.search("定投是什么？适合哪些情况？")

    assert [m.faq_id for m in result.matches] == ["FAQ-004"]


def test_absolute_floor_returns_not_found_for_out_of_domain():
    """整体不够相关时返回 not_found，不得拿无关分块充当证据。"""
    repository = _FakeRepository([_row("c1", "FAQ-105", vector_distance=0.52)])  # 相似度 0.48
    retriever = FaqRetriever(repository, _FakeEmbedding(), min_score=0.57)

    result = retriever.search("商品期货怎么开户")

    assert result.status == "not_found"
    assert result.matches == []


def test_close_hits_are_both_kept():
    """与最佳命中足够接近的候选应保留（多答案场景）。"""
    repository = _FakeRepository([
        _row("c1", "FAQ-011", vector_distance=0.23),   # 0.77
        _row("c2", "FAQ-012", vector_distance=0.31),   # 0.69
    ])
    retriever = FaqRetriever(repository, _FakeEmbedding(), min_score=0.57, relative_ratio=0.85)

    result = retriever.search("基金费用怎么收")

    assert [m.faq_id for m in result.matches] == ["FAQ-011", "FAQ-012"]


# ── 双通道归并：关键词行不得被向量行覆盖 ───────────────────────────────────

def test_keyword_channel_is_merged_not_overwritten():
    """仓储按 (chunk_id, 通道) 返回两行；归并后关键词得分必须保留。

    旧实现用 DISTINCT ON 去重，会保留向量行、把 keyword_score 覆盖为 NULL，
    使融合的关键词信号整条丢失。
    """
    repository = _FakeRepository([
        {"chunk_id": "c1", "faq_id": "FAQ-004", "index_version": "i",
         "source_path": "p", "question": "q", "answer": "a",
         "vector_distance": 0.2, "keyword_score": None},
        {"chunk_id": "c1", "faq_id": "FAQ-004", "index_version": "i",
         "source_path": "p", "question": "q", "answer": "a",
         "vector_distance": 0.2, "keyword_score": 0.5},
    ])
    retriever = FaqRetriever(repository, _FakeEmbedding(), min_score=0.0)

    merged = retriever._merge_channels(repository._rows)

    assert len(merged) == 1
    assert merged["c1"]["vector_distance"] == 0.2
    assert merged["c1"]["keyword_score"] == 0.5
