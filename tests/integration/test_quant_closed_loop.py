"""异步量化任务闭环：提交上下文、pending_jobs 下传、端点恢复与取消。

覆盖文档 P0 验收标准：幂等单任务、归属隔离、完成后恢复原会话并渲染合规、
取消后忽略迟到结果、pending_task_ids 返回真实 job_id。
"""

from __future__ import annotations

import threading

from finance_agent.shared.contracts import AsyncJobRef
from finance_agent.orchestration.contracts import (
    BusinessDomain,
    DomainOutcome,
)
from finance_agent.application.advisor import AdvisorSystem


class _FakeAsyncRepository:
    """内存异步仓储：实现闭环所需的最小读写接口。"""

    def __init__(self) -> None:
        self.jobs: dict[str, dict] = {}
        self.pending: dict[str, dict] = {}  # job_id -> 快照行

    def save_job_ref(self, *, customer_id, thread_id, run_id, job, idempotency_key) -> None:
        self.jobs[job.job_id] = {
            "job_id": job.job_id, "kind": job.kind, "status": job.status,
            "task_id": job.task_id, "customer_id": customer_id,
            "thread_id": thread_id, "run_id": run_id, "idempotency_key": idempotency_key,
        }

    def get_job_ref(self, job_id: str, customer_id: str) -> AsyncJobRef | None:
        row = self.jobs.get(job_id)
        if row is None or row["customer_id"] != customer_id:
            return None
        return AsyncJobRef(
            job_id=row["job_id"], kind=row["kind"], status=row["status"],
            task_id=row["task_id"],
        )

    def list_job_refs(self, thread_id: str) -> list[AsyncJobRef]:
        return [
            AsyncJobRef(job_id=r["job_id"], kind=r["kind"], status=r["status"], task_id=r["task_id"])
            for r in self.jobs.values() if r["thread_id"] == thread_id
        ]

    def save_pending_outcome(self, *, customer_id, thread_id, run_id,
                             conversation_id, job_id, outcome, code="") -> None:
        self.pending[job_id] = {
            "job_id": job_id, "task_id": outcome["task_id"], "code": code,
            "customer_id": customer_id, "thread_id": thread_id, "run_id": run_id,
            "conversation_id": conversation_id, "outcome": dict(outcome),
        }

    def get_pending_outcome(self, job_id: str, customer_id: str) -> dict | None:
        row = self.pending.get(job_id)
        if row is None or row["customer_id"] != customer_id:
            return None
        return self._snapshot_view(row)

    def get_pending_outcome_by_job(self, job_id: str) -> dict | None:
        row = self.pending.get(job_id)
        return self._snapshot_view(row) if row else None

    @staticmethod
    def _snapshot_view(row: dict) -> dict:
        return {
            "outcome": dict(row["outcome"]), "task_id": row["task_id"], "code": row["code"],
            "conversation_id": row["conversation_id"], "thread_id": row["thread_id"],
            "run_id": row["run_id"],
        }

    def delete_pending_outcome(self, job_id: str) -> None:
        self.pending.pop(job_id, None)

    def list_pending_outcomes_for_task(self, task_id: str) -> list[dict]:
        return [
            {"job_id": r["job_id"], "code": r["code"],
             "outcome": dict(r["outcome"]), "conversation_id": r["conversation_id"]}
            for r in self.pending.values() if r["task_id"] == task_id
        ]

    def list_pending_outcomes(self, thread_id: str) -> list[dict]:
        return [
            {"job_id": r["job_id"], "task_id": r["task_id"],
             "outcome": dict(r["outcome"]), "conversation_id": r["conversation_id"]}
            for r in self.pending.values() if r["thread_id"] == thread_id
        ]


