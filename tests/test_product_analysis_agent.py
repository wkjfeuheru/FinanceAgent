"""产品领域确定性流水线接入测试（面向领域模块）。"""

from __future__ import annotations

from finance_agent.product_research.contracts import (
    ProductAssessment,
    ProductFieldEvidence,
    ProductResearchResult,
)
from finance_agent.orchestrator.domains.product import (
    ProductDomainDeps,
    build_product_request,
    invoke_product,
)


class _StaticPipeline:
    def __init__(self, result: ProductResearchResult):
        self.result = result
        self.requests = []

    def analyze(self, request):
        self.requests.append(request)
        return self.result


def _empty_result() -> ProductResearchResult:
    return ProductResearchResult(
        kind="comparison",
        report="产品库暂无该产品数据。",
        data_quality="critical_missing",
    )


def _one_product_result() -> ProductResearchResult:
    evidence = ProductFieldEvidence(
        field="risk_level", value="R2", fact_id="product:P001:risk_level",
    )
    assessment = ProductAssessment(
        code="P001",
        name="示例基金",
        evidences={"risk_level": evidence},
        risk_level="R2",
        risk_source="产品库",
        suitability_status="not_evaluated",
        usable_for_comparison=False,
    )
    return ProductResearchResult(
        kind="single",
        product_codes=["P001"],
        assessments=[assessment],
        report="示例基金（P001）\n风险等级：R2。",
        data_quality="complete",
    )


def test_product_domain_does_not_construct_snapshot_from_message_code():
    pipeline = _StaticPipeline(_empty_result())
    state = invoke_product(ProductDomainDeps(pipeline=pipeline), {
        "user_message": "请分析110011基金",
        "intent_slots": {"product_analysis": {"product_codes": ["110011"]}},
        "user_profile": {},
        "facts": [],
    })

    assert pipeline.requests[0].product_codes == ["110011"]
    assert state["product_analysis"]["products"] == []
    assert state["intent_results"]["product_analysis"]["status"] == "degraded"


def test_product_domain_writes_typed_result_and_product_facts():
    pipeline = _StaticPipeline(_one_product_result())
    state = invoke_product(ProductDomainDeps(pipeline=pipeline), {
        "user_message": "分析示例基金",
        "intent_slots": {"product_analysis": {"product_names": ["示例基金"]}},
        "user_profile": {},
        "facts": [],
    })

    payload = state["product_analysis"]
    assert payload["schema_version"] == "product_research.v1"
    assert payload["product_codes"] == ["P001"]
    assert payload["evidence_ids"] == ["product:P001:risk_level"]
    assert [fact.fact_id for fact in state["facts"]] == ["product:P001:risk_level"]
    assert state["agent_response"].startswith("示例基金")


def test_product_request_reads_profile_from_task_context_when_state_projection_is_minimal():
    request = build_product_request({
        "user_message": "分析示例基金",
        "task_context": {
            "slots": {"product_codes": ["P001"]},
            "user_profile": {"risk_preference": "稳健", "holding_period": "long"},
        },
        "facts": [],
    })

    assert request.product_codes == ["P001"]
    assert request.profile == {"risk_preference": "稳健", "holding_period": "long"}
