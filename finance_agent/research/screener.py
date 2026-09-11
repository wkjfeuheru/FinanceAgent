"""仅使用已审核有效成员的确定性主题筛选。"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from finance_agent.research.contracts import AnalysisRequest, AnalysisResult
from finance_agent.research.pipeline import ResearchPipeline
from finance_agent.research.rule_engine import RuleEngine
from finance_agent.research.snapshot_builder import SnapshotBuilder
from finance_agent.research.theme_repository import ThemeRepository


@dataclass(frozen=True)
class ThemeCandidate:
    stock_code: str
    industry: str
    action: str
    score: float | None
    summary: str
    evidence_ids: list[str]
    rule_version: str = ""
    data_quality: str = ""
    scores: dict[str, float | None] = field(default_factory=dict)


@dataclass(frozen=True)
class ThemeScreeningResult:
    status: str
    personalization_status: str
    ranked_candidates: list[ThemeCandidate] = field(default_factory=list)
    pending_leads: list[dict[str, Any]] = field(default_factory=list)
    request: AnalysisRequest | None = None
    active_members: list[dict[str, Any]] = field(default_factory=list)
    exclusions: list[dict[str, Any]] = field(default_factory=list)
    analysis_results: list[AnalysisResult] = field(default_factory=list)
    facts: list[Any] = field(default_factory=list)


class ThemeScreener:
    def __init__(self, themes: ThemeRepository, gateway: Any):
        self._themes = themes
        self._gateway = gateway

    def screen(self, request: AnalysisRequest, profile: dict[str, Any]) -> ThemeScreeningResult:
        if request.theme_id is None:
            raise ValueError("主题筛选请求缺少 theme_id")
        now = datetime.now(timezone.utc)
        active = self._themes.active_members(request.theme_id, now)
        pending = [
            {"stock_code": lead.stock_code, "industry": lead.industry,
             "source_name": lead.source_name, "source_uri": lead.source_uri,
             "evidence_excerpt": lead.evidence_excerpt, "label": "待核验研究线索"}
            for lead in self._themes.pending_leads(request.theme_id)
        ]
        complete = bool(str(profile.get("risk_preference", "")).strip() and str(profile.get("holding_period", "")).strip())
        status = "personalized" if complete else "research_candidate"
        active_manifest = [member.model_dump(mode="json") for member in active]
        if len(active) < 5:
            return ThemeScreeningResult(
                "insufficient_active_coverage", status, pending_leads=pending,
                request=request, active_members=active_manifest,
            )

        pipeline = ResearchPipeline(
            snapshot_builder=SnapshotBuilder(self._gateway),
            rule_engine=RuleEngine.default(),
        )
        candidates: list[ThemeCandidate] = []
        analysis_results: list[AnalysisResult] = []
        facts: list[Any] = []
        exclusions: list[dict[str, Any]] = []
        for member in active:
            item_request = request.model_copy(update={"stock_codes": [member.stock_code], "profile_complete": complete})
            result, item_facts = pipeline.analyze_with_facts(item_request, user_profile=profile)
            facts.extend(item_facts)
            if result.action.value == "数据不足":
                exclusions.append({
                    "stock_code": member.stock_code,
                    "reason": result.data_quality,
                    "fact_ids": list(result.evidence_ids),
                })
                continue
            analysis_results.append(result)
            candidates.append(ThemeCandidate(
                stock_code=member.stock_code, industry=member.industry,
                action=result.action.value, score=result.scores.get("total"),
                summary=result.narrative, evidence_ids=result.evidence_ids,
                rule_version=result.rule_version, data_quality=result.data_quality,
                scores=dict(result.scores),
            ))
        candidates.sort(key=lambda item: (item.score is not None, item.score or -1), reverse=True)
        selected: list[ThemeCandidate] = []
        per_industry: dict[str, int] = {}
        for item in candidates:
            if per_industry.get(item.industry, 0) >= 2:
                continue
            selected.append(item)
            per_industry[item.industry] = per_industry.get(item.industry, 0) + 1
            if len(selected) == 5:
                break
        if len(selected) < 3:
            return ThemeScreeningResult(
                "insufficient_eligible_coverage", status, pending_leads=pending,
                request=request, active_members=active_manifest, exclusions=exclusions,
                analysis_results=analysis_results, facts=facts,
            )
        return ThemeScreeningResult(
            "complete", status, selected, pending, request, active_manifest,
            exclusions, analysis_results, facts,
        )
