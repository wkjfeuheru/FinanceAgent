"""QuantGateway 与 ResumeCoordinator：幂等、状态、恢复与取消。"""

from __future__ import annotations

import pytest

from finance_agent.shared.contracts import AsyncJobRef
from finance_agent.infrastructure.jobs.quant_gateway import InMemoryQuantGateway
from finance_agent.infrastructure.jobs.resume import ResumeCoordinator


def _payload():
    return {"high": [1.0, 2.0, 3.0], "low": [0.5, 1.5, 2.5], "close": [1.0, 2.0, 3.0]}


def test_gateway_reuses_idempotent_quant_job():
    gateway = InMemoryQuantGateway()

    first = gateway.submit("technical_indicators", _payload(), "key-1")
    second = gateway.submit("technical_indicators", _payload(), "key-1")

    assert second.job_id == first.job_id
    assert gateway.status(first.job_id) == "completed"
    assert gateway.result(first.job_id)["indicators"]


def test_gateway_reports_unknown_job_as_failed():
    gateway = InMemoryQuantGateway()

    assert gateway.status("missing") == "failed"
    assert gateway.result("missing") is None


def test_gateway_records_failed_quant_task():
    gateway = InMemoryQuantGateway()

    ref = gateway.submit("technical_indicators", {"close": []}, "bad-1")

    assert ref.status == "failed"


def test_gateway_requires_idempotency_key():
    gateway = InMemoryQuantGateway()
    with pytest.raises(ValueError):
        gateway.submit("technical_indicators", _payload(), "")


class _FakeRuntime:
    def __init__(self) -> None:
        self.job = AsyncJobRef(job_id="job-1", kind="quant", status="queued", task_id="task-1")
        self.status_value = "completed"
        self.resumed: list[tuple[str, str]] = []
        self.revoked: list[str] = []

    def pending_jobs(self, thread_id: str) -> list[AsyncJobRef]:
        assert thread_id == "v1:CUST1:conv-1"
        return [self.job]

    def job_status(self, job_id: str) -> str:
        return self.status_value

    def resume(self, thread_id: str, job: AsyncJobRef) -> None:
        self.resumed.append((thread_id, job.job_id))

    def revoke(self, job_id: str) -> None:
        self.revoked.append(job_id)


def test_resume_collects_ready_job_with_original_thread_id():
    fake_runtime = _FakeRuntime()

    ResumeCoordinator(fake_runtime).resume_ready("v1:CUST1:conv-1")

    assert fake_runtime.resumed == [("v1:CUST1:conv-1", "job-1")]


def test_resume_ignores_incomplete_and_cancelled_jobs():
    fake_runtime = _FakeRuntime()
    fake_runtime.status_value = "running"
    assert ResumeCoordinator(fake_runtime).resume_ready("v1:CUST1:conv-1") == []

    fake_runtime.status_value = "completed"
    fake_runtime.job = AsyncJobRef(
        job_id="job-1", kind="quant", status="cancelled", task_id="task-1"
    )
    assert ResumeCoordinator(fake_runtime).resume_ready("v1:CUST1:conv-1") == []


def test_cancel_revokes_only_unfinished_jobs():
    fake_runtime = _FakeRuntime()
    fake_runtime.status_value = "queued"

    ResumeCoordinator(fake_runtime).cancel("v1:CUST1:conv-1")

    assert fake_runtime.revoked == ["job-1"]


class _PendingGateway:
    """始终处于 queued：模拟同步预算内未完成的量化任务。"""

    def __init__(self) -> None:
        self.submitted: list[str] = []

    def submit(self, kind, payload, idempotency_key, *, customer_id=""):
        self.submitted.append(kind)
        return AsyncJobRef(job_id="job-x", kind=kind, status="queued", task_id="job-x")

    def status(self, job_id):
        return "queued"

    def result(self, job_id):
        return None


def _stock_data_with_history(code: str, bars: int = 80) -> dict:
    rows = [
        {"close": 10.0 + index, "high": 11.0 + index, "low": 9.0 + index}
        for index in range(bars)
    ]
    return {code: {"history": {"data": rows}}}


def _sink():
    from finance_agent.orchestration.contracts import BusinessDomain
    from finance_agent.orchestration.experts.base import ExpertSink

    return ExpertSink(domain=BusinessDomain.STOCK_RESEARCH, customer_id="CUST1")


def _patch_fetch(monkeypatch, data: dict) -> None:
    import finance_agent.domains.research.expert.tools as tools_stock

    monkeypatch.setattr(tools_stock._stockdata, "fetch_stock_data", lambda codes: {
        code: data[code] for code in codes if code in data
    })


def _patch_gateway(monkeypatch, gateway) -> None:
    import finance_agent.domains.research.expert.tools as tools_stock

    monkeypatch.setattr(tools_stock, "_gateway", lambda: gateway)


def _compute_technical(sink):
    from finance_agent.domains.research.expert.tools import compute_technical

    return compute_technical.invoke(
        {"stock_code": "600519"},
        config={"configurable": {"expert_sink": sink}},
    )


def test_technical_offload_reports_pending_without_faking_indicators(monkeypatch):
    """网关挂起：报"处理中"并携带真实 job_id，绝不编造指标。"""
    gateway = _PendingGateway()
    _patch_fetch(monkeypatch, _stock_data_with_history("600519"))
    _patch_gateway(monkeypatch, gateway)
    sink = _sink()

    _compute_technical(sink)

    assert "awaiting_quant" in sink.limitations
    assert sink.structured.get("technical_analysis") is None
    assert gateway.submitted == ["technical_indicators"]
    # 未完成的 job 必须随结果返回，供上层写入 DomainOutcome.pending_jobs：
    # 端点据此按真实 job_id 恢复，不能只报"处理中"却丢失可查询的标识。
    assert [ref.job_id for ref in sink.extras["pending_jobs"]] == ["job-x"]
    assert sink.extras["pending_job_codes"]["job-x"] == "600519"


def test_technical_offload_returns_indicators_when_gateway_completes(monkeypatch):
    from finance_agent.infrastructure.jobs.quant_gateway import InMemoryQuantGateway

    _patch_fetch(monkeypatch, _stock_data_with_history("600519"))
    _patch_gateway(monkeypatch, InMemoryQuantGateway())
    sink = _sink()

    _compute_technical(sink)

    assert not sink.limitations
    assert sink.extras.get("pending_jobs") is None
    indicators = sink.structured["technical_analysis"]["600519"]
    assert set(indicators) >= {"MA", "MACD", "KDJ", "RSI", "BOLL", "WR"}


