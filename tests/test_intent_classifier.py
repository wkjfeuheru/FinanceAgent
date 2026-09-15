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
