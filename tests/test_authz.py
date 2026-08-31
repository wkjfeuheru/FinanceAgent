"""鉴权与 IDOR 回归测试。"""

import pytest
from fastapi import HTTPException

from finance_agent.api import routes as r


class _FakeStore:
    def verify_token(self, token):
        return "CUST000001" if token == "good-token" else None


class _FakeRequest:
    def __init__(self, headers=None):
        self.headers = headers or {}


class _FakeChatRequest:
    customer_id = "CUST999999"


@pytest.fixture()
def auth_store(monkeypatch):
    monkeypatch.setattr(r, "get_user_store", lambda: _FakeStore())


def test_require_customer_id_missing_token(auth_store):
    with pytest.raises(HTTPException) as exc:
        r._require_customer_id(_FakeRequest())
    assert exc.value.status_code == 401


def test_require_customer_id_valid_token(auth_store):
    assert (
        r._require_customer_id(_FakeRequest({"Authorization": "Bearer good-token"}))
        == "CUST000001"
    )


def test_authorize_customer_blocks_idor(auth_store):
    with pytest.raises(HTTPException) as exc:
        r._authorize_customer(
            _FakeRequest({"Authorization": "Bearer good-token"}), "CUST000002",
        )
    assert exc.value.status_code == 403


def test_authorize_customer_allows_self_case_insensitive(auth_store):
    assert (
        r._authorize_customer(
            _FakeRequest({"Authorization": "Bearer good-token"}), "cust000001",
        )
        == "CUST000001"
    )


def test_resolve_customer_id_always_requires_auth(auth_store):
    with pytest.raises(HTTPException) as exc:
        r._resolve_customer_id(_FakeRequest(), _FakeChatRequest(), "HEADER")
    assert exc.value.status_code == 401