class _ControllableGateway:
    """可切换到 completed 的网关；记录每次 submit 的上下文参数。"""

    def __init__(self) -> None:
        self.submits: list[dict] = []
        self._results: dict[str, dict] = {}
        self._status: dict[str, str] = {}

    def submit(self, kind, payload, idempotency_key, *, customer_id="", thread_id="",
               run_id="", task_id="") -> AsyncJobRef:
        self.submits.append({
            "kind": kind, "key": idempotency_key, "customer_id": customer_id,
            "thread_id": thread_id, "run_id": run_id, "task_id": task_id,
        })
        job_id = f"job-{idempotency_key}"
        self._status.setdefault(job_id, "queued")
        self._results[job_id] = {"indicators": {"MA": {"value": 1.0}}}
        return AsyncJobRef(job_id=job_id, kind=kind, status="queued",
                           task_id=task_id or job_id)

    def status(self, job_id: str) -> str:
        return self._status.get(job_id, "queued")

    def result(self, job_id: str) -> dict | None:
        return self._results.get(job_id)

    def complete(self, job_id: str) -> None:
        self._status[job_id] = "completed"

    def cancel(self, job_id: str) -> None:
        self._status[job_id] = "cancelled"

    def revoke(self, job_id: str) -> None:
        self._status[job_id] = "cancelled"


def _processing_outcome(task_id: str, *, job_ids: list[str]) -> DomainOutcome:
    refs = [
        {"job_id": job_id, "kind": "technical_indicators", "status": "queued", "task_id": task_id}
        for job_id in job_ids
    ]
    return DomainOutcome(
        task_id=task_id,
        domain=BusinessDomain.STOCK_RESEARCH,
        status="processing",
        summary="量化任务处理中。",
        structured_data={
            "technical_analysis": {},
            "pending_jobs": refs,
            "pending_job_codes": {job_ids[0]: "600519"} if job_ids else {},
        },
        limitations=["awaiting_quant"],
        pending_jobs=[AsyncJobRef.model_validate(ref) for ref in refs],
    )


def _system(repository, gateway) -> AdvisorSystem:
    system = object.__new__(AdvisorSystem)
    system._stop_lock = threading.Lock()
    system._stop_requests = {}
    system._active_runs = {}
    system._async_run_repository = repository
    system._quant_gateway = gateway
    system._degradation_lock = threading.Lock()
    system._degradation_counts = {}
    system._get_async_run_repository = lambda: repository
    system._get_quant_gateway = lambda: gateway
    system._bump_degradation = lambda category: None
    return system


def _persisted_message(monkeypatch) -> list:
    captured: list = []
    monkeypatch.setattr(
        "finance_agent.application.async_recovery.get_database",
        lambda: type("DB", (), {
            "append_conversation_message": lambda self, *a, **k: captured.append((a, k)),
        })(),
    )
    return captured


# ── 1. 提交上下文与 pending_jobs 下传 ─────────────────────────────────────


def test_technical_tool_submits_with_customer_context_and_reports_pending_jobs(monkeypatch):
    """量化卸载必须携带归属客户，并回报真实 job_id 与代码。

    重构后股票领域图已删除，提交 seam 收敛到 ``compute_technical`` 工具：
    工具的 ``ExpertSink`` 只保证 ``customer_id``（授权查询与归属隔离的关键项）
    随 submit 下传；``thread_id/run_id/task_id`` 不再经此 seam（恢复路径由
    仓储中的 job 引用与结论的 task_id 承担）。
    """
    import finance_agent.domains.research.expert.tools as tools_stock
    from finance_agent.orchestration.contracts import BusinessDomain
    from finance_agent.orchestration.experts.base import ExpertSink
    from finance_agent.domains.research.expert.tools import compute_technical

    gateway = _ControllableGateway()
    monkeypatch.setattr(tools_stock, "_gateway", lambda: gateway)
    stock_data = {
        "600519": {"history": {"data": [
            {"close": 10.0 + i, "high": 11.0 + i, "low": 9.0 + i} for i in range(80)
        ]}},
    }
    monkeypatch.setattr(
        tools_stock._stockdata, "fetch_stock_data", lambda codes: dict(stock_data),
    )
    sink = ExpertSink(domain=BusinessDomain.STOCK_RESEARCH, customer_id="CUST1")

    compute_technical.invoke(
        {"stock_code": "600519"},
        config={"configurable": {"expert_sink": sink}},
    )

    assert "awaiting_quant" in sink.limitations
    # 归属客户必须落到 submit：缺失则 job 引用无法按客户授权查询。
    submitted = gateway.submits[0]
    assert submitted["customer_id"] == "CUST1"
    assert submitted["kind"] == "technical_indicators"
    refs = sink.extras["pending_jobs"]
    assert refs and sink.extras["pending_job_codes"][refs[0].job_id] == "600519"


