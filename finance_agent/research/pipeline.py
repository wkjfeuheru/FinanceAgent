"""无状态确定性研究流水线。"""

from __future__ import annotations

from typing import Any

from finance_agent.research.contracts import AnalysisRequest, AnalysisResult
from finance_agent.research.narrative import NarrativeRenderer
from finance_agent.research.rule_engine import RuleEngine
from finance_agent.research.snapshot_builder import SnapshotBuilder


class ResearchPipeline:
    """按请求构建快照、运行规则并生成结构化结果。"""

    def __init__(
        self,
        *,
        snapshot_builder: SnapshotBuilder,
        rule_engine: RuleEngine,
        narrative: NarrativeRenderer | None = None,
    ):
        self._snapshot_builder = snapshot_builder
        self._rule_engine = rule_engine
        self._narrative = narrative or NarrativeRenderer()

    def analyze(
        self,
        request: AnalysisRequest,
        *,
        user_profile: dict[str, Any],
    ) -> AnalysisResult:
        """执行一次不共享调用状态的研究。"""
        result, _ = self.analyze_with_facts(request, user_profile=user_profile)
        return result

    def analyze_with_facts(
        self,
        request: AnalysisRequest,
        *,
        user_profile: dict[str, Any],
    ) -> tuple[AnalysisResult, list[Any]]:
        """执行研究并返回同一轮结果引用的不可变事实快照。"""
        request = request.model_copy(update={
            "profile_complete": bool(
                request.profile_complete
                or (
                    str((user_profile or {}).get("risk_preference", "")).strip()
                    and str((user_profile or {}).get("holding_period", "")).strip()
                )
            )
        })
        snapshot, facts = self._snapshot_builder.build(request)
        assessment = self._rule_engine.evaluate(snapshot, request)
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
        narrative, report_mode = self._narrative.render(result)
        return (
            result.model_copy(update={"narrative": narrative, "report_mode": report_mode}),
            facts,
        )
