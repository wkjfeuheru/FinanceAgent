"""管理员标志下发：login 与 /api/me 必须准确暴露 is_admin。"""

from __future__ import annotations

import asyncio

import pytest

from finance_agent.api import routes as r


class _FakeRequest:
    def __init__(self, headers=None):
        self.headers = headers or {"Authorization": "Bearer good-token"}


class _Store:
    def verify_token(self, token):
        return "ADMIN1" if token == "admin-token" else ("USER1" if token == "user-token" else None)

    def get_user_by_customer_id(self, customer_id):
        return {"customer_id": customer_id, "username": customer_id.lower(), "display_name": customer_id}

    def login(self, username, password):
        return {
            "customer_id": "ADMIN1",
            "username": username,
            "display_name": "管理员",
            "token": "admin-token",
        }


@pytest.fixture()
def store(monkeypatch):
    monkeypatch.setattr(r, "get_user_store", lambda: _Store())
    monkeypatch.setattr(r, "ADMIN_CUSTOMER_IDS", {"ADMIN1"})


def test_login_marks_admin(store):
    response = asyncio.run(r.login(r.LoginRequest(username="admin", password="secret")))

    assert response.is_admin is True
    assert response.customer_id == "ADMIN1"


def test_me_exposes_is_admin_for_admin(store):
    payload = asyncio.run(r.get_current_user(_FakeRequest({"Authorization": "Bearer admin-token"})))

    assert payload["is_admin"] is True


def test_me_exposes_is_admin_false_for_regular_user(store):
    payload = asyncio.run(r.get_current_user(_FakeRequest({"Authorization": "Bearer user-token"})))

    assert payload["is_admin"] is False


def test_is_admin_is_whitelist_only_and_case_insensitive(monkeypatch):
    monkeypatch.setattr(r, "ADMIN_CUSTOMER_IDS", {"ADMIN1"})

    assert r._is_admin("admin1") is True
    assert r._is_admin("ADMIN1") is True
    assert r._is_admin("USER1") is False


def test_no_admin_configured_means_nobody_is_admin(monkeypatch):
    monkeypatch.setattr(r, "ADMIN_CUSTOMER_IDS", set())

    assert r._is_admin("ADMIN1") is False