def test_projection_reports_real_celery_job_ids():
    from finance_agent.orchestration.graphs.supervisor import project_supervisor_state

    outcome = _processing_outcome("single:run-1:stock_research", job_ids=["job-a", "job-b"])
    state = {
        "run": {
            "routing": {
                "domains": [BusinessDomain.STOCK_RESEARCH.value],
                "execution_mode": "domain_workflow",
            },
            "final_response": "量化任务处理中。",
            "run_status": "processing",
        },
        "task_results": {outcome.task_id: outcome.model_dump(mode="json")},
    }

    projected = project_supervisor_state(state)

    assert projected["pending_task_ids"] == ["job-a", "job-b"]


# ── 2. 快照落库与端点恢复 ───────────────────────────────────────────────


def test_persist_pending_outcomes_writes_snapshot_per_job():
    repository = _FakeAsyncRepository()
    system = _system(repository, _ControllableGateway())
    outcome = _processing_outcome("single:run-1:stock_research", job_ids=["job-a"])
    state = {
        "run_id": "run-1", "thread_id": "v1:CUST1:conv-1",
        "task_results": {outcome.task_id: outcome.model_dump(mode="json")},
    }

    system._persist_pending_outcomes(state, customer_id="CUST1", conversation_id="conv-1")

    assert "job-a" in repository.pending
    row = repository.pending["job-a"]
    assert row["conversation_id"] == "conv-1"
    assert row["code"] == "600519"


def test_resolve_run_status_processing_does_not_recover():
    repository = _FakeAsyncRepository()
    gateway = _ControllableGateway()
    system = _system(repository, gateway)
    repository.save_job_ref(
        customer_id="CUST1", thread_id="v1:CUST1:conv-1", run_id="run-1",
        job=AsyncJobRef(job_id="job-a", kind="technical_indicators",
                        status="queued", task_id="single:run-1:stock_research"),
        idempotency_key="technical_indicators:600519",
    )

    result = system.resolve_run_status("job-a", "CUST1")

    assert result["run_status"] == "processing"
    assert result["response"] == ""


def test_resolve_run_status_completed_job_waits_for_siblings():
    """一个 job 完成但兄弟仍在排队时，端点必须继续报 processing，不能把空答复当终态。"""
    repository = _FakeAsyncRepository()
    gateway = _ControllableGateway()
    system = _system(repository, gateway)
    task_id = "single:run-1:stock_research"
    for job_id in ("job-a", "job-b"):
        repository.save_job_ref(
            customer_id="CUST1", thread_id="v1:CUST1:conv-1", run_id="run-1",
            job=AsyncJobRef(job_id=job_id, kind="technical_indicators",
                            status="queued", task_id=task_id),
            idempotency_key=f"technical_indicators:{job_id}",
        )
        repository.save_pending_outcome(
            customer_id="CUST1", thread_id="v1:CUST1:conv-1", run_id="run-1",
            conversation_id="conv-1", job_id=job_id,
            outcome=_processing_outcome(task_id, job_ids=["job-a", "job-b"]).model_dump(mode="json"),
            code="600519",
        )
    gateway.complete("job-a")

    result = system.resolve_run_status("job-a", "CUST1")

    assert result["run_status"] == "processing"
    assert result["response"] == ""
    assert result["conversation_id"] == "conv-1"
    assert "job-a" in repository.pending
    assert "job-b" in repository.pending


def test_resolve_run_status_completed_recovers_and_persists(monkeypatch):
    repository = _FakeAsyncRepository()
    gateway = _ControllableGateway()
    system = _system(repository, gateway)
    captured = _persisted_message(monkeypatch)

    job = AsyncJobRef(job_id="job-a", kind="technical_indicators",
                      status="queued", task_id="single:run-1:stock_research")
    repository.save_job_ref(
        customer_id="CUST1", thread_id="v1:CUST1:conv-1", run_id="run-1",
        job=job, idempotency_key="technical_indicators:600519",
    )
    outcome = _processing_outcome("single:run-1:stock_research", job_ids=["job-a"])
    repository.save_pending_outcome(
        customer_id="CUST1", thread_id="v1:CUST1:conv-1", run_id="run-1",
        conversation_id="conv-1", job_id="job-a", outcome=outcome.model_dump(mode="json"),
        code="600519",
    )
    gateway.complete("job-a")

    result = system.resolve_run_status("job-a", "CUST1")

    assert result["run_status"] == "completed"
    assert result["conversation_id"] == "conv-1"
    assert "已完成" in result["response"] or result["response"]
    # 快照收尾后删除，重复轮询不会重复渲染。
    assert "job-a" not in repository.pending
    # 最终答复写回原会话。
    assert captured and captured[0][0][0] == "conv-1"


