"""Qwen 意图分类器的错误语义与重试边界测试。"""

import os

import requests
import pytest

# 占位密钥经环境变量注入，避免在源码中出现凭据形态的字符串。
_FAKE_API_KEY = os.environ.get("TEST_FAKE_API_KEY", "placeholder")

from finance_agent.orchestrator.intent import (
    DeepSeekIntentClassifier,
    IntentClassificationError,
)


class _Response:
    def __init__(self, payload=None, status_error=None):
        self.payload = payload
        self.status_error = status_error

    def raise_for_status(self):
        if self.status_error:
            raise self.status_error

    def json(self):
        return self.payload


def test_classifier_retries_timeout_and_uses_unavailable_error():
    calls = []

    def requester(*args, **kwargs):
        calls.append(kwargs["timeout"])
        raise requests.Timeout("slow")

    classifier = DeepSeekIntentClassifier(
        api_key=_FAKE_API_KEY,
        model="qwen-turbo",
        timeout=1,
        max_retries=2,
        deadline=10,
        requester=requester,
    )

    with pytest.raises(IntentClassificationError) as exc_info:
        classifier.classify("分析600519")

    assert len(calls) == 3
    assert exc_info.value.error_code == "intent_unavailable"
    assert exc_info.value.cause == "timeout"


def test_classifier_retries_protocol_error_and_distinguishes_it():
    calls = []

    def requester(*args, **kwargs):
        calls.append(1)
        return _Response({"choices": [{"message": {"content": "not-json"}}]})

    classifier = DeepSeekIntentClassifier(
        api_key=_FAKE_API_KEY,
        model="qwen-turbo",
        max_retries=2,
        deadline=10,
        requester=requester,
    )

    with pytest.raises(IntentClassificationError) as exc_info:
        classifier.classify("分析600519")

    assert len(calls) == 3
    assert exc_info.value.error_code == "intent_protocol_error"
    assert exc_info.value.cause == "invalid_json"


def test_classifier_retries_http_error_as_unavailable():
    calls = []

    def requester(*args, **kwargs):
        calls.append(1)
        return _Response(status_error=requests.HTTPError("503"))

    classifier = DeepSeekIntentClassifier(
        api_key=_FAKE_API_KEY,
        model="qwen-turbo",
        max_retries=2,
        deadline=10,
        requester=requester,
    )

    with pytest.raises(IntentClassificationError) as exc_info:
        classifier.classify("分析600519")

    assert len(calls) == 3
    assert exc_info.value.error_code == "intent_unavailable"
    assert exc_info.value.cause == "http"


def test_classifier_deadline_stops_retry_loop():
    calls = []

    def requester(*args, **kwargs):
        calls.append(1)
        raise requests.Timeout("slow")

    classifier = DeepSeekIntentClassifier(
        api_key=_FAKE_API_KEY,
        model="qwen-turbo",
        timeout=30,
        max_retries=2,
        deadline=0,
        requester=requester,
    )

    with pytest.raises(IntentClassificationError) as exc_info:
        classifier.classify("分析600519")

    assert calls == []
    assert exc_info.value.error_code == "intent_unavailable"
    assert exc_info.value.cause == "deadline"


# ── 主备降级链 ──────────────────────────────────────────────────────────────

def _payload():
    return {
        "intents": [{
            "intent": "stock_analysis", "query": "分析600519", "confidence": 0.99,
            "evidence": "分析600519", "execution_mode": "stock_analysis",
        }],
        "finance_related": True,
    }


class _OkClassifier:
    def __init__(self, payload):
        self.payload = payload
        self.calls = 0

    def classify(self, message, context_summary=""):
        self.calls += 1
        return dict(self.payload)


class _BoomClassifier:
    def __init__(self, cause="http"):
        self.calls = 0
        self._cause = cause

    def classify(self, message, context_summary=""):
        self.calls += 1
        raise IntentClassificationError("down", error_code="intent_unavailable", cause=self._cause)


