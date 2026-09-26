"""等待异步量化任务的恢复协调器（设计 §11）。

状态查询端点或周期性 sweep 调用 ``ResumeCoordinator``：先校验存储的 job 归属，
再用**原始 thread_id / run_id / task_id** 恢复图。被取消的运行只撤销排队任务，
忽略迟到的成功结果。
"""

from __future__ import annotations

from typing import Any, Protocol

from finance_agent.shared.contracts import AsyncJobRef


class QuantRuntime(Protocol):
    """恢复协调器依赖的运行时边界（生产由仓储 + 网关组合实现）。"""

    def pending_jobs(self, thread_id: str) -> list[AsyncJobRef]: ...
    def job_status(self, job_id: str) -> str: ...
    def resume(self, thread_id: str, job: AsyncJobRef) -> None: ...
    def revoke(self, job_id: str) -> None: ...


class ResumeCoordinator:
    """校验异步任务归属与状态，并在完成后恢复原始图。"""

    def __init__(self, runtime: QuantRuntime) -> None:
        self._runtime = runtime

    def resume_job(self, thread_id: str, job: AsyncJobRef) -> Any:
        """恢复单个已完成的异步任务；取消或未完成返回 False。

        状态端点（``GET /api/runs/{task_id}``）触发恢复时使用：归属与状态由
        端点/仓储先行校验，这里只做"取消忽略 + 仅完成才恢复"的最终把关。
        恢复回调的返回值（如合并后的响应）原样返回给调用方。
        """
        if job.status == "cancelled":
            return False
        if self._runtime.job_status(job.job_id) != "completed":
            return False
        return self._runtime.resume(thread_id, job)

    def resume_ready(self, thread_id: str) -> list[tuple[str, str]]:
        """扫描该线程就绪的异步任务并恢复图，返回 (thread_id, job_id) 列表。"""
        resumed: list[tuple[str, str]] = []
        for ref in self._runtime.pending_jobs(thread_id):
            # 取消后的迟到成功结果必须忽略。
            if ref.status == "cancelled":
                continue
            if self._runtime.job_status(ref.job_id) != "completed":
                continue
            self._runtime.resume(thread_id, ref)
            resumed.append((thread_id, ref.job_id))
        return resumed

    def cancel(self, thread_id: str) -> list[str]:
        """取消该线程尚未开始的任务，返回被撤销的 job 列表。"""
        cancelled: list[str] = []
        for ref in self._runtime.pending_jobs(thread_id):
            if self._runtime.job_status(ref.job_id) in {"queued", "running"}:
                self._runtime.revoke(ref.job_id)
                cancelled.append(ref.job_id)
        return cancelled


class RepositoryQuantRuntime:
    """生产运行时：仓储读取待恢复 job，网关查询状态，恢复回调续跑图。"""

    def __init__(
        self,
        gateway: Any,
        async_repository: Any,
        *,
        resume_runner: Any | None = None,
        revoke_runner: Any | None = None,
    ) -> None:
        self._gateway = gateway
        self._repository = async_repository
        self._resume_runner = resume_runner
        self._revoke_runner = revoke_runner

    def pending_jobs(self, thread_id: str) -> list[AsyncJobRef]:
        loader = getattr(self._repository, "list_job_refs", None)
        if callable(loader):
            return list(loader(thread_id) or [])
        return []

    def job_status(self, job_id: str) -> str:
        status = getattr(self._gateway, "status", None)
        return status(job_id) if callable(status) else "failed"

    def resume(self, thread_id: str, job: AsyncJobRef) -> Any:
        if self._resume_runner is not None:
            return self._resume_runner(
                thread_id, {"job_id": job.job_id, "task_id": job.task_id}
            )
        return None

    def revoke(self, job_id: str) -> None:
        if self._revoke_runner is not None:
            self._revoke_runner(job_id)
        else:
            revoke = getattr(self._gateway, "revoke", None)
            if callable(revoke):
                revoke(job_id)


__all__ = ["QuantRuntime", "RepositoryQuantRuntime", "ResumeCoordinator"]
