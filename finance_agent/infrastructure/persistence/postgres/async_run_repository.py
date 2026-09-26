"""PostgreSQL 可恢复异步任务引用与结论仓储。"""

from __future__ import annotations

import json
from typing import Any
from uuid import uuid4

from finance_agent.shared.contracts import AsyncJobRef
from finance_agent.infrastructure.persistence.postgres.connection import _PostgresRepository


class PostgresAsyncRunRepository(_PostgresRepository):
    """异步任务的可恢复引用仓储。"""

    def save_job_ref(
        self,
        *,
        customer_id: str,
        thread_id: str,
        run_id: str,
        job: AsyncJobRef,
        idempotency_key: str,
    ) -> None:
        self._ensure_schema()
        with self._transaction() as connection:
            cursor = connection.cursor()
            try:
                cursor.execute(
                    """INSERT INTO finance.async_jobs
                       (job_id, customer_id, thread_id, run_id, task_id, kind, status, idempotency_key, result_ref)
                       VALUES (%s, %s, %s, %s, %s, %s, %s, %s, '')
                       ON CONFLICT (idempotency_key) DO UPDATE SET
                         job_id = EXCLUDED.job_id,
                         thread_id = EXCLUDED.thread_id,
                         run_id = EXCLUDED.run_id,
                         task_id = EXCLUDED.task_id,
                         kind = EXCLUDED.kind,
                         status = EXCLUDED.status,
                         updated_at = now()""",
                    (job.job_id, customer_id, thread_id, run_id, job.task_id, job.kind, job.status, idempotency_key),
                )
            finally:
                cursor.close()

    def get_job_ref(self, job_id: str, customer_id: str) -> AsyncJobRef | None:
        self._ensure_schema()
        with self._transaction() as connection:
            cursor = connection.cursor()
            try:
                cursor.execute(
                    """SELECT job_id, kind, status, task_id
                       FROM finance.async_jobs
                       WHERE job_id = %s AND customer_id = %s""",
                    (job_id, customer_id),
                )
                row = cursor.fetchone()
            finally:
                cursor.close()
        if row is None:
            return None
        return AsyncJobRef(job_id=row[0], kind=row[1], status=row[2], task_id=row[3])

    def list_job_refs(self, thread_id: str) -> list[AsyncJobRef]:
        """列出某线程下的异步任务引用，供恢复协调器扫描。"""
        self._ensure_schema()
        with self._transaction() as connection:
            cursor = connection.cursor()
            try:
                cursor.execute(
                    """SELECT job_id, kind, status, task_id
                       FROM finance.async_jobs
                       WHERE thread_id = %s
                       ORDER BY created_at""",
                    (thread_id,),
                )
                rows = cursor.fetchall()
            finally:
                cursor.close()
        return [
            AsyncJobRef(job_id=row[0], kind=row[1], status=row[2], task_id=row[3])
            for row in rows
        ]

    def save_pending_outcome(
        self,
        *,
        customer_id: str,
        thread_id: str,
        run_id: str,
        conversation_id: str,
        job_id: str,
        outcome: dict[str, Any],
        code: str = "",
    ) -> None:
        """落库一条待完成的领域结论快照（按 job_id 幂等 upsert）。

        以 ``job_id`` 为主键：一次领域执行提交的每个量化任务各一行，共享同一份
        结论快照；重复写入（同 job 重试）只更新，不产生多行。``code`` 记录该
        job 对应的标的，恢复时据此把指标合并回 ``technical_analysis[code]``。
        """
        if not job_id:
            raise ValueError("pending outcome requires a job_id")
        task_id = str(outcome.get("task_id") or "")
        if not task_id:
            raise ValueError("pending outcome requires a task_id")
        self._ensure_schema()
        with self._transaction() as connection:
            cursor = connection.cursor()
            try:
                cursor.execute(
                    """INSERT INTO finance.pending_outcomes
                       (job_id, task_id, code, customer_id, thread_id, run_id, conversation_id, outcome)
                       VALUES (%s, %s, %s, %s, %s, %s, %s, %s::jsonb)
                       ON CONFLICT (job_id) DO UPDATE SET
                         task_id = EXCLUDED.task_id,
                         code = EXCLUDED.code,
                         customer_id = EXCLUDED.customer_id,
                         thread_id = EXCLUDED.thread_id,
                         run_id = EXCLUDED.run_id,
                         conversation_id = EXCLUDED.conversation_id,
                         outcome = EXCLUDED.outcome,
                         updated_at = now()""",
                    (
                        job_id, task_id, code, customer_id, thread_id,
                        run_id, conversation_id, json.dumps(outcome, ensure_ascii=False),
                    ),
                )
            finally:
                cursor.close()

    def get_pending_outcome(self, job_id: str, customer_id: str) -> dict[str, Any] | None:
        """取回待完成结论快照；按 customer_id 隔离，非本人任务返回 None。"""
        return self._load_pending_outcome(job_id, customer_id=customer_id)

    def get_pending_outcome_by_job(self, job_id: str) -> dict[str, Any] | None:
        """按 job_id 取快照（不校验归属）；仅供编排进程内部恢复使用。"""
        return self._load_pending_outcome(job_id, customer_id="")

    def _load_pending_outcome(
        self, job_id: str, *, customer_id: str
    ) -> dict[str, Any] | None:
        self._ensure_schema()
        with self._transaction() as connection:
            cursor = connection.cursor()
            try:
                if customer_id:
                    cursor.execute(
                        """SELECT outcome, task_id, code, conversation_id, thread_id, run_id
                           FROM finance.pending_outcomes
                           WHERE job_id = %s AND customer_id = %s""",
                        (job_id, customer_id),
                    )
                else:
                    cursor.execute(
                        """SELECT outcome, task_id, code, conversation_id, thread_id, run_id
                           FROM finance.pending_outcomes
                           WHERE job_id = %s""",
                        (job_id,),
                    )
                row = cursor.fetchone()
            finally:
                cursor.close()
        if row is None:
            return None
        outcome = row[0]
        if isinstance(outcome, str):
            outcome = json.loads(outcome)
        return {
            "outcome": outcome,
            "task_id": row[1],
            "code": row[2],
            "conversation_id": row[3],
            "thread_id": row[4],
            "run_id": row[5],
        }

    def delete_pending_outcome(self, job_id: str) -> None:
        """删除该 job 的快照行（该 job 已收尾）。"""
        self._ensure_schema()
        with self._transaction() as connection:
            cursor = connection.cursor()
            try:
                cursor.execute(
                    "DELETE FROM finance.pending_outcomes WHERE job_id = %s", (job_id,)
                )
            finally:
                cursor.close()

    def list_pending_outcomes_for_task(self, task_id: str) -> list[dict[str, Any]]:
        """列出同一领域任务下仍待完成的 job 行（判定该结论是否可收尾）。"""
        self._ensure_schema()
        with self._transaction() as connection:
            cursor = connection.cursor()
            try:
                cursor.execute(
                    """SELECT job_id, code, outcome, conversation_id
                       FROM finance.pending_outcomes
                       WHERE task_id = %s
                       ORDER BY created_at""",
                    (task_id,),
                )
                rows = cursor.fetchall()
            finally:
                cursor.close()
        results: list[dict[str, Any]] = []
        for row in rows:
            outcome = row[2]
            if isinstance(outcome, str):
                outcome = json.loads(outcome)
            results.append(
                {
                    "job_id": row[0], "code": row[1],
                    "outcome": outcome, "conversation_id": row[3],
                }
            )
        return results

    def list_pending_outcomes(self, thread_id: str) -> list[dict[str, Any]]:
        """列出某线程下全部待完成结论快照（供批量恢复/观测）。"""
        self._ensure_schema()
        with self._transaction() as connection:
            cursor = connection.cursor()
            try:
                cursor.execute(
                    """SELECT job_id, task_id, outcome, conversation_id
                       FROM finance.pending_outcomes
                       WHERE thread_id = %s
                       ORDER BY created_at""",
                    (thread_id,),
                )
                rows = cursor.fetchall()
            finally:
                cursor.close()
        results: list[dict[str, Any]] = []
        for row in rows:
            outcome = row[2]
            if isinstance(outcome, str):
                outcome = json.loads(outcome)
            results.append(
                {
                    "job_id": row[0], "task_id": row[1],
                    "outcome": outcome, "conversation_id": row[3],
                }
            )
        return results


__all__ = ["PostgresAsyncRunRepository"]
