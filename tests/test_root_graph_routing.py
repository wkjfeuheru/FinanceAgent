"""Root Graph 领域路由：三领域映射、执行模式与显式失败。"""

from __future__ import annotations

import pytest

from finance_agent.orchestrator.root_graph import (
    CLASSIFICATION_FAILED_RESPONSE,
    RootGraphDependencies,
    build_root_graph,
    classify_domains,
)


class _FakeClassifier:
    def __init__(self, payload: dict) -> None:
        self._payload = payload

    def classify_intents(self, message: str, context_summary: str = "") -> dict:
        return self._payload


def _payload(intents: list[str], *, error: dict | None = None, uncertain: list | None = None) -> dict:
    return {
        "intents": [{"intent": intent, "query": intent, "confidence": 0.99} for intent in intents],
        "uncertain_intents": uncertain or [],
        "finance_related": any(intent != "casual_chat" for intent in intents),
        "intent_source": "deepseek",
        "classification_error": error or {},
    }


@pytest.mark.parametrize(
    ("message", "intents", "domains", "mode"),
    [
        ("你好", ["casual_chat"], [], "conversation"),
        ("分析贵州茅台", ["stock_analysis"], ["stock_research"], "domain_react"),
        ("推荐一些股票", ["stock_recommendation"], ["stock_research"], "domain_react"),
        ("市场情绪怎么样", ["market_insight"], ["market_insight"], "domain_react"),
        ("市场情绪和基金产品怎么搭配", ["market_insight", "product_analysis"],
         ["market_insight", "product_research"], "plan_execute"),
    ],
)
def test_root_routes_by_domain_count(message, intents, domains, mode):
    decision = classify_domains(message, classifier=_FakeClassifier(_payload(intents)))

    assert [domain.value for domain in decision.domains] == domains
    assert decision.execution_mode == mode
    assert decision.error_code == ""


def test_classification_error_routes_to_explicit_clarify_not_conversation():
    decision = classify_domains(
        "随便说点什么",
        classifier=_FakeClassifier(_payload([], error={"error_code": "intent_unavailable"})),
    )

    assert decision.execution_mode == "clarify"
    assert decision.error_code == "intent_unavailable"
    assert decision.domains == []


def test_low_confidence_uncertainty_routes_to_clarify():
    decision = classify_domains(
        "那个东西怎么样",
        classifier=_FakeClassifier(
            _payload([], uncertain=[{"intent": "stock_analysis", "confidence": 0.4, "query": "那个"}])
        ),
    )

    assert decision.execution_mode == "clarify"
    assert decision.error_code == ""


def test_root_graph_creates_deterministic_single_domain_task_id():
    captured = {}

    def domain_runner(context):
        captured["task_id"] = context.task.task_id
        from finance_agent.orchestrator.contracts import DomainOutcome

        return DomainOutcome(
            task_id=context.task.task_id,
            domain=context.task.domain,
            status="success",
            summary="已完成分析。",
        )

    graph = build_root_graph(
        RootGraphDependencies(
            classifier=_FakeClassifier(_payload(["stock_analysis"])),
            domain_runner=domain_runner,
        )
    )
    result = graph.invoke({"user_message": "分析贵州茅台", "run_id": "run-1", "customer_id": "CUST1"})

    assert captured["task_id"] == "single:run-1:stock_research"
    assert result["single_task_id"] == "single:run-1:stock_research"
    assert result["run_status"] == "completed"


def test_root_graph_classification_failure_is_not_silently_treated_as_chat():
    graph = build_root_graph(
        RootGraphDependencies(
            classifier=_FakeClassifier(_payload([], error={"error_code": "intent_unavailable"})),
            conversation_runner=lambda state: {"final_response": "不应被调用", "status": "success"},
        )
    )
    result = graph.invoke({"user_message": "随便", "run_id": "run-1"})

    assert result["run_status"] == "failed"
    assert result["final_response"] == CLASSIFICATION_FAILED_RESPONSE
    assert "classification_error:intent_unavailable" in result["warnings"]


def test_root_graph_conversation_mode_delegates_to_conversation_runner():
    graph = build_root_graph(
        RootGraphDependencies(
            classifier=_FakeClassifier(_payload(["casual_chat"])),
            conversation_runner=lambda state: {"final_response": "你好，我是投顾助手。", "status": "success"},
        )
    )
    result = graph.invoke({"user_message": "你好", "run_id": "run-1"})

    assert result["final_response"] == "你好，我是投顾助手。"
    assert result["run_status"] == "completed"


def test_missing_domain_runner_fails_explicitly_instead_of_silent_success():
    graph = build_root_graph(RootGraphDependencies(classifier=_FakeClassifier(_payload(["stock_analysis"]))))
    result = graph.invoke({"user_message": "分析贵州茅台", "run_id": "run-1", "customer_id": "CUST1"})

    assert result["run_status"] == "failed"
    assert "domain_runner_unavailable:stock_research" in result["warnings"]
