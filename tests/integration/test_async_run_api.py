"""异步运行状态端点：鉴权、归属校验与安全状态投影。"""

from __future__ import annotations

import asyncio

import pytest
from fastapi import HTTPException

from finance_agent.api import dependencies as deps
from finance_agent.api.routers import chat as r

chat_routes = r


class _FakeStore:
    def verify_token(self, token):
        return "CUST1" if token == "good-token" else None


class _FakeRequest:
    def __init__(self, headers=None):
        self.headers = headers or {}


def auth() -> _FakeRequest:
    return _FakeRequest({"Authorization": "Bearer good-token"})


@pytest.fixture()
def auth_store(monkeypatch):
    monkeypatch.setattr(deps, "get_user_store", lambda: _FakeStore())


class _FakeSystem:
    def __init__(self, payload):
        self._payload = payload
        self.calls: list[tuple[str, str]] = []

    def resolve_run_status(self, task_id, customer_id):
        self.calls.append((task_id, customer_id))
        return self._payload


def test_processing_response_keeps_legacy_fields(monkeypatch, auth_store):
    system = _FakeSystem(
        {
            "run_status": "processing",
            "task_id": "job-1",
            "response": "",
            "conversation_id": "",
            "warnings": [],
        }
    )
    monkeypatch.setattr(chat_routes, "get_system", lambda: system)

    payload = asyncio.run(r.get_run_status(auth(), "job-1"))

    assert payload["run_status"] == "processing"
    assert "response" in payload
    assert system.calls == [("job-1", "CUST1")]


def test_run_status_requires_authentication(monkeypatch, auth_store):
    monkeypatch.setattr(chat_routes, "get_system", lambda: _FakeSystem({}))

    with pytest.raises(HTTPException) as exc:
        asyncio.run(r.get_run_status(_FakeRequest(), "job-1"))

    assert exc.value.status_code == 401


def test_unknown_run_returns_not_found(monkeypatch, auth_store):
    system = _FakeSystem({"run_status": "not_found", "task_id": "job-x", "response": ""})
    monkeypatch.setattr(chat_routes, "get_system", lambda: system)

    payload = asyncio.run(r.get_run_status(auth(), "job-x"))

    assert payload["run_status"] == "not_found"


def test_missing_resolver_is_404(monkeypatch, auth_store):
    monkeypatch.setattr(chat_routes, "get_system", lambda: object())

    with pytest.raises(HTTPException) as exc:
        asyncio.run(r.get_run_status(auth(), "job-1"))

    assert exc.value.status_code == 404
