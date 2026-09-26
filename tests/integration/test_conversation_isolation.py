"""会话隔离：跨用户读写一律 404，删除只清本人数据。"""

from __future__ import annotations

import asyncio
import threading

import pytest
from fastapi import HTTPException

from finance_agent.api import dependencies as deps
from finance_agent.api.routers import chat as r
from finance_agent.api.routers import conversations


class _FakeRequest:
    def __init__(self, headers=None):
        self.headers = headers or {"Authorization": "Bearer good-token"}


class _ChatRequest:
    def __init__(self, message="你好", conversation_id=""):
        self.message = message
        self.conversation_id = conversation_id
        self.chat_history = []
        self.customer_id = ""
        self.resume = False
        self.answers = {}


@pytest.fixture()
def auth_store(monkeypatch):
    class _Store:
        def verify_token(self, token):
            return "CUST1" if token == "good-token" else None

    monkeypatch.setattr(deps, "get_user_store", lambda: _Store())


def _patch_db(monkeypatch, *, owned: bool):
    class _DB:
        def get_conversation(self, conversation_id, customer_id):
            if not owned:
                return None
            return {"conversation_id": conversation_id, "customer_id": customer_id}

    monkeypatch.setattr("finance_agent.orchestration.persistence_database.get_database", lambda: _DB())


# ── DELETE 路由 ──────────────────────────────────────────────────────────────

def test_delete_rejects_conversation_not_owned(auth_store, monkeypatch):
    """非本人会话：404，且绝不调用删除（不得清除他人 checkpoint/记忆）。"""
    _patch_db(monkeypatch, owned=False)
    called = {"deleted": False}

    class _System:
        def delete_checkpoint_conversation(self, conversation_id, customer_id):
            called["deleted"] = True
            return True

    monkeypatch.setattr(conversations, "get_system", lambda: _System())

    with pytest.raises(HTTPException) as exc:
        asyncio.run(conversations.delete_conversation(_FakeRequest(), "CUST1", "someone-else"))

    assert exc.value.status_code == 404
    assert called["deleted"] is False


def test_delete_allows_owned_conversation(auth_store, monkeypatch):
    _patch_db(monkeypatch, owned=True)

    class _System:
        def delete_checkpoint_conversation(self, conversation_id, customer_id):
            return True

    monkeypatch.setattr(conversations, "get_system", lambda: _System())

    result = asyncio.run(conversations.delete_conversation(_FakeRequest(), "CUST1", "my-conv"))

    assert result == {"status": "ok", "conversation_id": "my-conv"}


def test_delete_cannot_touch_another_customers_path(auth_store, monkeypatch):
    """路径 customer_id 必须等于登录用户，否则 403（越权入口）。"""
    _patch_db(monkeypatch, owned=True)
    with pytest.raises(HTTPException) as exc:
        asyncio.run(conversations.delete_conversation(_FakeRequest(), "CUST-OTHER", "conv"))
    assert exc.value.status_code == 403


# ── /api/chat 归属校验 ───────────────────────────────────────────────────────

def test_chat_rejects_writing_into_another_users_conversation(auth_store, monkeypatch):
    """带上他人 conversation_id 时 404，避免把消息写进别人的会话。"""
    _patch_db(monkeypatch, owned=False)
    called = {"handled": False}

    class _System:
        def handle_message(self, **kwargs):
            called["handled"] = True
            return {}

    monkeypatch.setattr(r, "get_system", lambda: _System())

    with pytest.raises(HTTPException) as exc:
        asyncio.run(r.chat(_ChatRequest(conversation_id="victim-conv"), _FakeRequest()))

    assert exc.value.status_code == 404
    assert called["handled"] is False


def test_chat_allows_owned_conversation(auth_store, monkeypatch):
    _patch_db(monkeypatch, owned=True)

    class _System:
        def handle_message(self, **kwargs):
            return {"response": "ok", "conversation_id": "my-conv"}

    monkeypatch.setattr(r, "get_system", lambda: _System())

    result = asyncio.run(r.chat(_ChatRequest(conversation_id="my-conv"), _FakeRequest()))

    assert result.response == "ok"


def test_chat_with_empty_conversation_id_skips_ownership_check(auth_store, monkeypatch):
    """空 id 表示新建会话，不应触发归属查询（否则首次对话无法开始）。"""
    checked = {"n": 0}

    class _DB:
        def get_conversation(self, conversation_id, customer_id):
            checked["n"] += 1
            return None

    monkeypatch.setattr("finance_agent.orchestration.persistence_database.get_database", lambda: _DB())

    class _System:
        def handle_message(self, **kwargs):
            return {"response": "ok", "conversation_id": "new-conv"}

    monkeypatch.setattr(r, "get_system", lambda: _System())

    asyncio.run(r.chat(_ChatRequest(conversation_id=""), _FakeRequest()))

    assert checked["n"] == 0


# ── delete_checkpoint_conversation 只在确实删除本人行时才清理 ─────────────────

def test_delete_checkpoint_conversation_returns_false_for_unowned(monkeypatch):
    from finance_agent.application.advisor import AdvisorSystem

    system = object.__new__(AdvisorSystem)
    cleared = {"memory": False, "checkpoint": False}

    class _DB:
        def delete_conversation(self, conversation_id, customer_id):
            return False  # 非本人：0 行受影响

    system.run_state = type("RS", (), {"delete": lambda *a, **k: cleared.__setitem__("checkpoint", True)})()
    system.memory = type("M", (), {
        "store": type("S", (), {
            "clear_conversation": lambda *a, **k: cleared.__setitem__("memory", True),
        })(),
    })()

    monkeypatch.setattr(
        "finance_agent.application.advisor.get_database", lambda: _DB(),
    )

    assert system.delete_checkpoint_conversation("victim-conv", "CUST1") is False
    assert cleared["memory"] is False
    assert cleared["checkpoint"] is False
