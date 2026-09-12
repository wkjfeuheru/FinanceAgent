"""将结构化研究结果投影为现有 API/state 字段。"""

from __future__ import annotations

from typing import Any

from finance_agent.research.contracts import AnalysisResult


def _entry(result: AnalysisResult, code: str) -> dict[str, Any]:
    """单只标的的旧字段投影；只引用该标的自己的结论与证据。"""
    return {
        "code": code,
        "rating": result.action.value,
        "overall_score": result.scores.get("total"),
        "summary": result.narrative,
        "data_quality": result.data_quality,
        "rule_version": result.rule_version,
        "evidence_ids": list(result.evidence_ids),
    }


def project_legacy_many(results: list[AnalysisResult]) -> dict[str, Any]:
    """投影多条按标的独立的结论。

    比较请求会为每只标的给出各自的结论，因此这里按结果自身的 ``request``
    归属代码，绝不把某一只股票的评级复制给其他标的。
    """
    projected: dict[str, Any] = {}
    for result in results:
        request = result.request
        codes = request.stock_codes if request is not None else []
        for code in codes:
            projected[code] = _entry(result, code)
    return {
        "stock_analysis": projected,
        "technical_analysis": {},
        "analysis_results": [result.model_dump(mode="json") for result in results],
    }
