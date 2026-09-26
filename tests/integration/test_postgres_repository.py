"""PostgreSQL 运行审计 Repository 测试。"""

import json
from datetime import datetime, timezone
from uuid import uuid4

import pytest

from finance_agent.shared.contracts import ExpertResult, ExpertStatus, RequestEnvelope
from finance_agent.infrastructure.persistence.postgres.runtime_repository import PostgresRuntimeRepository
from finance_agent.infrastructure.persistence.postgres.research_repository import ResearchRunRepository
from finance_agent.domains.research.contracts import Action, AnalysisKind, AnalysisRequest, AnalysisResult


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

    def fetchall(self):
        return list(self.rows)

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


def test_research_run_repository_persists_replayable_result_and_snapshot_manifest():
    """防止研究审计丢失规则版本、画像状态、快照和事实引用。"""
    connection = FakeConnection()
    repository = ResearchRunRepository(lambda: connection)
    result = AnalysisResult(
        request=AnalysisRequest(
            kind=AnalysisKind.SINGLE_STOCK,
            stock_codes=["600519"],
            profile_complete=True,
        ),
        action=Action.WATCH,
        data_quality="complete",
        rule_version="research_rules/v1",
        scores={"fundamental": 80.0, "total": 82.5},
        evidence_ids=["fact-600519"],
        personalization_status="personalized",
    )

    research_run_id = repository.save(
        result,
        snapshot_manifest=[{"fact_id": "fact-600519", "as_of": "2026-09-11"}],
        run_id=str(uuid4()),
        customer_id="CUST001",
        conversation_id="conversation-1",
    )

    run_statement, run_parameters = connection.cursor_instance.statements[0]
    result_statement, result_parameters = next(
        item for item in connection.cursor_instance.statements
        if "INSERT INTO finance.research_results" in item[0]
    )
    assert research_run_id
    assert "finance.research_runs" in run_statement
    assert '"profile_complete": true' in run_parameters[4]
    assert '"fact_id": "fact-600519"' in run_parameters[5]
    assert run_parameters[6] == "research_rules/v1"
    assert "finance.research_results" in result_statement
    assert result_parameters[2] == "600519"
    assert result_parameters[3] == "关注"
    assert connection.committed is True


def test_research_run_repository_persists_multiple_independent_results():
    connection = FakeConnection()
    repository = ResearchRunRepository(lambda: connection)
    request = AnalysisRequest(
        kind=AnalysisKind.COMPARISON, stock_codes=["600519", "600036"], profile_complete=False,
    )
    results = [
        AnalysisResult(
            request=request.model_copy(update={"stock_codes": ["600519"]}),
            action=Action.WATCH, data_quality="complete", rule_version="research_rules/v1",
            scores={"total": 88}, evidence_ids=["fact-1"],
        ),
        AnalysisResult(
            request=request.model_copy(update={"stock_codes": ["600036"]}),
            action=Action.WAIT, data_quality="warning", rule_version="research_rules/v1",
            scores={"total": 62}, evidence_ids=["fact-2"],
        ),
    ]

    run_id = repository.save_many(
        request=request,
        results=results,
        snapshot_manifest=[{"fact_id": "fact-1"}, {"fact_id": "fact-2"}],
        run_id=str(uuid4()), customer_id="CUST001", conversation_id="conversation-1",
        status="partial_success",
    )

    assert run_id
    run_statement, run_parameters = connection.cursor_instance.statements[0]
    result_statements = [item for item in connection.cursor_instance.statements if "INSERT INTO finance.research_results" in item[0]]
    assert '"active_members"' not in run_parameters[5]
    assert len(result_statements) == 2
    assert result_statements[0][1][2] == "600519"
    assert result_statements[1][1][2] == "600036"


def test_research_run_repository_uses_stable_id_and_upsert_for_same_agent_run():
    connection = FakeConnection()
    repository = ResearchRunRepository(lambda: connection)
    agent_run_id = str(uuid4())
    result = AnalysisResult(
        request=AnalysisRequest(kind=AnalysisKind.SINGLE_STOCK, stock_codes=["600519"]),
        action=Action.WATCH, data_quality="complete", rule_version="research_rules/v1",
    )

    first = repository.save(result, snapshot_manifest=[], run_id=agent_run_id,
                            customer_id="CUST001", conversation_id="conversation-1")
    second = repository.save(result, snapshot_manifest=[], run_id=agent_run_id,
                             customer_id="CUST001", conversation_id="conversation-1")
    run_statement = connection.cursor_instance.statements[-3][0]

    assert first == second
    assert "ON CONFLICT (research_run_id)" in run_statement
    assert "DELETE FROM finance.research_results" in connection.cursor_instance.statements[-2][0]


def test_research_run_repository_rolls_back_when_one_result_insert_fails():
    connection = FakeConnection(fail_on="INSERT INTO finance.research_results")
    repository = ResearchRunRepository(lambda: connection)
    result = AnalysisResult(
        request=AnalysisRequest(kind=AnalysisKind.SINGLE_STOCK, stock_codes=["600519"]),
        action=Action.WATCH, data_quality="complete", rule_version="research_rules/v1",
    )

    with pytest.raises(RuntimeError, match="sql_failed"):
        repository.save_many(
            request=result.request, results=[result], snapshot_manifest=[],
            run_id=str(uuid4()), customer_id="CUST001", conversation_id="conversation-1",
        )
    assert connection.committed is False
    assert connection.rolled_back is True


def test_research_run_repository_loads_record_for_replay():
    """审计重放需要按运行 ID 读回请求、快照清单与标的结论。"""
    manifest = [{"fact_id": "stock_snapshot:600519:abc", "payload": {"inputs": {"quote": {}}}}]
    connection = FakeConnection(rows=[
        ("run-uuid", None, "CUST001", "conversation-1",
         '{"kind": "single_stock", "stock_codes": ["600519"], "profile_complete": true}',
         json.dumps({"snapshots": manifest}),
         "research_rules/v1", "completed"),
        ("600519", "关注", '{"total": 82.0}', '["stock_snapshot:600519:abc"]', ""),
    ])
    repository = ResearchRunRepository(lambda: connection)

    record = repository.load("run-uuid")

    assert record is not None
    assert record["request_data"]["stock_codes"] == ["600519"]
    assert record["snapshot_manifest"]["snapshots"] == manifest
    assert record["rule_version"] == "research_rules/v1"
    assert record["results"][0]["stock_code"] == "600519"
    assert record["results"][0]["scores"] == {"total": 82.0}
    assert connection.closed is True


def test_research_run_repository_load_returns_none_when_missing():
    repository = ResearchRunRepository(lambda: FakeConnection(rows=[]))

    assert repository.load("missing-run") is None
    assert repository.load("") is None
