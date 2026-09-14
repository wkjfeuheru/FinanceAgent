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