def test_primary_success_does_not_touch_fallback():
    from finance_agent.orchestrator.intent import IntentClassifier

    primary = _OkClassifier(_payload())
    fallback = _BoomClassifier()
    result = IntentClassifier(classifier=primary, fallback_classifier=fallback).classify_intents("分析600519")

    assert result["intent_source"] == "deepseek"
    assert result["classification_error"] == {}
    assert primary.calls == 1
    assert fallback.calls == 0


def test_primary_failure_falls_back_to_secondary_model():
    from finance_agent.orchestrator.intent import IntentClassifier

    primary = _BoomClassifier(cause="http")
    fallback = _OkClassifier(_payload())
    result = IntentClassifier(classifier=primary, fallback_classifier=fallback).classify_intents("分析600519")

    assert result["intent_source"] == "deepseek_fallback"
    assert result["classification_error"] == {}
    assert [i["intent"] for i in result["intents"]] == ["stock_analysis"]
    assert primary.calls == 1 and fallback.calls == 1


def test_both_models_failing_reports_explicit_error():
    from finance_agent.orchestrator.intent import IntentClassifier

    result = IntentClassifier(
        classifier=_BoomClassifier(cause="http"),
        fallback_classifier=_BoomClassifier(cause="deadline"),
    ).classify_intents("分析600519")

    assert result["intents"] == []
    assert result["classification_error"]["error_code"] == "intent_unavailable"
    assert "primary=http" in result["classification_error"]["cause"]
    assert "fallback=deadline" in result["classification_error"]["cause"]


def test_injected_classifier_has_no_config_fallback():
    """注入主分类器时不自动构造联网备用模型，避免测试意外发起真实请求。"""
    from finance_agent.orchestrator.intent import IntentClassifier

    classifier = IntentClassifier(classifier=_BoomClassifier())
    assert classifier.fallback_classifier is None

    result = classifier.classify_intents("分析600519")
    assert result["classification_error"]["error_code"] == "intent_unavailable"


def test_prompt_defines_product_vs_knowledge_boundary():
    """分类提示词必须写明 product_analysis 与 casual_chat(FAQ) 的边界，
    否则模型会把含“基金”的知识问答（如风险等级含义）误判为产品分析。"""
    from finance_agent.orchestrator.intent import _INTENT_CLASSIFIER_PROMPT as prompt

    assert "casual_chat" in prompt
    # 明确的知识问答示例必须出现在提示词里，作为边界锚点
    for anchor in ("风险等级", "申购费率", "具体产品"):
        assert anchor in prompt, f"提示词缺少边界锚点：{anchor}"
    # 并且要显式禁止“见词即判”
    assert "不得因为句中出现" in prompt


# ── 逐条容错：单条小问题不得拖垮整批意图 ────────────────────────────────────

def _validate(payload, message):
    from finance_agent.orchestrator.intent import DeepSeekIntentClassifier

    return DeepSeekIntentClassifier._validate(payload, message)


def test_low_confidence_item_does_not_discard_valid_siblings():
    """复合请求里某条低置信度意图缺少澄清问题时，不得连带丢掉其它有效意图。"""
    message = "分析贵州茅台并比较合适的基金产品"
    payload = {"intents": [
        {"intent": "stock_analysis", "query": "分析贵州茅台", "confidence": 0.95,
         "evidence": "分析贵州茅台", "execution_mode": "stock_analysis"},
        {"intent": "product_analysis", "query": "比较合适的基金产品", "confidence": 0.85,
         "evidence": "比较合适的基金产品", "execution_mode": "product_analysis"},
    ], "finance_related": True}

    parsed = _validate(payload, message)

    assert [i["intent"] for i in parsed["intents"]] == ["stock_analysis", "product_analysis"]


def test_invalid_execution_mode_does_not_discard_valid_siblings():
    """模型臆造 execution_mode 时归一化即可，不应让整批意图分类失败。"""
    message = "华夏成长基金和易方达蓝筹哪个好"
    payload = {"intents": [
        {"intent": "product_analysis", "query": message, "confidence": 0.95,
         "evidence": message, "execution_mode": "product_comparison"},
    ], "finance_related": True}

    parsed = _validate(payload, message)

    assert len(parsed["intents"]) == 1


