"""PostgreSQL 运行审计 Repository 测试。"""

from datetime import datetime, timezone
from uuid import uuid4

import pytest

from finance_agent.contracts import ExpertResult, ExpertStatus, RequestEnvelope
from finance_agent.data.postgres_repository import PostgresRuntimeRepository


class FakeCursor:
    def __init__(self, rows=None, fail_on=None):
        self.rows = list(rows or [])
        self.fail_on = fail_on
        self.statements = []
        self.closed = False

    def execute(self, statement, parameters=()):
        self.statements.append((statement, parameters))
        if self.fail_on and self.fail_on in statement:
            raise RuntimeError("sql_failed")

    def fetchone(self):
        return self.rows.pop(0) if self.rows else None

    def close(self):
        self.closed = True


class FakeConnection:
    def __init__(self, rows=None, fail_on=None):
        self.cursor_instance = FakeCursor(rows, fail_on)
        self.committed = False
        self.rolled_back = False
        self.closed = False

    def cursor(self):
        return self.cursor_instance

    def commit(self):
        self.committed = True

    def rollback(self):
        self.rolled_back = True

    def close(self):
        self.closed = True


def make_request():
    return RequestEnvelope(
        run_id=uuid4(),
        trace_id=uuid4(),
        user_id=uuid4(),
        customer_id="CUST001",
        conversation_id="conversation-1",
        message_id=uuid4(),
        message="分析 600519",
        requested_at=datetime.now(timezone.utc),
    )


def test_create_run_commits_user_message_and_running_run():
    connection = FakeConnection(rows=[("CUST001",), ("conversation-1",)])
    repository = PostgresRuntimeRepository(lambda: connection)

    result = repository.create_run(make_request())

    assert result["status"] == "running"
    assert connection.committed is True
    assert connection.rolled_back is False
    assert any("conversation_messages" in statement for statement, _ in connection.cursor_instance.statements)
    assert any("agent_runs" in statement for statement, _ in connection.cursor_instance.statements)


def test_create_run_rolls_back_when_identity_or_session_is_invalid():
    connection = FakeConnection(rows=[])
    repository = PostgresRuntimeRepository(lambda: connection)

    with pytest.raises(ValueError, match="customer_not_found"):
        repository.create_run(make_request())

    assert connection.committed is False
    assert connection.rolled_back is True
    assert connection.closed is True


def test_create_run_rolls_back_when_run_insert_fails():
    connection = FakeConnection(
        rows=[("CUST001",), ("conversation-1",)],
        fail_on="INSERT INTO finance.agent_runs",
    )
    repository = PostgresRuntimeRepository(lambda: connection)

    with pytest.raises(RuntimeError, match="sql_failed"):
        repository.create_run(make_request())

    assert connection.committed is False
    assert connection.rolled_back is True


def test_upsert_expert_result_is_idempotent_and_keeps_audit_fields():
    connection = FakeConnection()
    repository = PostgresRuntimeRepository(lambda: connection)
    run_id = str(uuid4())
    trace_id = str(uuid4())
    result = ExpertResult(
        expert_name="product_analysis",
        status=ExpertStatus.DEGRADED,
        schema_version="1.0",
        summary="产品数据暂不可用",
        result_data={"product_codes": ["110011"]},
        fact_ids=["fact-1"],
        degradation_reason="source_timeout",
    )

    first = repository.upsert_expert_result(run_id, trace_id, result)
    second = repository.upsert_expert_result(run_id, trace_id, result)
    statement, parameters = connection.cursor_instance.statements[-1]

    assert first == second
    assert first["status"] == "degraded"
    assert "ON CONFLICT (run_id, expert_name)" in statement
    assert "trace_id" in statement
    assert "source_timeout" in parameters
    assert connection.committed is True
    assert connection.rolled_back is False


def test_complete_run_commits_assistant_message_and_terminal_status():
    connection = FakeConnection()
    repository = PostgresRuntimeRepository(lambda: connection)
    result = repository.complete_run(
        str(uuid4()),
        "conversation-1",
        "已完成分析",
        message_id=str(uuid4()),
        metadata={"task_plan": ["stock_analysis"]},
    )

    assert result["status"] == "completed"
    assert connection.committed is True
    assert connection.rolled_back is False
    assert any("role, content" in statement and "assistant" in statement for statement, _ in connection.cursor_instance.statements)
    assert any("UPDATE finance.agent_runs" in statement for statement, _ in connection.cursor_instance.statements)


def test_complete_run_rolls_back_if_terminal_update_fails():
    connection = FakeConnection(fail_on="UPDATE finance.agent_runs")
    repository = PostgresRuntimeRepository(lambda: connection)

    with pytest.raises(RuntimeError, match="sql_failed"):
        repository.complete_run(
            str(uuid4()),
            "conversation-1",
            "已完成分析",
            message_id=str(uuid4()),
        )

    assert connection.committed is False
    assert connection.rolled_back is True


def test_cancel_run_marks_pending_work_without_deleting_results():
    connection = FakeConnection()
    repository = PostgresRuntimeRepository(lambda: connection)
    result = repository.cancel_run(str(uuid4()))
    statement, parameters = connection.cursor_instance.statements[-1]

    assert result["status"] == "cancelled"
    assert "UPDATE finance.agent_runs" in statement
    assert "status = 'cancelled'" in statement
    assert "agent_results" not in statement
    assert connection.committed is True


def test_cancel_run_rolls_back_when_persistence_fails():
    connection = FakeConnection(fail_on="UPDATE finance.agent_runs")
    repository = PostgresRuntimeRepository(lambda: connection)

    with pytest.raises(RuntimeError, match="sql_failed"):
        repository.cancel_run(str(uuid4()))

    assert connection.committed is False
    assert connection.rolled_back is True
