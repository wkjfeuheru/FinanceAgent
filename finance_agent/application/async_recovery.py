"""异步量化任务的恢复协作器（Task 3，设计 §11）。

从 ``AdvisorSystem`` 抽出的"异步恢复"职责：状态查询端点与停止撤销都经这里，
把 ``resolve_run_status`` / 恢复渲染 / 快照落库 / 指标合并聚到一处，宿主的
``AdvisorSystem`` 只保留同名薄方法转发，公共签名与响应字段不变。

恢复运行时（仓储读 job、网关查状态、runner 续跑）由 ``RepositoryQuantRuntime``
组合，复用既有的 ``ResumeCoordinator`` 把关"取消忽略 + 仅完成才恢复"。
"""

from __future__ import annotations

import logging
from typing import Any, Protocol

from finance_agent.orchestration.contracts import (
    DEFAULT_JOB_RUN_STATUS,
    JOB_STATUS_TO_RUN_STATUS,
)
from finance_agent.orchestration.persistence_database import get_database
from finance_agent.orchestration.runtime.thread_key import build_thread_id

logger = logging.getLogger(__name__)


class _Host(Protocol):
    """QuantRecovery 依赖的宿主能力（由 AdvisorSystem 提供）。"""

    def _get_async_run_repository(self): ...
    def _get_quant_gateway(self): ...
    def _best_effort(self, category: str, action: Any) -> None: ...


