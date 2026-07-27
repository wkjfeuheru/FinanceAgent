import json

import pytest

from finance_agent.agents.supervisor import (
    GLMIntentClassifier,
    IntentClassificationError,
)


class FakeResponse:
    def __init__(self, content, status_code=200):
        self.status_code = status_code
        self._content = content

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")

    def json(self):
        return {"choices": [{"message": {"content": self._content}}]}


class RecordingRequester:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def __call__(self, url, **kwargs):
        self.calls.append((url, kwargs))
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


def payload(*intents, finance_related=True):
    return json.dumps({
        "intents": list(intents),
        "finance_related": finance_related,
    }, ensure_ascii=False)


def recommendation_intent(query="最近AI行业有什么值得投资的股票，为我推荐几个"):
    return {
        "intent": "stock_recommendation",
        "query": query,
        "confidence": 0.99,
        "reason": "当前轮明确要求推荐候选股票",
        "evidence": "为我推荐几个" if "为我推荐几个" in query else "推荐",
        "execution_mode": "candidate_search",
        "requires_slot_extraction": False,
    }


def make_classifier(requester, **overrides):
    options = {
        "api_key": "zhipu-test-key",
        "base_url": "https://open.bigmodel.cn/api/paas/v4/chat/completions",
        "model": "glm-4.7-flash",
        "timeout": 30,
        "max_retries": 1,
        "requester": requester,
    }
    options.update(overrides)
    return GLMIntentClassifier(**options)


def test_glm_request_uses_structured_current_turn_and_recent_summary():
    query = "最近AI行业有什么值得投资的股票，为我推荐几个"
    context = "用户上一轮询问银行股；客服给出候选。"
    requester = RecordingRequester([FakeResponse(payload(recommendation_intent()))])
    classifier = make_classifier(requester)

    result = classifier.classify(query, context, False, [])

    assert result["intents"] == [recommendation_intent()]
    url, options = requester.calls[0]
    assert url == "https://open.bigmodel.cn/api/paas/v4/chat/completions"
    assert options["timeout"] == 30
    assert options["headers"]["Authorization"] == "Bearer zhipu-test-key"
    body = options["json"]
    assert body["model"] == "glm-4.7-flash"
    assert body["temperature"] == 0
    assert body["thinking"] == {"type": "disabled"}
    assert body["response_format"] == {"type": "json_object"}
    prompt_input = json.loads(body["messages"][1]["content"])
    assert prompt_input == {
        "current_message": query,
        "recent_context_summary": context,
        "pending_allocation": False,
        "pending_fields": [],
    }


def test_profile_like_context_does_not_add_asset_allocation_intent():
    query = "最近AI行业有什么值得投资的股票，为我推荐几个"
    context = "之前用户曾说风险偏好R1、预算2万元、期限1年。"
    requester = RecordingRequester([FakeResponse(payload(recommendation_intent()))])

    result = make_classifier(requester).classify(query, context, False, [])

    assert [item["intent"] for item in result["intents"]] == ["stock_recommendation"]


def test_context_only_evidence_is_rejected():
    query = "最近AI行业有什么值得投资的股票，为我推荐几个"
    invalid_allocation = {
        "intent": "asset_allocation",
        "query": query,
        "confidence": 0.98,
        "reason": "上下文存在预算",
        "evidence": "R1、预算2万元",
        "execution_mode": "allocation",
        "requires_slot_extraction": True,
    }
    requester = RecordingRequester([
        FakeResponse(payload(recommendation_intent(), invalid_allocation)),
    ])

    result = make_classifier(requester).classify(
        query, "风险偏好R1、预算2万元", False, [],
    )

    assert [item["intent"] for item in result["intents"]] == ["stock_recommendation"]


def test_invalid_json_is_retried_once():
    requester = RecordingRequester([
        FakeResponse("not json"),
        FakeResponse(payload(recommendation_intent("推荐AI股票"))),
    ])

    result = make_classifier(requester).classify("推荐AI股票", "", False, [])

    assert result["intents"][0]["intent"] == "stock_recommendation"
    assert len(requester.calls) == 2


def test_two_invalid_responses_raise_classification_error():
    requester = RecordingRequester([FakeResponse("bad"), FakeResponse("still bad")])

    with pytest.raises(IntentClassificationError):
        make_classifier(requester).classify("推荐AI股票", "", False, [])

    assert len(requester.calls) == 2


def test_missing_api_key_fails_without_request():
    requester = RecordingRequester([])
    classifier = GLMIntentClassifier(
        api_key="", base_url="https://example.test", model="glm-4.7-flash",
        requester=requester,
    )

    with pytest.raises(IntentClassificationError, match="ZHIPU_API_KEY"):
        classifier.classify("推荐股票", "", False, [])

    assert requester.calls == []


def test_non_official_base_url_is_rejected_without_sending_api_key():
    requester = RecordingRequester([])
    classifier = GLMIntentClassifier(
        api_key="secret", base_url="https://attacker.example/chat",
        model="glm-4.7-flash", requester=requester,
    )

    with pytest.raises(IntentClassificationError, match="智谱官方"):
        classifier.classify("推荐股票", "", False, [])

    assert requester.calls == []


def test_retry_count_is_capped_at_one():
    requester = RecordingRequester([FakeResponse("bad"), FakeResponse("still bad")])
    classifier = make_classifier(requester, max_retries=99)

    with pytest.raises(IntentClassificationError):
        classifier.classify("推荐股票", "", False, [])

    assert len(requester.calls) == 2
