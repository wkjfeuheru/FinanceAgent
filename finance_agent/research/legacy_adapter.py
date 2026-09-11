"""将结构化研究结果投影为现有 API/state 字段。"""

from __future__ import annotations

from typing import Any

from finance_agent.research.contracts import AnalysisResult


def project_legacy(result: AnalysisResult) -> dict[str, Any]:
    """保留旧消费者需要的股票综合分析和技术分析形状。"""
    request = result.request
    codes = request.stock_codes if request is not None else []
    projected: dict[str, Any] = {}
    for code in codes:
        projected[code] = {
            "code": code,
            "rating": result.action.value,
            "overall_score": result.scores.get("total"),
            "summary": result.narrative,
            "data_quality": result.data_quality,
            "rule_version": result.rule_version,
            "evidence_ids": list(result.evidence_ids),
        }
    return {
        "stock_analysis": projected,
        "technical_analysis": {},
        "analysis_results": [result.model_dump(mode="json")],
    }