class QuantRecovery:
    """异步量化任务的查询、恢复、撤销与快照落库。"""

    def __init__(self, host: _Host) -> None:
        self._host = host

    # ── 状态查询 / 恢复 ──────────────────────────────────────────────

    def resolve_run_status(self, task_id: str, customer_id: str) -> dict[str, Any]:
        """查询异步量化任务状态；完成时恢复原会话并返回渲染后的答复。

        ``task_id`` 即 Celery ``job_id``（``project_supervisor_state`` 的
        ``pending_task_ids`` 返回真实 job_id）。归属校验：仓储按 customer_id
        隔离，非本人任务返回 not_found。
        """
        repository = self._host._get_async_run_repository()
        job = repository.get_job_ref(task_id, customer_id)
        if job is None:
            return {
                "run_status": "not_found", "task_id": task_id,
                "response": "", "conversation_id": "",
            }
        status = self._host._get_quant_gateway().status(task_id)
        run_status = JOB_STATUS_TO_RUN_STATUS.get(status, DEFAULT_JOB_RUN_STATUS)
        if run_status != "completed":
            # cancelled：迟到成功结果必须忽略，不恢复。
            return {
                "run_status": run_status, "task_id": task_id,
                "response": "", "conversation_id": "", "warnings": [],
            }

        # 已完成：恢复原会话（合并指标 → 重渲染 → 过合规），不重跑已完成任务。
        recovered = self.recover_completed_job(task_id, customer_id)
        if not recovered.get("response"):
            # 同一领域可能并发提交多个标的的计算任务；当前完成不代表兄弟任务也已完成。
            return {
                "run_status": "processing",
                "task_id": task_id,
                "response": "",
                "conversation_id": recovered.get("conversation_id", ""),
                "warnings": recovered.get("warnings", []),
            }
        return {
            "run_status": "completed",
            "task_id": task_id,
            "response": recovered.get("response", "量化任务已完成。"),
            "conversation_id": recovered.get("conversation_id", ""),
            "warnings": recovered.get("warnings", []),
        }

    def recover_completed_job(self, job_id: str, customer_id: str) -> dict[str, Any]:
        """恢复一个已完成的量化任务：合并指标、重跑合规、写回原会话。

        快照按 job_id 定位（归属已由 get_job_ref 按 customer_id 校验）。恢复
        runner 经 ResumeCoordinator 触发，保证"取消忽略 + 仅完成才恢复"的
        把关与批量扫描路径一致。
        """
        from finance_agent.infrastructure.jobs.resume import ResumeCoordinator

        repository = self._host._get_async_run_repository()
        snapshot = repository.get_pending_outcome(job_id, customer_id)
        if snapshot is None:
            # 无快照（可能已被前一次恢复收尾）：只报告完成，不重复渲染。
            return {"response": "量化任务已完成。", "conversation_id": "", "warnings": []}
        thread_id = str(snapshot.get("thread_id") or "")
        ref = repository.get_job_ref(job_id, customer_id)
        coordinator = ResumeCoordinator(self.quant_runtime())
        try:
            result = coordinator.resume_job(thread_id, ref)
        except Exception:  # noqa: BLE001 - 恢复失败降级为状态报告，不抛给端点
            logger.warning("quant_resume_failed job_id=%s", job_id, exc_info=True)
            result = None
        if not isinstance(result, dict):
            return {"response": "量化任务已完成。", "conversation_id": "", "warnings": []}
        return result

    def quant_runtime(self):
        """构造恢复运行时：仓储读 job、网关查状态、runner 执行恢复。"""
        from finance_agent.infrastructure.jobs.resume import RepositoryQuantRuntime

        return RepositoryQuantRuntime(
            self._host._get_quant_gateway(),
            self._host._get_async_run_repository(),
            resume_runner=self.resume_quant_job,
        )

    def resume_quant_job(self, thread_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        """恢复 runner：合并量化指标、重跑合规、把最终答复写回原会话。

        与 Celery worker 解耦——worker 只计算，恢复由编排进程负责。一次领域
        执行可能提交多个 job（每只标的一个），因此每次恢复都从**全部兄弟 job**
        重算：已完成的指标合并、未完成的保留等待；全部完成才收尾并删除快照。
        """
        repository = self._host._get_async_run_repository()
        gateway = self._host._get_quant_gateway()
        job_id = str(payload.get("job_id", ""))
        snapshot = repository.get_pending_outcome_by_job(job_id)
        if snapshot is None:
            return {"response": "量化任务已完成。", "conversation_id": "", "warnings": []}

        task_id = str(snapshot.get("task_id") or "")
        conversation_id = str(snapshot.get("conversation_id") or "")
        rows = [
            row for row in repository.list_pending_outcomes_for_task(task_id)
        ] or [{
            "job_id": job_id,
            "code": str(snapshot.get("code") or ""),
            "outcome": snapshot.get("outcome") or {},
            "conversation_id": conversation_id,
        }]

        warnings: list[str] = []
        merged: dict[str, Any] = {}
        still_pending = False
        for row in rows:
            status = gateway.status(row["job_id"])
            if status == "cancelled":
                # 取消后的迟到成功结果忽略：该 job 不计入，也不阻塞收尾。
                continue
            if status != "completed":
                still_pending = True
                continue
            indicators = self.merge_quant_indicators(
                row.get("outcome") or {}, row["job_id"], str(row.get("code") or ""),
            )
            if indicators is None:
                warnings.append(f"quant_result_unavailable:{row['job_id']}")
            else:
                merged.update(indicators)

        base = dict(snapshot.get("outcome") or {})
        if still_pending:
            # 仍有兄弟 job 未完成：保留快照，不提前收尾（端点会再被轮询）。
            return {"response": "", "conversation_id": conversation_id, "warnings": warnings}

        # 全部完成（或已取消）：合并指标、移除等待限制、重算状态。
        structured = dict(base.get("structured_data") or {})
        structured.pop("pending_jobs", None)
        structured.pop("pending_job_codes", None)
        if merged:
            structured["technical_analysis"] = {
                **(structured.get("technical_analysis") or {}), **merged,
            }
        limitations = [
            item for item in (base.get("limitations") or []) if item != "awaiting_quant"
        ]
        if not merged:
            limitations.append("quant_result_unavailable")
        base.update(
            status="success" if not limitations else "partial",
            structured_data=structured,
            limitations=limitations,
            pending_jobs=[],
        )
        for row in rows:
            repository.delete_pending_outcome(row["job_id"])

        response = self.render_recovered_response(base)
        from finance_agent.orchestration.graphs.compliance import run_compliance

        try:
            result = run_compliance(draft=response)
            response = result.response
            if result.action == "blocked":
                warnings.append("compliance_blocked")
        except Exception:  # noqa: BLE001 - 合规不可用不改写，但仍返回结果
            logger.warning("quant_resume_compliance_failed job_id=%s", job_id, exc_info=True)

        self.append_recovered_message(
            conversation_id, task_id, str(base.get("summary") or ""), response,
        )
        return {"response": response, "conversation_id": conversation_id, "warnings": warnings}

    def merge_quant_indicators(
        self, outcome: dict[str, Any], job_id: str, code: str,
    ) -> dict[str, Any] | None:
        """把该 job 的量化指标并入 ``technical_analysis[code]``；无结果返回 None。"""
        result = self._host._get_quant_gateway().result(job_id)
        if not isinstance(result, dict):
            return None
        indicators = result.get("indicators")
        if not isinstance(indicators, dict) or not code:
            return None
        return {code: indicators}

    @staticmethod
    def render_recovered_response(outcome: dict[str, Any]) -> str:
        """由恢复后的结论渲染最终答复（保留原 summary 并追加完成提示）。"""
        summary = str(outcome.get("summary") or "").strip()
        note = "技术指标计算已完成，以上结论已更新。"
        return f"{summary}\n\n{note}" if summary else note

    def append_recovered_message(
        self, conversation_id: str, task_id: str, summary: str, response: str,
    ) -> None:
        """把恢复后的答复写回原会话（尽力而为，不阻塞状态端点返回）。"""
        if not conversation_id or not response:
            return

        def _write() -> None:
            db = get_database()
            db.append_conversation_message(
                conversation_id, "assistant", response, {"recovered_task_id": task_id},
            )

        self._host._best_effort("persist_recovered_message", _write)

    # ── 快照落库 / 撤销 ──────────────────────────────────────────────

    def persist_pending_outcomes(
        self, state: dict[str, Any], *, customer_id: str, conversation_id: str,
    ) -> None:
        """把 processing 结论（含 pending_jobs）按 job_id 落库为快照。

        仅在结论确实携带 pending_jobs 时写入；写入是尽力而为：失败只记降级
        计数，不影响本轮响应。快照记录 thread_id/run_id 与标的代码，供状态端点
        在量化任务完成后合并指标、恢复原会话。
        """
        outcomes = (state.get("task_results") or {}) if isinstance(state, dict) else {}
        for value in outcomes.values():
            if not isinstance(value, dict) or value.get("status") != "processing":
                continue
            refs = list(value.get("pending_jobs") or [])
            structured = value.get("structured_data") or {}
            if isinstance(structured, dict):
                refs += list(structured.get("pending_jobs") or [])
            if not refs:
                continue
            codes = (
                structured.get("pending_job_codes")
                if isinstance(structured, dict) else None
            ) or {}
            run_id = str(state.get("run_id", ""))
            thread_id = str(state.get("thread_id", ""))

            def _save(refs=refs, codes=codes, outcome=value, run_id=run_id, thread_id=thread_id) -> None:
                repository = self._host._get_async_run_repository()
                for ref in refs:
                    if not isinstance(ref, dict) or not ref.get("job_id"):
                        continue
                    repository.save_pending_outcome(
                        customer_id=customer_id,
                        thread_id=thread_id,
                        run_id=run_id,
                        conversation_id=conversation_id,
                        job_id=str(ref["job_id"]),
                        outcome=outcome,
                        code=str(codes.get(str(ref["job_id"]), "")),
                    )

            self._host._best_effort("persist_pending_outcomes", _save)

    def revoke_quant_jobs(self, customer_id: str, conversation_id: str) -> list[str]:
        """撤销该会话名下 queued/running 的量化任务；返回被撤销的 job 列表。"""
        if not customer_id or not conversation_id:
            return []
        try:
            from finance_agent.infrastructure.jobs.resume import (
                RepositoryQuantRuntime,
                ResumeCoordinator,
            )

            repository = self._host._get_async_run_repository()
            runtime = RepositoryQuantRuntime(
                self._host._get_quant_gateway(), repository,
            )
            coordinator = ResumeCoordinator(runtime)
            thread_id = build_thread_id(customer_id, conversation_id)
            return coordinator.cancel(thread_id)
        except Exception:  # noqa: BLE001 - 撤销失败不得影响停止语义
            logger.warning(
                "quant_revoke_failed conversation_id=%s", conversation_id, exc_info=True,
            )
            return []


__all__ = ["QuantRecovery"]
