"""运行时控制回归测试：停止生成、澄清路由、admin 清全库门控。"""

import threading

import pytest
from fastapi import HTTPException

from finance_agent.orchestration.graphs.supervisor import (
    SupervisorDependencies,
    build_supervisor_graph,
    classify_domains,
    run_of,
)


class _FakeClassifier:
    """既是领域分类器（classify_intents），也是底层意图模型（classify）。"""

    def __init__(self, payload):
        self.payload = payload

    def classify(self, message, context_summary=""):
        return self.payload

    def classify_intents(self, message, context_summary=""):
        return self.payload


def test_request_stop_and_is_stopped():
    from finance_agent.application.advisor import AdvisorSystem

    system = object.__new__(AdvisorSystem)
    system._stop_requests = {}
    system._active_runs = {}
    system._stop_lock = threading.Lock()

    system._active_runs["run-1"] = "conv-1"
    assert system.request_stop(run_id="run-1") is True
    assert system._is_stopped("conv-1") is True
    assert system._is_stopped("conv-2") is False
    assert system.request_stop(conversation_id="conv-2") is True
    assert system._is_stopped("conv-2") is True
    assert system.request_stop() is False  # 无标识不记录


def test_low_confidence_intent_routes_to_clarification():
    """低置信度且缺信息时输出结构化澄清，不进入执行子图。"""
    classifier = _FakeClassifier({
        "intents": [],
        "uncertain_intents": [{
            "intent": "stock_recommendation", "query": "那只股票", "confidence": 0.5,
            "execution_mode": "candidate_search",
            "clarification_question": "您想分析具体哪只股票？",
        }],
        "finance_related": True,
        "classification_error": {},
    })

    decision = classify_domains("帮我看看那只股票", classifier=classifier)

    assert decision.execution_mode == "clarify"
    assert decision.domains == []


def test_classification_marks_error_when_no_valid_intents():
    """模型返回了 intents 但全部被过滤：必须标记分类失败（否则落含糊回复）。"""
    from finance_agent.orchestration.routing.intent import IntentClassifier

    classifier = IntentClassifier(classifier=_FakeClassifier({
        "intents": [{"intent": "unknown_intent", "query": "x", "confidence": 0.99, "evidence": "x"}],
        "finance_related": True,
    }))

    result = classifier.classify_intents("随便问问")

    assert result["intents"] == []
    assert result["classification_error"], "空有效意图必须带非空错误，供编排层走兜底"
    assert result["classification_error"]["cause"] == "no_valid_intents"


def test_clarification_state_does_not_execute_subgraphs():
    """低置信度澄清：根图输出澄清文案，不调用任何领域执行器。"""
    called = {"domain": False}

    def domain_runner(context):
        called["domain"] = True
        raise AssertionError("澄清分支不得执行领域子图")

    graph = build_supervisor_graph(
        SupervisorDependencies(
            classifier=_FakeClassifier({
                "intents": [],
                "uncertain_intents": [{"intent": "stock_analysis", "confidence": 0.4, "query": "那个"}],
                "finance_related": True,
                "classification_error": {},
            }),
            domain_runner=domain_runner,
        )
    )

    result = graph.invoke({"user_message": "那个怎么样", "run_id": "run-1"})

    assert run_of(result)["run_status"] == "completed"
    assert not called["domain"]


def test_handle_message_output_includes_stock_structured_fields(monkeypatch):
    """回归 P1a：API 输出必须携带 analysis_results/technical_analysis 等结构化字段。"""
    from finance_agent.orchestration.contracts import BusinessDomain, DomainOutcome
    from finance_agent.application.advisor import AdvisorSystem

    system = object.__new__(AdvisorSystem)
    system._workflow_lock = threading.RLock()
    system._stop_lock = threading.Lock()
    system._stop_requests = {}
    system._active_runs = {}
    system._progress_lock = threading.Lock()
    system._progress_callbacks = {}
    system._trace_lock = threading.Lock()
    system._trace_sequences = {}
    system._progress_context = type("Ctx", (), {"callback": None})()
    system.audit = type("A", (), {
        "is_available": lambda self: False,
        "create_run": lambda *a, **k: None,
        "complete_run": lambda *a, **k: None,
    })()
    system.memory = type("M", (), {
        "window_size": 10,
        "load_context": lambda self, c, conv, fb: {
            "profile": {}, "context_text": "", "sliding_window": [],
        },
        "append_window_message": lambda *a, **k: None,
        "update_profile_from_result": lambda *a, **k: None,
    })()
    system.get_checkpoint_conversation_messages = lambda *a, **k: []
    system._emit_progress = lambda *a, **k: None
    system._trace_agent = lambda *a, **k: None
    monkeypatch.setattr(
        "finance_agent.application.advisor.get_database",
        lambda: type("DB", (), {"append_conversation_message": lambda *a, **k: None})(),
    )

    class _Classifier:
        def classify_intents(self, message, context_summary=""):
            return {
                "intents": [{"intent": "stock_analysis", "query": message, "confidence": 0.99}],
                "uncertain_intents": [], "finance_related": True,
                "intent_source": "deepseek", "classification_error": {},
            }

    def domain_runner(context):
        return DomainOutcome(
            task_id=context.task.task_id,
            domain=BusinessDomain.STOCK_RESEARCH,
            status="success",
            summary="已完成 600519 的分析。",
            structured_data={
                "stock_data": {"600519": {"basic_info": {"name": "贵州茅台"}}},
                "stock_analysis": {"600519": {"rating": "推荐"}},
                "technical_analysis": {"600519": {"trend": "up"}},
                "analysis_results": [{"action": "关注", "rule_version": "research_rules/v1.2"}],
            },
        )

    system.supervisor = build_supervisor_graph(
        SupervisorDependencies(classifier=_Classifier(), domain_runner=domain_runner)
    )

    output = system.handle_message("分析600519", conversation_id="proj-test")

    assert output["analysis_results"][0]["rule_version"] == "research_rules/v1.2"
    assert output["technical_analysis"] == {"600519": {"trend": "up"}}
    assert output["stock_analysis"] == {"600519": {"rating": "推荐"}}


def test_clear_records_admin_gate(monkeypatch):
    from finance_agent.api import dependencies as deps
    from finance_agent.api.routers import admin as r

    monkeypatch.setattr(deps, "ADMIN_CUSTOMER_IDS", set())

    class _FakeRequest:
        headers = {"Authorization": "Bearer good-token"}

    class _FakeStore:
        def verify_token(self, token):
            return "CUST000001"

    monkeypatch.setattr(deps, "get_user_store", lambda: _FakeStore())

    with pytest.raises(HTTPException) as exc:
        r.clear_records(_FakeRequest(), customer_id=None, keep_users=True)
    assert exc.value.status_code == 403
