import json

import finance_agent.agents.supervisor as supervisor_module
from finance_agent.agents.supervisor import SupervisorAgent


class FakeChain:
    def __init__(self, value):
        self.value = value

    def invoke(self, _payload):
        return self.value


class ExplodingChain:
    def invoke(self, _payload):
        raise AssertionError("classification LLM must not be invoked")


class RaisingChain:
    def invoke(self, _payload):
        raise RuntimeError("primary unavailable")


class FakeZeroShotClassifier:
    def __init__(self, result):
        self.result = result
        self.calls = []

    def predict(self, message, context="", pending_allocation=False):
        self.calls.append((message, context, pending_allocation))
        return self.result


class ImmediateExecutor:
    def submit(self, function):
        function()


def make_supervisor(payload):
    supervisor = object.__new__(SupervisorAgent)
    supervisor._intent_chain = FakeChain(json.dumps(payload, ensure_ascii=False))
    return supervisor


def test_model_returns_all_intents_and_deduplicates():
    supervisor = make_supervisor({
        "intents": [
            {"intent": "market_query", "query": "查询半导体板块表现", "confidence": 0.91, "reason": "行情", "execution_mode": "market_overview", "requires_slot_extraction": False},
            {"intent": "stock_recommendation", "query": "推荐半导体股票", "confidence": 0.95, "reason": "推荐", "execution_mode": "candidate_search", "requires_slot_extraction": False},
            {"intent": "asset_allocation", "query": "配置20万元", "confidence": 0.93, "reason": "配置", "execution_mode": "allocation", "requires_slot_extraction": True},
            {"intent": "stock_recommendation", "query": "筛选龙头", "confidence": 0.72, "reason": "重复同类", "execution_mode": "candidate_search", "requires_slot_extraction": False},
        ],
        "finance_related": True,
    })
    result = supervisor.plan_tasks("看看半导体板块，推荐股票并配置20万元")
    assert [item["intent"] for item in result["intents"]] == [
        "market_query", "stock_recommendation", "asset_allocation",
    ]
    recommendation = result["intents"][1]
    assert "推荐半导体股票" in recommendation["query"]
    assert "筛选龙头" in recommendation["query"]
    assert result["task_plan"] == [
        "data_fetch", "fundamental_analysis", "asset_allocation", "compliance",
    ]


def test_emotion_and_market_query_both_execute():
    supervisor = make_supervisor({
        "intents": [
            {"intent": "casual_chat", "query": "回应亏损焦虑", "confidence": 0.9, "reason": "情绪", "execution_mode": "conversation", "requires_slot_extraction": False},
            {"intent": "market_query", "query": "查询茅台走势", "confidence": 0.94, "reason": "行情", "execution_mode": "security_analysis", "requires_slot_extraction": True},
        ],
        "finance_related": True,
    })
    result = supervisor.plan_tasks("最近亏得很焦虑，帮我看看茅台最近走势")
    assert {item["intent"] for item in result["intents"]} == {
        "casual_chat", "market_query",
    }
    assert "casual_chat" in result["task_plan"]
    assert "data_fetch" in result["task_plan"]


def test_invalid_model_output_without_nli_uses_safe_fallback():
    supervisor = object.__new__(SupervisorAgent)
    supervisor._intent_chain = FakeChain("not-json")
    result = supervisor.plan_tasks("推荐三只银行股，用10万元做稳健配置")
    assert [item["intent"] for item in result["intents"]] == ["casual_chat"]
    assert result["intent_source"] == "safe_fallback"


def test_low_confidence_intents_are_not_executed():
    supervisor = make_supervisor({
        "intents": [
            {"intent": "market_query", "query": "可能查行情", "confidence": 0.4, "reason": "不确定", "execution_mode": "security_analysis", "requires_slot_extraction": True},
        ],
        "finance_related": True,
    })
    result = supervisor.plan_tasks("随便聊聊投资")
    assert [item["intent"] for item in result["intents"]] == ["casual_chat"]
    assert result["intent_source"] == "safe_fallback"


def test_zero_shot_mode_does_not_invoke_llm(monkeypatch):
    classifier = FakeZeroShotClassifier({
        "intents": [{
            "intent": "stock_recommendation",
            "query": "推荐银行股",
            "confidence": 0.9,
            "reason": "多语言 NLI 零样本分类",
        }],
        "finance_related": True,
    })
    agent = object.__new__(SupervisorAgent)
    agent._zero_shot_classifier = classifier
    agent._intent_chain = ExplodingChain()
    monkeypatch.setattr(supervisor_module, "INTENT_CLASSIFIER_MODE", "zero_shot")

    result = agent.plan_tasks("推荐银行股")

    assert [item["intent"] for item in result["intents"]] == ["stock_recommendation"]
    assert result["intent_source"] in {"zero_shot", "zero_shot+rule"}


