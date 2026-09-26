"""PostgreSQL 审计层接入测试。"""

import uuid

from finance_agent.shared.contracts import RequestEnvelope
from finance_agent.shared.identifiers import generate_identifiers
from finance_agent.infrastructure.persistence.postgres.audit_repository import PostgresAuditStore


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


def test_orchestrator_persists_structured_stock_research_with_snapshot_manifest():
    """防止审计只保存文本而遗漏确定性研究的重放输入。"""
    from datetime import datetime, timezone
    from finance_agent.shared.contracts import FactSnapshot
    from finance_agent.application.advisor import AdvisorSystem

    class _RecordingAudit:
        def is_available(self):
            return True

        def upsert_expert_result(self, *args):
            pass

        def save_research_result(self, result, **context):
            self.result = result
            self.context = context

    system = object.__new__(AdvisorSystem)
    system.audit = _RecordingAudit()
    state = {
        "run_id": "run-1", "trace_id": "trace-1", "customer_id": "CUST001",
        "thread_id": "conversation-1",
        "analysis_results": [{
            "request": {"kind": "single_stock", "stock_codes": ["600519"], "profile_complete": True},
            "action": "关注", "data_quality": "complete", "rule_version": "research_rules/v1",
            "scores": {"total": 80.0}, "evidence_ids": ["fact-1"],
            "personalization_status": "personalized", "restrictions": [], "narrative": "", "report_mode": "deterministic",
        }],
        "facts": [FactSnapshot(
            fact_id="fact-1", domain="stock_research_snapshot", source="fixture",
            fetched_at=datetime.now(timezone.utc), payload={"code": "600519"},
        )],
    }

    system._audit_research_results(state)

    assert system.audit.result.rule_version == "research_rules/v1"
    assert system.audit.context["run_id"] == "run-1"
    assert system.audit.context["customer_id"] == "CUST001"
    manifest = system.audit.context["snapshot_manifest"]
    assert len(manifest) == 1
    assert manifest[0]["fact_id"] == "fact-1"
    assert manifest[0]["domain"] == "stock_research_snapshot"
    assert manifest[0]["payload"] == {"code": "600519"}


def test_audit_manifest_written_by_stock_analysis_can_be_replayed():
    """审计写入的清单必须自带重放输入，且能复算出同一结论。

    重构后股票领域图已删除，改为直接用 ``ResearchPipeline`` 产出确定性的
    结论与事实，再走 ``AdvisorSystem._audit_research_results`` 审计与重放。
    """
    from finance_agent.application.advisor import AdvisorSystem
    from finance_agent.domains.research.contracts import AnalysisKind, AnalysisRequest
    from finance_agent.domains.research.evaluation import evaluate
    from finance_agent.domains.research.replay import replay_research_run

    fetched_at = "2026-08-28T08:00:00+00:00"

    class Gateway:
        def get_security_data(self, stock_code: str) -> dict:
            closes = [round(10.0 * 1.004 ** index, 4) for index in range(60)]
            return {
                "basic_info": {"code": stock_code, "name": "测试股票"},
                "quote": {"code": stock_code, "price": closes[-1], "date": "2026-08-28",
                          "adjustment": "raw", "source": "fixture", "fetched_at": fetched_at},
                "history": {"adjustment": "forward", "source": "fixture", "fetched_at": fetched_at,
                            "data": [{"date": "2026-08-28", "close": close} for close in closes]},
                "indicators": {"roe": 18.0, "revenue_yoy": 20.0, "netprofit_yoy": 20.0,
                               "pe_ttm": 18.0, "pb": 2.0, "end_date": "2026-06-30",
                               "ann_date": "2026-08-25", "source": "fixture",
                               "fetched_at": fetched_at},
            }

    request = AnalysisRequest(kind=AnalysisKind.SINGLE_STOCK, stock_codes=["600519"])
    results, facts = evaluate(
        request, user_profile={}, gateway=Gateway(),
    )
    state = {
        "analysis_results": [result.model_dump(mode="json") for result in results],
        "facts": facts,
        "research_request": request.model_dump(mode="json"),
        "run_id": "run-1", "trace_id": "trace-1",
        "customer_id": "CUST001", "thread_id": "conv-1",
    }

    class _RecordingAudit:
        def is_available(self):
            return True

        def upsert_expert_result(self, *args):
            pass

        def save_research_result(self, result, **context):
            self.result = result
            self.context = context

    system = object.__new__(AdvisorSystem)
    system.audit = _RecordingAudit()
    system._audit_research_results(state)

    manifest = system.audit.context["snapshot_manifest"]
    analysis_result = state["analysis_results"][0]
    assert manifest[0]["payload"]["inputs"]["history"]["data"]
    assert manifest[0]["payload"]["evaluated_at"] == fetched_at

    outcome = replay_research_run(
        research_run_id="run-1",
        request_data=analysis_result["request"],
        results=[{
            "stock_code": "600519", "action": analysis_result["action"],
            "scores": analysis_result["scores"], "fact_ids": analysis_result["evidence_ids"],
        }],
        snapshot_manifest=manifest,
        rule_version=analysis_result["rule_version"],
    )

    assert outcome.matched is True
    assert outcome.fact_ids_matched is True