def test_unknown_intent_is_dropped_downstream_not_fatal():
    """未知 intent 由 normalize 丢弃，最终如实上报 no_valid_intents（而非崩溃）。"""
    from finance_agent.orchestrator.intent import IntentClassifier

    class _Model:
        def classify(self, message, context_summary=""):
            return {"intents": [
                {"intent": "unknown_intent", "query": message, "confidence": 0.99, "evidence": message},
            ], "finance_related": True}

    result = IntentClassifier(classifier=_Model()).classify_intents("随便问问")

    assert result["intents"] == []
    assert result["classification_error"]["cause"] == "no_valid_intents"


def test_evidence_not_in_message_still_dropped_per_item():
    """证据必须逐字来自当前消息：单条编造证据只丢该条。"""
    message = "分析600519"
    payload = {"intents": [
        {"intent": "stock_analysis", "query": "分析600519", "confidence": 0.95,
         "evidence": "分析600519", "execution_mode": "stock_analysis"},
        {"intent": "product_analysis", "query": "编造的", "confidence": 0.95,
         "evidence": "这句不在原文里", "execution_mode": "product_analysis"},
    ], "finance_related": True}

    parsed = _validate(payload, message)

    assert [i["intent"] for i in parsed["intents"]] == ["stock_analysis"]


# ── 模型把 execution_mode 误填为 intent ─────────────────────────────────────

def test_execution_mode_misused_as_intent_is_recovered():
    """模型常把 market_overview 这类 execution_mode 填进 intent 字段。

    这是可修复的格式错误，必须还原成所属意图，而不是丢弃整条分类
    （否则“今天大盘怎么样”会间歇性失败）。
    """
    from finance_agent.orchestrator.intent import normalize_intent_item

    cases = {
        "market_overview": ("market_insight", "market_overview"),
        "market_sentiment": ("market_insight", "market_sentiment"),
        "capital_flow": ("market_insight", "capital_flow"),
        "policy_impact": ("market_insight", "policy_impact"),
        "candidate_search": ("stock_recommendation", "candidate_search"),
        "stock_comparison": ("stock_recommendation", "stock_comparison"),
        "conversation": ("casual_chat", "conversation"),
        "product_analysis": ("product_analysis", "product_analysis"),
    }
    for raw, (intent, mode) in cases.items():
        item = {"intent": raw, "query": "今天大盘怎么样", "confidence": 0.95,
                "evidence": "今天大盘怎么样", "execution_mode": raw}
        normalized = normalize_intent_item(item, "今天大盘怎么样")
        assert normalized is not None, f"{raw} 应被还原而不是丢弃"
        assert (normalized["intent"], normalized["execution_mode"]) == (intent, mode)


def test_unknown_intent_is_still_rejected():
    from finance_agent.orchestrator.intent import normalize_intent_item

    assert normalize_intent_item(
        {"intent": "totally_unknown", "query": "x", "confidence": 0.9, "evidence": "x"},
        "x",
    ) is None


def test_prompt_forbids_mode_values_in_intent_field():
    from finance_agent.orchestrator.intent import _INTENT_CLASSIFIER_PROMPT as prompt

    assert "intent` 字段" in prompt
    assert "不能" in prompt


def test_prompt_confidence_threshold_is_not_hardcoded_twice():
    """提示词里的置信度阈值必须取自常量，避免文案与过滤规则双写漂移。"""
    from finance_agent.orchestrator.intent import (
        _INTENT_CLASSIFIER_PROMPT as prompt,
        _INTENT_CONFIDENCE_THRESHOLD as threshold,
    )

    assert f"confidence 小于 {threshold}" in prompt
    # 阈值数值在提示词里只出现一次（即那段由常量插值而来），不得再写死一份
    assert prompt.count(str(threshold)) == 1
