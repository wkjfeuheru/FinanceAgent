"""FAQ 混合检索：向量召回 + 关键词召回，融合、阈值过滤与证据投影。

融合分定义为 ``归一化 RRF × 语义相似度``。RRF 只表达“排名的相对一致性”，
无法判断候选整体是否相关；乘以余弦相似度后，完全不相关的候选集分数会趋近
于 0，从而让 ``FAQ_MIN_SCORE`` 能有意义地判出 ``not_found``。
"""

from __future__ import annotations

from typing import Any, Sequence

from finance_agent import config
from finance_agent.faq.contracts import FaqSearchMatch, FaqSearchResult

_RRF_K = 60
_MIN_CANDIDATES = 12


def _similarity(vector_distance: Any) -> float:
    if vector_distance is None:
        return 0.0
    return max(0.0, min(1.0, 1.0 - float(vector_distance)))


class FaqRetriever:
    """隐藏 Markdown、embedding 与 pgvector 细节的检索入口。"""

    def __init__(
        self,
        repository: Any,
        embedding_provider: Any,
        *,
        min_score: float | None = None,
        top_k: int = 4,
    ) -> None:
        self._repository = repository
        self._embedding_provider = embedding_provider
        self._min_score = config.FAQ_MIN_SCORE if min_score is None else min_score
        self._top_k = top_k

    def search(self, query: str, top_k: int | None = None) -> FaqSearchResult:
        limit = top_k or self._top_k
        if not query.strip() or limit < 1:
            return FaqSearchResult(status="not_found", matches=[])

        candidates = self._repository.search(
            query_embedding=self._embedding_provider.embed_query(query),
            query_text=query,
            limit=max(limit * 3, _MIN_CANDIDATES),
        )
        if not candidates:
            return FaqSearchResult(status="not_found", matches=[])

        scored = self._fuse(candidates)
        matches: list[FaqSearchMatch] = []
        for candidate, score in scored:
            if score < self._min_score:
                continue
            matches.append(
                FaqSearchMatch(
                    faq_id=candidate["faq_id"],
                    chunk_id=str(candidate["chunk_id"]),
                    score=score,
                    index_version=candidate["index_version"],
                    source_path=candidate["source_path"],
                    content=candidate["content"],
                )
            )
            if len(matches) >= limit:
                break

        if not matches:
            return FaqSearchResult(status="not_found", matches=[])
        return FaqSearchResult(status="found", matches=matches)

    def _fuse(self, candidates: Sequence[dict[str, Any]]) -> list[tuple[dict[str, Any], float]]:
        vector_ranked = sorted(
            (c for c in candidates if c.get("vector_distance") is not None),
            key=lambda c: (float(c["vector_distance"]), str(c["chunk_id"])),
        )
        keyword_ranked = sorted(
            (c for c in candidates if float(c.get("keyword_score") or 0.0) > 0.0),
            key=lambda c: (-float(c["keyword_score"]), str(c["chunk_id"])),
        )

        rrf: dict[str, float] = {str(c["chunk_id"]): 0.0 for c in candidates}
        for rank, candidate in enumerate(vector_ranked):
            rrf[str(candidate["chunk_id"])] += 1.0 / (_RRF_K + rank + 1)
        for rank, candidate in enumerate(keyword_ranked):
            rrf[str(candidate["chunk_id"])] += 1.0 / (_RRF_K + rank + 1)

        max_rrf = max(rrf.values()) or 1.0
        scored: list[tuple[dict[str, Any], float]] = []
        for candidate in candidates:
            normalized = rrf[str(candidate["chunk_id"])] / max_rrf
            score = round(normalized * _similarity(candidate.get("vector_distance")), 6)
            scored.append((candidate, score))
        scored.sort(key=lambda item: (-item[1], str(item[0]["chunk_id"])))
        return scored