def test_zero_shot_failure_uses_safe_fallback_without_llm(monkeypatch):
    class BrokenClassifier:
        def predict(self, *_args, **_kwargs):
            raise RuntimeError("broken model")

    agent = object.__new__(SupervisorAgent)
    agent._zero_shot_classifier = BrokenClassifier()
    agent._intent_chain = ExplodingChain()
    monkeypatch.setattr(supervisor_module, "INTENT_CLASSIFIER_MODE", "zero_shot")

    result = agent.plan_tasks("推荐三只银行股，用10万元做稳健配置")

    assert [item["intent"] for item in result["intents"]] == ["casual_chat"]
    assert result["intent_source"] == "safe_fallback"


def test_empty_zero_shot_result_does_not_restore_business_intent_from_keywords(monkeypatch):
    agent = object.__new__(SupervisorAgent)
    agent._zero_shot_classifier = FakeZeroShotClassifier({
        "intents": [],
        "finance_related": False,
    })
    agent._intent_chain = ExplodingChain()
    monkeypatch.setattr(supervisor_module, "INTENT_CLASSIFIER_MODE", "zero_shot")

    result = agent.plan_tasks("推荐银行股")

    assert [item["intent"] for item in result["intents"]] == ["casual_chat"]
    assert result["finance_related"] is False


def test_shadow_mode_keeps_llm_primary_and_logs_zero_shot(monkeypatch):
    agent = make_supervisor({
        "intents": [{
            "intent": "market_query",
            "query": "查看茅台走势",
            "confidence": 0.9,
            "reason": "行情",
            "execution_mode": "security_analysis",
            "requires_slot_extraction": True,
        }],
        "finance_related": True,
    })
    classifier = FakeZeroShotClassifier({
        "intents": [{
            "intent": "stock_recommendation",
            "query": "查看茅台走势",
            "confidence": 0.8,
            "reason": "多语言 NLI 零样本分类",
        }],
        "finance_related": True,
        "latency_ms": 1.0,
    })
    agent._zero_shot_classifier = classifier
    monkeypatch.setattr(supervisor_module, "INTENT_CLASSIFIER_MODE", "shadow")
    monkeypatch.setattr(supervisor_module, "_SHADOW_EXECUTOR", ImmediateExecutor())

    result = agent.plan_tasks("查看茅台走势")

    assert [item["intent"] for item in result["intents"]] == ["market_query"]
    assert result["intent_source"] == "model"
    assert classifier.calls == [("查看茅台走势", "", False)]


def test_supervisor_normalizes_execution_plan_without_reading_query_keywords():
    supervisor = make_supervisor({
        "intents": [{
            "intent": "stock_recommendation",
            "query": "给我一些方向",
            "confidence": 0.95,
            "reason": "候选搜索",
            "execution_mode": "candidate_search",
            "requires_slot_extraction": False,
        }],
        "finance_related": True,
    })

    result = supervisor.plan_tasks("给我一些方向")

    assert result["intents"][0]["execution_mode"] == "candidate_search"
    assert result["intents"][0]["requires_slot_extraction"] is False
    assert result["task_plan"] == [
        "data_fetch", "fundamental_analysis", "compliance",
    ]


def test_invalid_execution_mode_does_not_infer_route_from_query():
    supervisor = make_supervisor({
        "intents": [{
            "intent": "market_query",
            "query": "贵州茅台最近走势",
            "confidence": 0.95,
            "reason": "行情",
            "execution_mode": "unknown",
            "requires_slot_extraction": True,
        }],
        "finance_related": True,
    })

    result = supervisor.plan_tasks("贵州茅台最近走势")

    assert result["intents"][0]["execution_mode"] == "unsupported"
    assert result["intents"][0]["requires_slot_extraction"] is False
    assert result["task_plan"] == ["compliance"]


def test_primary_failure_uses_zero_shot_without_keyword_rules(monkeypatch):
    agent = object.__new__(SupervisorAgent)
    agent._intent_chain = RaisingChain()
    agent._zero_shot_classifier = FakeZeroShotClassifier({
        "intents": [{
            "intent": "asset_allocation",
            "query": "替我安排这笔钱",
            "confidence": 0.88,
            "reason": "NLI",
        }],
        "finance_related": True,
    })
    monkeypatch.setattr(supervisor_module, "INTENT_CLASSIFIER_MODE", "model")

    result = agent.plan_tasks("替我安排这笔钱")

    assert result["intent_source"] == "zero_shot"
    assert result["intents"][0]["execution_mode"] == "allocation"


def test_primary_and_nli_failure_ignore_business_keywords(monkeypatch):
    class BrokenClassifier:
        def predict(self, *_args, **_kwargs):
            raise RuntimeError("nli unavailable")

    agent = object.__new__(SupervisorAgent)
    agent._intent_chain = RaisingChain()
    agent._zero_shot_classifier = BrokenClassifier()
    monkeypatch.setattr(supervisor_module, "INTENT_CLASSIFIER_MODE", "model")

    result = agent.plan_tasks("推荐股票并配置10万元")

    assert result["intent_source"] == "safe_fallback"
    assert result["finance_related"] is False
    assert result["intents"] == [{
        "intent": "casual_chat",
        "query": "推荐股票并配置10万元",
        "confidence": 0.0,
        "reason": "意图分类服务暂不可用",
        "execution_mode": "conversation",
        "requires_slot_extraction": False,
    }]