def test_resolve_run_status_rejects_other_customer():
    repository = _FakeAsyncRepository()
    system = _system(repository, _ControllableGateway())
    repository.save_job_ref(
        customer_id="CUST1", thread_id="v1:CUST1:conv-1", run_id="run-1",
        job=AsyncJobRef(job_id="job-a", kind="technical_indicators",
                        status="queued", task_id="task"),
        idempotency_key="k",
    )

    assert system.resolve_run_status("job-a", "CUST2")["run_status"] == "not_found"


def test_cancelled_job_is_not_recovered():
    repository = _FakeAsyncRepository()
    gateway = _ControllableGateway()
    system = _system(repository, gateway)
    job = AsyncJobRef(job_id="job-a", kind="technical_indicators",
                      status="queued", task_id="task")
    repository.save_job_ref(
        customer_id="CUST1", thread_id="v1:CUST1:conv-1", run_id="run-1",
        job=job, idempotency_key="k",
    )
    gateway.cancel("job-a")

    result = system.resolve_run_status("job-a", "CUST1")

    # 取消后即便 worker 迟到完成，也按 cancelled 上报且不恢复。
    assert result["run_status"] == "cancelled"


def test_sibling_jobs_block_finalize_until_all_complete(monkeypatch):
    repository = _FakeAsyncRepository()
    gateway = _ControllableGateway()
    system = _system(repository, gateway)
    _persisted_message(monkeypatch)
    task_id = "single:run-1:stock_research"
    for job_id in ("job-a", "job-b"):
        repository.save_job_ref(
            customer_id="CUST1", thread_id="v1:CUST1:conv-1", run_id="run-1",
            job=AsyncJobRef(job_id=job_id, kind="technical_indicators",
                            status="queued", task_id=task_id),
            idempotency_key=f"k:{job_id}",
        )
    repository.save_pending_outcome(
        customer_id="CUST1", thread_id="v1:CUST1:conv-1", run_id="run-1",
        conversation_id="conv-1", job_id="job-a",
        outcome=_processing_outcome(task_id, job_ids=["job-a", "job-b"]).model_dump(mode="json"),
        code="600519",
    )
    repository.save_pending_outcome(
        customer_id="CUST1", thread_id="v1:CUST1:conv-1", run_id="run-1",
        conversation_id="conv-1", job_id="job-b",
        outcome=_processing_outcome(task_id, job_ids=["job-a", "job-b"]).model_dump(mode="json"),
        code="000001",
    )
    gateway.complete("job-a")  # job-b 仍未完成

    result = system.resolve_run_status("job-a", "CUST1")

    # 兄弟任务未完成：不收尾，快照仍在。
    assert result["conversation_id"] == "conv-1"
    assert repository.pending

    gateway.complete("job-b")
    result2 = system.resolve_run_status("job-b", "CUST1")

    assert result2["run_status"] == "completed"
    assert not repository.pending


# ── 3. 取消语义：停止时撤销未开始的量化任务 ─────────────────────────────


def test_request_stop_revokes_pending_quant_jobs():
    repository = _FakeAsyncRepository()
    gateway = _ControllableGateway()
    system = _system(repository, gateway)
    system._active_runs["run-1"] = ("conv-1", "CUST1")
    repository.save_job_ref(
        customer_id="CUST1", thread_id="v1:CUST1:conv-1", run_id="run-1",
        job=AsyncJobRef(job_id="job-a", kind="technical_indicators",
                        status="queued", task_id="task"),
        idempotency_key="k",
    )

    assert system.request_stop(run_id="run-1") is True

    assert gateway.status("job-a") == "cancelled"


def test_gateway_submit_is_idempotent_per_key():
    from finance_agent.infrastructure.jobs.quant_gateway import InMemoryQuantGateway

    gateway = InMemoryQuantGateway()
    first = gateway.submit("technical_indicators", {"high": [1], "low": [1], "close": [1]}, "same-key")
    second = gateway.submit("technical_indicators", {"high": [1], "low": [1], "close": [1]}, "same-key")

    assert first.job_id == second.job_id
