import math

import finance_agent.agents.supervisor as supervisor_module
from finance_agent.agents.supervisor import SupervisorAgent


class FakeGLMClassifier:
    def __init__(self, result):
        self.result = result
        self.calls = []

    def classify(
        self, message, context_summary="", pending_allocation=False, pending_fields=None,
    ):
        self.calls.append((message, context_summary, pending_allocation, pending_fields or []))
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


def make_supervisor(payload):
    supervisor = object.__new__(SupervisorAgent)
    supervisor._intent_classifier = FakeGLMClassifier(payload)
    return supervisor


def test_supervisor_builds_configured_glm_classifier(monkeypatch):
    captured = {}

    class RecordingClassifier:
        def __init__(self, **kwargs):
            captured.update(kwargs)

    monkeypatch.setattr(supervisor_module, "GLMIntentClassifier", RecordingClassifier)
    agent = object.__new__(SupervisorAgent)
    agent._intent_classifier = None

    _ = agent.intent_classifier

    assert captured["model"] == supervisor_module.ZHIPU_INTENT_MODEL
    assert captured["base_url"] == supervisor_module.ZHIPU_BASE_URL


def test_glm_is_the_first_and_only_intent_classifier():
    classifier = FakeGLMClassifier({
        "intents": [{
            "intent": "asset_allocation", "query": "安排资金",
            "confidence": 0.9, "reason": "GLM", "evidence": "安排资金",
            "execution_mode": "allocation", "requires_slot_extraction": True,
        }],
        "finance_related": True,
    })
    agent = object.__new__(SupervisorAgent)
    agent._intent_classifier = classifier

    result = agent.plan_tasks("安排资金")

    assert classifier.calls == [("安排资金", "", False, [])]
    assert result["intent_source"] == "glm"
    assert result["intents"][0]["execution_mode"] == "allocation"


def test_nli_returns_all_intents_and_deduplicates():
    supervisor = make_supervisor({
        "intents": [
            {"intent": "market_query", "query": "查看市场", "confidence": 0.91, "reason": "GLM", "evidence": "查看市场", "execution_mode": "market_overview"},
            {"intent": "stock_recommendation", "query": "寻找标的", "confidence": 0.95, "reason": "GLM", "evidence": "寻找标的", "execution_mode": "candidate_search"},
            {"intent": "asset_allocation", "query": "安排资金", "confidence": 0.93, "reason": "GLM", "evidence": "安排资金", "execution_mode": "allocation"},
            {"intent": "stock_recommendation", "query": "比较候选", "confidence": 0.72, "reason": "GLM", "evidence": "比较候选", "execution_mode": "security_comparison"},
        ],
        "finance_related": True,
    })

    result = supervisor.plan_tasks("组合请求")

    assert [item["intent"] for item in result["intents"]] == [
        "market_query", "stock_recommendation", "asset_allocation",
    ]
    assert result["intents"][0]["execution_mode"] == "market_overview"
    assert result["intents"][1]["execution_mode"] == "candidate_search"
    assert "比较候选" in result["intents"][1]["query"]
    assert result["task_plan"] == [
        "data_fetch", "fundamental_analysis", "asset_allocation", "compliance",
    ]


def test_emotion_and_market_query_both_execute():
    supervisor = make_supervisor({
        "intents": [
            {"intent": "casual_chat", "query": "回应情绪", "confidence": 0.9, "reason": "GLM", "evidence": "回应情绪", "execution_mode": "conversation"},
            {"intent": "market_query", "query": "查看市场", "confidence": 0.94, "reason": "GLM", "evidence": "查看市场", "execution_mode": "market_overview"},
        ],
        "finance_related": True,
    })

    result = supervisor.plan_tasks("组合请求")

    assert {item["intent"] for item in result["intents"]} == {"casual_chat", "market_query"}
    assert result["task_plan"] == ["casual_chat", "compliance"]


def test_nli_failure_returns_classification_error_without_fake_chat_intent():
    supervisor = object.__new__(SupervisorAgent)
    supervisor._intent_classifier = FakeGLMClassifier(RuntimeError("unavailable"))

    result = supervisor.plan_tasks("推荐股票并配置10万元")

    assert result["intent_source"] == "classification_error"
    assert result["intents"] == []
    assert result["task_plan"] == ["compliance"]


def test_empty_nli_result_uses_safe_fallback():
    supervisor = make_supervisor({"intents": [], "finance_related": False})
    result = supervisor.plan_tasks("任意文本")
    assert result["intent_source"] == "safe_fallback"
    assert [item["intent"] for item in result["intents"]] == ["casual_chat"]


def test_invalid_execution_mode_does_not_infer_route_from_query():
    supervisor = make_supervisor({
        "intents": [{
            "intent": "market_query", "query": "贵州茅台最近走势",
            "confidence": 0.95, "reason": "NLI", "execution_mode": "unknown",
        }],
        "finance_related": True,
    })
    result = supervisor.plan_tasks("贵州茅台最近走势")
    assert result["intents"][0]["execution_mode"] == "unsupported"
    assert result["intents"][0]["requires_slot_extraction"] is False
    assert result["task_plan"] == ["compliance"]


def test_non_finite_confidence_is_rejected():
    supervisor = make_supervisor({
        "intents": [{
            "intent": "asset_allocation", "query": "安排资金",
            "confidence": math.nan, "reason": "非法置信度",
        }],
        "finance_related": True,
    })
    result = supervisor.plan_tasks("安排资金")
    assert result["intent_source"] == "safe_fallback"
    assert [item["intent"] for item in result["intents"]] == ["casual_chat"]


def test_pending_fields_are_passed_to_glm_classifier():
    classifier = FakeGLMClassifier({
        "intents": [{
            "intent": "asset_allocation", "query": "2万元，稳健，持有一年",
            "confidence": 0.98, "reason": "补充等待字段", "evidence": "2万元",
            "execution_mode": "allocation", "requires_slot_extraction": True,
        }],
        "finance_related": True,
    })
    agent = object.__new__(SupervisorAgent)
    agent._intent_classifier = classifier

    agent.plan_tasks(
        "2万元，稳健，持有一年", "此前正在配置", True,
        ["budget_amount", "risk_preference", "holding_period"],
    )

    assert classifier.calls == [(
        "2万元，稳健，持有一年", "此前正在配置", True,
        ["budget_amount", "risk_preference", "holding_period"],
    )]
