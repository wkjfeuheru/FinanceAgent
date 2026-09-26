"""鉴权与 IDOR 回归测试。"""

import pytest
from fastapi import HTTPException

from finance_agent.api import dependencies as r
from finance_agent.api.routers import chat as chat_routes


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
    from finance_agent.api import dependencies as deps

    monkeypatch.setattr(r, "get_user_store", lambda: _FakeStore())
    monkeypatch.setattr(deps, "get_user_store", lambda: _FakeStore())


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


def test_chat_stop_rejects_conversation_not_owned_by_caller(auth_store, monkeypatch):
    """stop 必须校验会话归属，避免任意登录用户停掉他人运行。"""
    import asyncio
    from types import SimpleNamespace

    class _DB:
        def get_conversation(self, conversation_id, customer_id):
            return None  # 该会话不属于当前用户

    monkeypatch.setattr(
        "finance_agent.orchestration.persistence_database.get_database", lambda: _DB(),
    )

    with pytest.raises(HTTPException) as exc:
        asyncio.run(chat_routes.chat_stop(
            _FakeRequest({"Authorization": "Bearer good-token"}),
            conversation_id="someone-elses-conv",
            run_id="",
        ))
    assert exc.value.status_code == 404


def test_chat_stop_allows_owned_conversation(auth_store, monkeypatch):
    import asyncio

    stopped: dict[str, str] = {}

    class _DB:
        def get_conversation(self, conversation_id, customer_id):
            return {"conversation_id": conversation_id, "customer_id": customer_id}

    class _System:
        def request_stop(self, conversation_id="", run_id=""):
            stopped["conversation_id"] = conversation_id
            return True

    monkeypatch.setattr(
        "finance_agent.orchestration.persistence_database.get_database", lambda: _DB(),
    )
    monkeypatch.setattr(chat_routes, "get_system", lambda: _System())

    result = asyncio.run(chat_routes.chat_stop(
        _FakeRequest({"Authorization": "Bearer good-token"}),
        conversation_id="my-conv",
        run_id="",
    ))
    assert result["stopped"] is True
    assert stopped["conversation_id"] == "my-conv"


def test_delete_user_clears_research_rows_before_user():
    """注销账号必须先清理 research_results/research_runs，否则外键会让注销 500。"""
    from finance_agent.infrastructure.persistence.postgres.auth_store import PostgresAuthStore

    executed: list[str] = []

    class _Cursor:
        rowcount = 1

        def execute(self, statement, params=()):
            executed.append(statement)

        def close(self):
            pass

    class _Conn:
        def cursor(self):
            return _Cursor()

        def commit(self):
            pass

        def rollback(self):
            pass

        def close(self):
            pass

    store = PostgresAuthStore(lambda: _Conn())
    store._schema_ready = True
    store.delete_user("CUST1")

    joined = "\n".join(executed)
    assert "finance.research_results" in joined
    assert "finance.research_runs" in joined
    # 顺序：先结果、再运行、最后用户
    assert joined.index("finance.research_results") < joined.index("finance.research_runs") < joined.index("finance.users")


def test_chat_stop_rejects_run_id_not_owned_by_caller(auth_store, monkeypatch):
    """仅凭 run_id 停止时也必须校验归属，不能停掉他人正在跑的会话。"""
    import asyncio

    class _System:
        def lookup_active_run(self, run_id):
            return ("someone-elses-conv", "CUST000002")

        def request_stop(self, conversation_id="", run_id=""):
            raise AssertionError("不得对他人运行调用 request_stop")

    monkeypatch.setattr(chat_routes, "get_system", lambda: _System())

    with pytest.raises(HTTPException) as exc:
        asyncio.run(chat_routes.chat_stop(
            _FakeRequest({"Authorization": "Bearer good-token"}),
            conversation_id="",
            run_id="run-other",
        ))
    assert exc.value.status_code == 404


def test_chat_stop_allows_owned_run_id(auth_store, monkeypatch):
    import asyncio

    stopped: dict[str, str] = {}

    class _DB:
        def get_conversation(self, conversation_id, customer_id):
            return {"conversation_id": conversation_id, "customer_id": customer_id}

    class _System:
        def lookup_active_run(self, run_id):
            return ("my-conv", "CUST000001")

        def request_stop(self, conversation_id="", run_id=""):
            stopped["conversation_id"] = conversation_id
            stopped["run_id"] = run_id
            return True

    monkeypatch.setattr(
        "finance_agent.orchestration.persistence_database.get_database", lambda: _DB(),
    )
    monkeypatch.setattr(chat_routes, "get_system", lambda: _System())

    result = asyncio.run(chat_routes.chat_stop(
        _FakeRequest({"Authorization": "Bearer good-token"}),
        conversation_id="",
        run_id="run-mine",
    ))
    assert result["stopped"] is True
    assert stopped["conversation_id"] == "my-conv"
    assert stopped["run_id"] == "run-mine"
