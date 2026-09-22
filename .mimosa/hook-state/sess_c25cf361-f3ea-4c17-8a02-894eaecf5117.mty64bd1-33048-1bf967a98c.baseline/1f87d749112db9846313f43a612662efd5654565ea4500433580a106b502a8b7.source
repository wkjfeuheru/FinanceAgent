"""运行时控制回归测试：停止生成、澄清流程、admin 清全库门控。"""

import asyncio

import pytest
from fastapi import HTTPException

from finance_agent.agents.supervisor import ManagerAgent


class _FakeClassifier:
    def __init__(self, payload):
        self.payload = payload

    def classify(self, *args, **kwargs):
        return self.payload


def test_request_stop_and_is_stopped():
    from finance_agent.orchestrator.orchestrator import AdvisorSystem

    system = object.__new__(AdvisorSystem)
    system._stop_requests = {}
    system._active_runs = {}
    system._stop_lock = __import__("threading").Lock()

    system._active_runs["run-1"] = "conv-1"
    assert system.request_stop(run_id="run-1") is True
    assert system._is_stopped("conv-1") is True
    assert system._is_stopped("conv-2") is False
    assert system.request_stop(conversation_id="conv-2") is True
    assert system._is_stopped("conv-2") is True
    assert system.request_stop() is False  # 无标识不记录


def test_clarification_writes_uncertain_intents():
    manager = ManagerAgent()
    manager._intent_classifier = _FakeClassifier({
        "intents": [{
            "intent": "stock_recommendation",
            "query": "那只股票",
            "confidence": 0.5,
            "reason": "低置信度",
            "evidence": "那只股票",
            "execution_mode": "candidate_search",
            "clarification_question": "您想分析具体哪只股票？",
        }],
        "finance_related": True,
    })
    state = {"user_message": "帮我看看那只股票"}
    dispatch = manager.dispatch_tasks(state)

    assert dispatch == []
    assert len(state["uncertain_intents"]) == 1
    assert state["uncertain_intents"][0]["clarification_question"] == "您想分析具体哪只股票？"


def test_clear_records_admin_gate(monkeypatch):
    from finance_agent.api import routes as r

    monkeypatch.setattr(r, "ADMIN_CUSTOMER_IDS", set())

    class _FakeRequest:
        headers = {"Authorization": "Bearer good-token"}

    class _FakeStore:
        def verify_token(self, token):
            return "CUST000001"

    monkeypatch.setattr(r, "get_user_store", lambda: _FakeStore())

    with pytest.raises(HTTPException) as exc:
        asyncio.run(r.clear_records(_FakeRequest(), customer_id=None, keep_users=True))
    assert exc.value.status_code == 403
