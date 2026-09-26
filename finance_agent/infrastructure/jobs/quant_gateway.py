"""QuantGateway：CPU 密集计算的提交/状态/取结果 seam（设计 §6.6、§11）。

领域图只依赖本 seam；Celery 是生产 Adapter，测试使用内存 Adapter。提交必须幂等：
相同 idempotency_key 返回同一个 job。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol
from uuid import NAMESPACE_URL, uuid5

from finance_agent.shared.contracts import AsyncJobRef


class QuantGateway(Protocol):
    def submit(
        self,
        kind: str,
        payload: dict[str, Any],
        idempotency_key: str,
        *,
        customer_id: str = "",
        thread_id: str = "",
        run_id: str = "",
        task_id: str = "",
    ) -> AsyncJobRef: ...
    def status(self, job_id: str) -> str: ...
    def result(self, job_id: str) -> dict[str, Any] | None: ...


def _job_id_for(idempotency_key: str) -> str:
    return str(uuid5(NAMESPACE_URL, f"finance.quant:{idempotency_key}"))


@dataclass
class _Job:
    ref: AsyncJobRef
    result: dict[str, Any] | None = None


@dataclass
class InMemoryQuantGateway:
    """同步执行的内存网关，供测试与单进程环境使用。

    ``repository``（可选）与 Celery 网关同义：提交时把 job 引用落库，
    使内存网关也能覆盖"提交—查询—恢复"整条路径的测试。
    """

    _jobs: dict[str, _Job] = field(default_factory=dict)
    _by_key: dict[str, str] = field(default_factory=dict)
    _repository: Any = None

    def submit(
        self,
        kind: str,
        payload: dict[str, Any],
        idempotency_key: str,
        *,
        customer_id: str = "",
        thread_id: str = "",
        run_id: str = "",
        task_id: str = "",
    ) -> AsyncJobRef:
        if not idempotency_key:
            raise ValueError("idempotency_key is required")
        existing = self._by_key.get(idempotency_key)
        if existing is not None:
            return self._jobs[existing].ref

        from finance_agent.infrastructure.jobs.quant_tasks import run_quant_task

        job_id = _job_id_for(idempotency_key)
        # AsyncJobRef.task_id 携带**领域 task_id**（调用方传入），job_id 才是
        # Celery 任务标识：状态端点按 job_id 查询，结论聚合按 task_id 定位。
        # task_id 缺省时回退为 job_id（旧调用方无领域上下文）。
        domain_task_id = task_id or job_id
        try:
            result = run_quant_task(kind, payload)
        except Exception as exc:  # noqa: BLE001 - 任务失败体现在状态与结果里
            ref = AsyncJobRef(job_id=job_id, kind=kind, status="failed", task_id=domain_task_id)
            self._jobs[job_id] = _Job(ref=ref, result={"error": type(exc).__name__})
        else:
            ref = AsyncJobRef(job_id=job_id, kind=kind, status="completed", task_id=domain_task_id)
            self._jobs[job_id] = _Job(ref=ref, result=result)
        self._by_key[idempotency_key] = job_id
        if self._repository is not None and customer_id and thread_id and run_id:
            self._repository.save_job_ref(
                customer_id=customer_id,
                thread_id=thread_id,
                run_id=run_id,
                job=ref,
                idempotency_key=idempotency_key,
            )
        return ref

    def status(self, job_id: str) -> str:
        job = self._jobs.get(job_id)
        return job.ref.status if job is not None else "failed"

    def result(self, job_id: str) -> dict[str, Any] | None:
        job = self._jobs.get(job_id)
        return job.result if job is not None else None


@dataclass
class CeleryQuantGateway:
    """生产网关：把任务投递到 Celery ``finance.quant`` 队列。

    ``async_repository``（可选）用于持久化 job 引用，保证跨进程/重启后的幂等与恢复；
    ``app`` 可注入以便测试，默认真实 Celery 应用。
    """

    app: Any = None
    async_repository: Any = None
    _by_key: dict[str, str] = field(default_factory=dict)

    def _app(self) -> Any:
        if self.app is None:
            from finance_agent.infrastructure.jobs.celery_app import celery_app

            self.app = celery_app
        return self.app

    def submit(
        self,
        kind: str,
        payload: dict[str, Any],
        idempotency_key: str,
        *,
        customer_id: str = "",
        thread_id: str = "",
        run_id: str = "",
        task_id: str = "",
    ) -> AsyncJobRef:
        if not idempotency_key:
            raise ValueError("idempotency_key is required")
        existing = self._by_key.get(idempotency_key)
        if existing is not None:
            return AsyncJobRef(job_id=existing, kind=kind, status="queued", task_id=existing)

        job_id = _job_id_for(idempotency_key)
        self._app().send_task(
            "finance.quant.run",
            args=[kind, payload],
            task_id=job_id,
            queue=_quant_queue(),
        )
        ref = AsyncJobRef(job_id=job_id, kind=kind, status="queued", task_id=job_id)
        self._by_key[idempotency_key] = job_id
        if self.async_repository is not None and customer_id and thread_id and run_id:
            self.async_repository.save_job_ref(
                customer_id=customer_id,
                thread_id=thread_id,
                run_id=run_id,
                job=ref,
                idempotency_key=idempotency_key,
            )
        return ref

    def status(self, job_id: str) -> str:
        from celery.result import AsyncResult

        state = AsyncResult(job_id, app=self._app()).state
        return {
            "PENDING": "queued",
            "RECEIVED": "queued",
            "STARTED": "running",
            "RETRY": "running",
            "SUCCESS": "completed",
            "FAILURE": "failed",
            "REVOKED": "cancelled",
        }.get(state, "queued")

    def result(self, job_id: str) -> dict[str, Any] | None:
        from celery.result import AsyncResult

        async_result = AsyncResult(job_id, app=self._app())
        if not async_result.successful():
            return None
        value = async_result.result
        return value.get("result") if isinstance(value, dict) else value


def _quant_queue() -> str:
    from finance_agent.infrastructure import settings as config

    return config.CELERY_QUANT_QUEUE


__all__ = ["CeleryQuantGateway", "InMemoryQuantGateway", "QuantGateway"]
