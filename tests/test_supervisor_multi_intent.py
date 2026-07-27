import math

import finance_agent.agents.supervisor as supervisor_module
from finance_agent.agents.supervisor import SupervisorAgent


class FakeZeroShotClassifier:
    def __init__(self, result):
        self.result = result
        self.calls = []

    def predict(self, message, context="", pending_allocation=False):
        self.calls.append((message, context, pending_allocation))
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


def make_supervisor(payload):
    supervisor = object.__new__(SupervisorAgent)
    supervisor._zero_shot_classifier = FakeZeroShotClassifier(payload)
    return supervisor


def test_supervisor_builds_fixed_mdeberta_classifier(monkeypatch):
    captured = {}

    class RecordingClassifier:
        def __init__(self, model_name, **kwargs):
            captured["model_name"] = model_name
            captured["kwargs"] = kwargs

    monkeypatch.setattr(supervisor_module, "ZeroShotIntentClassifier", RecordingClassifier)
    agent = object.__new__(SupervisorAgent)
    agent._zero_shot_classifier = None

    _ = agent.zero_shot_classifier

    assert captured["model_name"] == "MoritzLaurer/mDeBERTa-v3-base-mnli-xnli"


def test_nli_is_the_first_and_only_intent_classifier():
    classifier = FakeZeroShotClassifier({
        "intents": [{
            "intent": "asset_allocation", "query": "安排资金",
            "confidence": 0.9, "reason": "NLI",
        }],
        "finance_related": True,
    })
    agent = object.__new__(SupervisorAgent)
    agent._zero_shot_classifier = classifier

    result = agent.plan_tasks("安排资金")

    assert classifier.calls == [("安排资金", "", False)]
    assert result["intent_source"] == "zero_shot"
    assert result["intents"][0]["execution_mode"] == "allocation"


def test_nli_returns_all_intents_and_deduplicates():
    supervisor = make_supervisor({
        "intents": [
            {"intent": "market_query", "query": "查看市场", "confidence": 0.91, "reason": "NLI"},
            {"intent": "stock_recommendation", "query": "寻找标的", "confidence": 0.95, "reason": "NLI"},
            {"intent": "asset_allocation", "query": "安排资金", "confidence": 0.93, "reason": "NLI"},
            {"intent": "stock_recommendation", "query": "比较候选", "confidence": 0.72, "reason": "NLI"},
        ],
        "finance_related": True,
    })

    result = supervisor.plan_tasks("组合请求")

    assert [item["intent"] for item in result["intents"]] == [
        "market_query", "stock_recommendation", "asset_allocation",
    ]
    assert result["intents"][0]["execution_mode"] == "unsupported"
    assert result["intents"][1]["execution_mode"] == "candidate_search"
    assert "比较候选" in result["intents"][1]["query"]
    assert result["task_plan"] == [
        "data_fetch", "fundamental_analysis", "asset_allocation", "compliance",
    ]


def test_emotion_and_market_query_both_execute():
    supervisor = make_supervisor({
        "intents": [
            {"intent": "casual_chat", "query": "回应情绪", "confidence": 0.9, "reason": "NLI"},
            {"intent": "market_query", "query": "查看市场", "confidence": 0.94, "reason": "NLI"},
        ],
        "finance_related": True,
    })

    result = supervisor.plan_tasks("组合请求")

    assert {item["intent"] for item in result["intents"]} == {"casual_chat", "market_query"}
    assert result["task_plan"] == ["casual_chat", "compliance"]


def test_nli_failure_uses_safe_fallback_without_keyword_recovery():
    supervisor = object.__new__(SupervisorAgent)
    supervisor._zero_shot_classifier = FakeZeroShotClassifier(RuntimeError("unavailable"))

    result = supervisor.plan_tasks("推荐股票并配置10万元")

    assert result["intent_source"] == "safe_fallback"
    assert result["finance_related"] is False
    assert result["intents"] == [{
        "intent": "casual_chat", "query": "推荐股票并配置10万元",
        "confidence": 0.0, "reason": "意图分类服务暂不可用",
        "execution_mode": "conversation", "requires_slot_extraction": False,
    }]


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
