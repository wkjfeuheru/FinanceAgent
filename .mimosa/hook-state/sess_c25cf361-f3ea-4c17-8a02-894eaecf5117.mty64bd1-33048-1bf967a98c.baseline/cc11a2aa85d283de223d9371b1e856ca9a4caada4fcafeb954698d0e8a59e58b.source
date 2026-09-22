"""无状态确定性研究流水线。

结论的原子单位是**单只标的**：比较请求会为每只标的生成一条独立结论，
避免把某一只股票的评分与行动结论投影到其他标的上。单标的请求（含主题
筛选的逐成员调用）在行为上与此前完全一致。
"""

from __future__ import annotations

from typing import Any

from finance_agent.contracts import FactSnapshot
from finance_agent.research.contracts import (
    AnalysisRequest,
    AnalysisResult,
    MarketDataSnapshot,
    SecuritySnapshot,
)
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
        """执行单标的请求并返回唯一结论。"""
        result, _ = self.analyze_with_facts(request, user_profile=user_profile)
        return result

    def analyze_with_facts(
        self,
        request: AnalysisRequest,
        *,
        user_profile: dict[str, Any],
    ) -> tuple[AnalysisResult, list[FactSnapshot]]:
        """执行单标的请求并返回其结论与同一轮事实快照。"""
        self._require_single_security(request)
        results, facts = self.analyze_per_security(request, user_profile=user_profile)
        return results[0], facts

    def analyze_per_security(
        self,
        request: AnalysisRequest,
        *,
        user_profile: dict[str, Any],
    ) -> tuple[list[AnalysisResult], list[FactSnapshot]]:
        """按标的独立评估：每只标的各有一条结论，引用各自的证据事实。

        快照仍然按整个请求构建一次，因此跨标的质量门禁（例如报告期混用）
        会影响其中每一条结论，而不是只影响第一只股票。
        """
        prepared = self._with_profile(request, user_profile)
        snapshot, facts = self._snapshot_builder.build(prepared)
        if not snapshot.securities:
            # 无标的请求（例如主题级请求）保持单条结论语义。
            assessment = self._rule_engine.evaluate(snapshot, prepared)
            return [self._build_result(prepared, snapshot, assessment, facts)], facts

        results: list[AnalysisResult] = []
        for security in snapshot.securities:
            item_request = self._security_request(prepared, security)
            item_snapshot = snapshot.model_copy(
                update={"securities": [security], "request": item_request},
            )
            assessment = self._rule_engine.evaluate(item_snapshot, item_request)
            results.append(self._build_result(
                item_request, item_snapshot, assessment, self._evidence_for(security, facts),
            ))
        return results, facts

    @staticmethod
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

    @staticmethod
    def _security_request(request: AnalysisRequest, security: SecuritySnapshot) -> AnalysisRequest:
        """把请求收敛到单只标的（比较请求按单股结论描述）。"""
        return request.for_security(security.code)

    @staticmethod
    def _evidence_for(security: SecuritySnapshot, facts: list[FactSnapshot]) -> list[FactSnapshot]:
        """只引用该标的自己的证据事实；无匹配时返回空。

        曾经无匹配就退回**整轮**事实，会让该标的的结论引用其他标的的证据，
        污染逐标的归属与审计重放关联（比较请求下尤其明显）。宁可证据为空，
        也不张冠李戴。
        """
        return [fact for fact in facts if fact.payload.get("code") == security.code]

    def _build_result(
        self,
        request: AnalysisRequest,
        snapshot: MarketDataSnapshot,
        assessment: Any,
        facts: list[FactSnapshot],
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
        narrative, report_mode = self._narrative.render(result)
        return result.model_copy(update={"narrative": narrative, "report_mode": report_mode})

    @staticmethod
    def _require_single_security(request: AnalysisRequest) -> None:
        """多标的请求不得走单条结论入口，否则会掩盖其他标的。"""
        if len(request.stock_codes) > 1:
            raise ValueError("多标的比较必须使用 analyze_per_security 逐只生成结论")
