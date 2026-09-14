"""QuantGateway 与 ResumeCoordinator：幂等、状态、恢复与取消。"""

from __future__ import annotations

import pytest

from finance_agent.orchestrator.contracts import AsyncJobRef
from finance_agent.orchestrator.quant import InMemoryQuantGateway
from finance_agent.orchestrator.resume import ResumeCoordinator


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

    def submit(self, kind, payload, idempotency_key):
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


def test_technical_offload_reports_pending_without_faking_indicators():
    from finance_agent.orchestrator.domains.stock import StockDeps, compute_technical_via_gateway

    gateway = _PendingGateway()
    deps = StockDeps(quant_gateway=gateway, quant_wait_seconds=0.0)

    indicators, pending = compute_technical_via_gateway(
        deps, _stock_data_with_history("600519"), ["600519"]
    )

    assert pending is True
    assert indicators == {}
    assert gateway.submitted == ["technical_indicators"]


def test_technical_offload_returns_indicators_when_gateway_completes():
    from finance_agent.orchestrator.domains.stock import StockDeps, compute_technical_via_gateway
    from finance_agent.orchestrator.quant import InMemoryQuantGateway

    deps = StockDeps(quant_gateway=InMemoryQuantGateway(), quant_wait_seconds=1.0)

    indicators, pending = compute_technical_via_gateway(
        deps, _stock_data_with_history("600519"), ["600519"]
    )

    assert pending is False
    assert set(indicators["600519"]) >= {"MA", "MACD", "KDJ", "RSI", "BOLL", "WR"}


