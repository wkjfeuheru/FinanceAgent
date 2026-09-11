"""PostgreSQL 审计层接入测试。"""

import uuid

from finance_agent.contracts import ExpertResult, ExpertStatus, IntentKind, RequestEnvelope, Task, generate_identifiers
from finance_agent.data.postgres_repository import PostgresAuditStore


class _RecordingCursor:
    def __init__(self, rows=None):
        self.rows = list(rows or [])
        self.statements = []

    def execute(self, statement, parameters=()):
        self.statements.append(statement)

    def fetchone(self):
        return self.rows.pop(0) if self.rows else None

    def close(self):
        pass


class _RecordingConnection:
    def __init__(self, rows=None):
        self.cursor_instance = _RecordingCursor(rows)

    def cursor(self):
        return self.cursor_instance

    def commit(self):
        pass

    def rollback(self):
        pass

    def close(self):
        pass


class _RecordingFactory:
    def __init__(self, rows_per_connection=None):
        self.rows_per_connection = list(rows_per_connection or [])
        self.connections = []

    def __call__(self):
        rows = self.rows_per_connection.pop(0) if self.rows_per_connection else None
        conn = _RecordingConnection(rows)
        self.connections.append(conn)
        return conn


def test_audit_store_noop_when_unavailable():
    store = PostgresAuditStore(None)
    assert store.is_available() is False
    assert store.create_run(object()) is None
    assert store.upsert_expert_result("r", "t", object()) is None
    assert store.complete_run("r", "c", "resp", message_id="m") is None
    assert store.cancel_run("r") is None


def test_audit_store_create_run_flow():
    factory = _RecordingFactory([
        None,                       # setup_schema
        None,                       # ensure_conversation
        [("CUST001",), ("conv-1",)],  # create_run 内两次存在性校验
    ])
    store = PostgresAuditStore(factory)
    ids = generate_identifiers("conv-1")
    request = RequestEnvelope(
        run_id=ids.run_id,
        trace_id=ids.trace_id,
        user_id=uuid.uuid4(),
        customer_id="CUST001",
        conversation_id="conv-1",
        message_id=ids.message_id,
        message="分析 600519",
    )

    result = store.create_run(request)

    assert result is not None
    statements = [
        s for conn in factory.connections for s in conn.cursor_instance.statements
    ]
    assert any("finance.users" in s for s in statements)
    assert any("finance.conversations" in s for s in statements)
    assert any("finance.conversation_messages" in s for s in statements)
    assert any("finance.agent_runs" in s for s in statements)


def test_orchestrator_audit_expert_result():
    from finance_agent.orchestrator.orchestrator import AdvisorSystem

    class _RecordingAudit:
        def __init__(self):
            self.calls = []

        def is_available(self):
            return True

        def upsert_expert_result(self, run_id, trace_id, result):
            self.calls.append((run_id, trace_id, result.expert_name))

    system = object.__new__(AdvisorSystem)
    system.audit = _RecordingAudit()
    state = {"run_id": "run-1", "trace_id": "trace-1", "stock_analysis": {"600519": {}}}
    system._audit_expert_result(state, "stock_analysis")

    assert len(system.audit.calls) == 1
    assert system.audit.calls[0] == ("run-1", "trace-1", "stock_analysis")


def test_task_result_keeps_research_rule_and_snapshot_fact_ids():
    """股票研究审计必须直接引用规则版本和原始快照事实。"""
    from datetime import datetime, timezone
    from finance_agent.contracts import FactSnapshot
    from finance_agent.orchestrator.orchestrator import AdvisorSystem

    system = object.__new__(AdvisorSystem)
    task = Task(
        task_id="task-1",
        intent=IntentKind.MARKET_QUERY,
        expert_name="stock_analysis",
    )
    state = {
        "intent_results": {"market_query": {"status": "success", "content": "完成"}},
        "analysis_results": [{
            "rule_version": "research_rules/v1",
            "evidence_ids": ["stock_snapshot:600519:fixture"],
        }],
        "facts": [FactSnapshot(
            fact_id="stock_snapshot:600519:fixture",
            domain="stock_research_snapshot",
            source="fixture",
            fetched_at=datetime.now(timezone.utc),
            payload={"code": "600519"},
        )],
    }

    result = system._make_task_result(state, task, "stock_analysis")

    assert result.result_data["analysis_results"][0]["rule_version"] == "research_rules/v1"
    assert "stock_snapshot:600519:fixture" in result.fact_ids
