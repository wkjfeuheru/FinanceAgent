"""股票领域子图：模式选择、统一 DomainOutcome 与确定性工具执行。"""

from __future__ import annotations

from finance_agent.orchestrator.contracts import DomainTaskContext, PlanTask, BusinessDomain
from finance_agent.orchestrator.domains.stock import StockDeps, build_stock_domain_graph
from finance_agent.research.contracts import Action, AnalysisKind, AnalysisRequest, AnalysisResult


def _context(goal: str) -> DomainTaskContext:
    return DomainTaskContext(
        task=PlanTask(
            task_id="single:run-1:stock_research",
            domain=BusinessDomain.STOCK_RESEARCH,
            goal=goal,
            instruction=goal,
            expected_output="domain_outcome",
        ),
        thread_id="v1:CUST1:conv-1",
        customer_id="CUST1",
        conversation_id="conv-1",
        user_message=goal,
    )


class _FakePipeline:
    def analyze_per_security(self, request: AnalysisRequest, *, user_profile):
        results = [
            AnalysisResult(
                request=AnalysisRequest(kind=AnalysisKind.SINGLE_STOCK, stock_codes=[code]),
                action=Action.WATCH,
                data_quality="complete",
                rule_version="research_rules/v1",
                narrative=f"{code} 研究结论：观望。",
            )
            for code in request.stock_codes
        ]
        return results, []


def test_stock_domain_selects_candidate_search_for_recommendation():
    graph = build_stock_domain_graph(StockDeps())

    outcome = graph.invoke({"context": _context("推荐一些股票")})["domain_outcome"]

    assert outcome.structured_data["mode"] == "candidate_search"
    assert outcome.domain == BusinessDomain.STOCK_RESEARCH


def test_stock_domain_returns_uniform_outcome_with_analysis_results():
    graph = build_stock_domain_graph(
        StockDeps(pipeline=_FakePipeline(), injected_pipeline=True)
    )

    outcome = graph.invoke({"context": _context("分析600519")})["domain_outcome"]

    assert outcome.domain == BusinessDomain.STOCK_RESEARCH
    assert outcome.task_id == "single:run-1:stock_research"
    assert outcome.status in {"success", "partial"}
    assert "600519" in outcome.structured_data["stock_analysis"]
    assert outcome.structured_data["mode"] == "single_analysis"
