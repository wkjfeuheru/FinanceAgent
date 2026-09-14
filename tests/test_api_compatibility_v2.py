"""V2 响应投影必须保持既有 /api/chat 字段兼容，只追加新字段。"""

from __future__ import annotations

from finance_agent.orchestrator.contracts import BusinessDomain, DomainOutcome
from finance_agent.orchestrator.root_graph import RootGraphDependencies, build_root_graph, project_root_state

# 现有前端与 /api/chat 依赖的字段，V2 不得删除。
_LEGACY_KEYS = {
    "response",
    "task_plan",
    "task_dispatch",
    "tasks",
    "task_results",
    "user_profile",
    "stock_data",
    "fundamental_analysis",
    "stock_analysis",
    "technical_analysis",
    "analysis_results",
    "theme_screening",
    "theme_screening_status",
    "theme_candidates",
    "pending_leads",
    "personalization_status",
    "product_analysis",
    "market_insight",
    "compliance_result",
    "conversation_id",
    "run_status",
    "warnings",
}


class _FakeClassifier:
    def classify_intents(self, message: str, context_summary: str = "") -> dict:
        return {
            "intents": [{"intent": "stock_analysis", "query": message, "confidence": 0.99}],
            "uncertain_intents": [],
            "finance_related": True,
            "intent_source": "deepseek",
            "classification_error": {},
        }


def test_projection_preserves_all_legacy_keys():
    state = {
        "routing": {"domains": [BusinessDomain.STOCK_RESEARCH.value], "execution_mode": "domain_react"},
        "final_response": "已完成分析。",
        "run_status": "completed",
        "warnings": [],
        "domain_outcomes": {},
        "task_results": {},
    }

    projected = project_root_state(state, conversation_id="conv-1")

    assert _LEGACY_KEYS <= set(projected)
    assert projected["response"] == "已完成分析。"
    assert projected["task_plan"] == ["stock_research"]
    assert projected["conversation_id"] == "conv-1"


def test_projection_lifts_stock_structured_fields():
    outcome = DomainOutcome(
        task_id="single:run-1:stock_research",
        domain=BusinessDomain.STOCK_RESEARCH,
        status="success",
        summary="贵州茅台分析完成。",
        structured_data={
            "stock_data": {"600519": {"basic_info": {"name": "贵州茅台"}}},
            "stock_analysis": {"600519": {"rating": "推荐"}},
            "technical_analysis": {"600519": {"trend": "up"}},
            "analysis_results": [{"action": "关注"}],
        },
    )
    state = {
        "routing": {"domains": [BusinessDomain.STOCK_RESEARCH.value], "execution_mode": "domain_react"},
        "final_response": "贵州茅台分析完成。",
        "run_status": "completed",
        "domain_outcomes": {outcome.task_id: outcome.model_dump(mode="json")},
        "task_results": {outcome.task_id: outcome.model_dump(mode="json")},
    }

    projected = project_root_state(state)

    assert projected["stock_analysis"] == {"600519": {"rating": "推荐"}}
    assert projected["technical_analysis"] == {"600519": {"trend": "up"}}
    assert projected["analysis_results"] == [{"action": "关注"}]


def test_projection_reports_processing_task_ids():
    outcome = DomainOutcome(
        task_id="single:run-1:stock_research",
        domain=BusinessDomain.STOCK_RESEARCH,
        status="processing",
        summary="量化任务处理中。",
    )
    state = {
        "routing": {"domains": [BusinessDomain.STOCK_RESEARCH.value], "execution_mode": "domain_react"},
        "final_response": "量化任务处理中。",
        "run_status": "processing",
        "domain_outcomes": {outcome.task_id: outcome.model_dump(mode="json")},
    }

    projected = project_root_state(state)

    assert projected["run_status"] == "processing"
    assert projected["pending_task_ids"] == ["single:run-1:stock_research"]


def test_composite_plan_projection_merges_market_and_product():
    market = DomainOutcome(
        task_id="t-market",
        domain=BusinessDomain.MARKET_INSIGHT,
        status="success",
        summary="情绪偏暖。",
        structured_data={"market_insight": {"sentiment": "warm"}},
    )
    product = DomainOutcome(
        task_id="t-product",
        domain=BusinessDomain.PRODUCT_RESEARCH,
        status="success",
        summary="建议稳健型基金。",
        structured_data={"product_analysis": {"recommended": ["基金A"]}},
    )
    graph = build_root_graph(
        RootGraphDependencies(
            classifier=_FakeClassifierWithDomains(),
            plan_runner=lambda state, domains: [market, product],
        )
    )

    result = graph.invoke({"user_message": "市场情绪和基金产品怎么搭配", "run_id": "run-2"})
    projected = project_root_state(result)

    assert projected["market_insight"] == {"sentiment": "warm"}
    assert projected["product_analysis"] == {"recommended": ["基金A"]}
    assert projected["run_status"] == "completed"


class _FakeClassifierWithDomains:
    def classify_intents(self, message: str, context_summary: str = "") -> dict:
        return {
            "intents": [
                {"intent": "market_insight", "query": message, "confidence": 0.99},
                {"intent": "product_analysis", "query": message, "confidence": 0.99},
            ],
            "uncertain_intents": [],
            "finance_related": True,
            "intent_source": "deepseek",
            "classification_error": {},
        }
