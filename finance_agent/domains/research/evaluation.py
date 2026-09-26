"""确定性研究评估：把请求编译为可审计的分标的结论。

这是领域内**确定性多跳**的封装层：``evaluate`` 一次完成"构建带溯源快照 →
执行质量门禁 → 规则裁决 → 生成结论与证据事实"，供股票专家的
``evaluate_research`` 工具调用，也供审计重放复用。

设计边界：

- 承接自旧的 ``ResearchPipeline``，但**不再是"固定管线"的执行路径**——它只是
  一个可被 ReAct 工具按需调用的确定性函数，不编排任何步骤序列。
- 结论的原子单位是**单只标的**：比较请求为每只标的各生成一条独立结论，引用各自
  的证据事实，避免把某一只的评分/行动投影到其他标的上。
- 产出的 ``AnalysisResult`` / ``FactSnapshot`` 形状与审计持久化契约严格一致
  （``application/run_persistence.py`` 逐项 ``AnalysisResult.model_validate``）。
"""

from __future__ import annotations

from typing import Any

from finance_agent.shared.contracts import FactSnapshot
from finance_agent.domains.research.contracts import (
    AnalysisRequest,
    AnalysisResult,
    MarketDataSnapshot,
    SecuritySnapshot,
)
from finance_agent.domains.research.narrative import NarrativeRenderer
from finance_agent.domains.research.rule_engine import RuleEngine
from finance_agent.domains.research.snapshot_builder import SnapshotBuilder


def evaluate(
    request: AnalysisRequest,
    *,
    user_profile: dict[str, Any],
    gateway: Any,
    rule_engine: RuleEngine | None = None,
    narrative: NarrativeRenderer | None = None,
) -> tuple[list[AnalysisResult], list[FactSnapshot]]:
    """按标的独立评估：每只标的各有一条结论，引用各自的证据事实。

    ``gateway`` 是取数网关（``StockDataGateway`` 结构子集）；本层据其构建带溯源
    与门禁的快照。``rule_engine`` 缺省用仓库审定规则，``narrative`` 缺省用确定性
    模板渲染。

    快照按整个请求构建一次，因此跨标的质量门禁（例如报告期混用）会影响其中
    每一条结论，而不是只影响第一只股票。
    """
    renderer = narrative or NarrativeRenderer()
    engine = rule_engine or RuleEngine.default()
    builder = SnapshotBuilder(gateway)
    prepared = _with_profile(request, user_profile)
    snapshot, facts = builder.build(prepared)
    if not snapshot.securities:
        # 无标的请求保持单条结论语义。
        assessment = engine.evaluate(snapshot, prepared)
        return [_build_result(prepared, snapshot, assessment, facts, renderer)], facts

    results: list[AnalysisResult] = []
    for security in snapshot.securities:
        item_request = prepared.for_security(security.code)
        item_snapshot = snapshot.model_copy(
            update={"securities": [security], "request": item_request},
        )
        assessment = engine.evaluate(item_snapshot, item_request)
        results.append(_build_result(
            item_request, item_snapshot, assessment,
            _evidence_for(security, facts), renderer,
        ))
    return results, facts


def _with_profile(
    request: AnalysisRequest, user_profile: dict[str, Any],
) -> AnalysisRequest:
    """按用户画像补全 profile_complete，保持既有语义。"""
    return request.model_copy(update={
        "profile_complete": bool(
            request.profile_complete
            or (
                str((user_profile or {}).get("risk_preference", "")).strip()
                and str((user_profile or {}).get("holding_period", "")).strip()
            )
        )
    })


def _evidence_for(security: SecuritySnapshot, facts: list[FactSnapshot]) -> list[FactSnapshot]:
    """只引用该标的自己的证据事实；无匹配时返回空。

    曾经无匹配就退回**整轮**事实，会让该标的的结论引用其他标的的证据，污染逐标的
    归属与审计重放关联（比较请求下尤其明显）。宁可证据为空，也不张冠李戴。
    """
    return [fact for fact in facts if fact.payload.get("code") == security.code]


def _build_result(
    request: AnalysisRequest,
    snapshot: MarketDataSnapshot,
    assessment: Any,
    facts: list[FactSnapshot],
    narrative: NarrativeRenderer,
) -> AnalysisResult:
    scores = {
        "fundamental": assessment.scores.fundamental,
        "technical": assessment.scores.technical,
        "risk": assessment.scores.risk,
        "suitability": assessment.scores.suitability,
        "total": assessment.scores.total,
    }
    result = AnalysisResult(
        request=request,
        action=assessment.action,
        data_quality=snapshot.quality.status,
        rule_version=assessment.rule_version,
        scores=scores,
        evidence_ids=[fact.fact_id for fact in facts],
        personalization_status=assessment.personalization_status,
        restrictions=list(assessment.restrictions),
    )
    rendered, report_mode = narrative.render(result)
    return result.model_copy(update={"narrative": rendered, "report_mode": report_mode})


def project_analysis_results(results: list[AnalysisResult]) -> dict[str, Any]:
    """把结论投影为公开响应/审计契约所需的字段。

    返回 ``stock_analysis``（按标的的结论摘要，供前端卡片）与 ``analysis_results``
    （结论全量，供审计持久化与结构化消费）。按结果自身的 ``request`` 归属代码，
    绝不把某一只股票的评级复制给其他标的；``technical_analysis`` 由专家基于 K 线
    另行计算，本层不返回，避免误导。
    """
    projected: dict[str, Any] = {}
    for result in results:
        request = result.request
        codes = request.stock_codes if request is not None else []
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
        "analysis_results": [result.model_dump(mode="json") for result in results],
    }


__all__ = ["evaluate", "project_analysis_results"]
