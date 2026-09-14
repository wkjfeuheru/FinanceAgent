"""产品领域子图：统一 DomainOutcome 与确定性 pipeline 调用。"""

from __future__ import annotations

from finance_agent.orchestrator.contracts import BusinessDomain, DomainTaskContext, PlanTask
from finance_agent.orchestrator.domains.product import ProductDomainDeps, build_product_domain_graph
from finance_agent.product_research.contracts import ProductResearchResult


class _FakePipeline:
    def analyze(self, request):
        return ProductResearchResult(
            kind=request.kind,
            product_codes=list(request.product_codes),
            assessments=[],
            report="暂无可用产品数据。",
            data_quality="critical_missing",
            personalization_status="research_candidate",
            evidence_ids=[],
            ambiguities=[],
        )


def _context(goal: str) -> DomainTaskContext:
    return DomainTaskContext(
        task=PlanTask(
            task_id="single:run-1:product_research",
            domain=BusinessDomain.PRODUCT_RESEARCH,
            goal=goal,
            instruction=goal,
            expected_output="domain_outcome",
        ),
        thread_id="v1:CUST1:conv-1",
        customer_id="CUST1",
        conversation_id="conv-1",
        user_message=goal,
    )


def test_product_domain_returns_uniform_outcome():
    graph = build_product_domain_graph(deps=ProductDomainDeps(pipeline=_FakePipeline()))

    outcome = graph.invoke({"context": _context("分析基金000001")})["domain_outcome"]

    assert outcome.domain == BusinessDomain.PRODUCT_RESEARCH
    assert outcome.structured_data["mode"] == "product_lookup"
    assert "product_analysis" in outcome.structured_data
    assert outcome.structured_data["product_analysis"]["type"] == "deep_dive"


def test_product_domain_pipeline_failure_returns_safe_limitations():
    class _Boom:
        def analyze(self, request):
            raise RuntimeError("db down")

    graph = build_product_domain_graph(deps=ProductDomainDeps(pipeline=_Boom()))

    outcome = graph.invoke({"context": _context("分析基金000001")})["domain_outcome"]

    assert outcome.status == "failed"
    assert outcome.limitations == ["product_pipeline_failed"]
