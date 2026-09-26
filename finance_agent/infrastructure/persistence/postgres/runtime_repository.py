"""PostgreSQL 运行时审计仓储。"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any
from uuid import UUID, uuid5

from finance_agent.shared.contracts import DispatchPlan, ExpertResult, RequestEnvelope
from finance_agent.infrastructure.persistence.postgres.migrations import run_migrations
from finance_agent.infrastructure.persistence.postgres.transaction import TransactionRunner


def _json_object(value: Any) -> Any:
    """把 JSONB 列读出的值统一为 Python 对象。"""
    if value is None or isinstance(value, (dict, list)):
        return value
    try:
        return json.loads(value)
    except (TypeError, ValueError):
        return None


class PostgresRuntimeRepository:
    """使用 DB-API 连接执行运行审计事务。"""

    #: 事务实现复用共享 runner（提交/回滚只有一处）。
    _transaction = TransactionRunner.transaction
    transaction = TransactionRunner.transaction

    def __init__(self, connection_factory):
        self._connection_factory = connection_factory

    def create_run(
        self,
        request: RequestEnvelope,
        dispatch_plan: DispatchPlan | None = None,
    ) -> dict[str, Any]:
        """确认用户和会话，并原子写入用户消息与初始运行记录。

        ``task_dispatch`` 列已**停止写入有效内容**（计划层删除后不再有派发计划，
        调用方也不传 ``dispatch_plan``），恒为 ``[]``。列本身保留以兼容既有
        schema 与读取方，删除列属于独立的迁移轮次；``dispatch_plan`` 参数同类
        （deprecated）。
        """
        task_dispatch = dispatch_plan.model_dump(mode="json")["tasks"] if dispatch_plan else []
        context_summary = {"schema_version": "1.0", "summary": ""}
        fact_manifest: list[str] = []
        model_usage: dict[str, Any] = {"schema_version": "1.0"}
        started_at = request.requested_at.astimezone(timezone.utc)

        with self._transaction() as connection:
            cursor = connection.cursor()
            try:
                cursor.execute(
                    """
                    SELECT customer_id FROM finance.users
                    WHERE customer_id = %s
                    """,
                    (request.customer_id,),
                )
                if cursor.fetchone() is None:
                    raise ValueError("customer_not_found")

                cursor.execute(
                    """
                    SELECT conversation_id FROM finance.conversations
                    WHERE conversation_id = %s AND customer_id = %s
                    """,
                    (request.conversation_id, request.customer_id),
                )
                if cursor.fetchone() is None:
                    raise ValueError("conversation_not_found")

                cursor.execute(
                    """
                    INSERT INTO finance.conversation_messages
                        (message_id, conversation_id, role, content, metadata, created_at)
                    VALUES (%s, %s, 'user', %s, %s::jsonb, %s)
                    """,
                    (
                        str(request.message_id),
                        request.conversation_id,
                        request.message,
                        json.dumps({
                            "schema_version": "1.0",
                            "run_id": str(request.run_id),
                            "trace_id": str(request.trace_id),
                        }),
                        started_at,
                    ),
                )
                cursor.execute(
                    """
                    INSERT INTO finance.agent_runs
                        (run_id, trace_id, customer_id, conversation_id,
                         user_message_id, status, task_dispatch, context_summary,
                         fact_manifest, model_usage, started_at)
                    VALUES (%s, %s, %s, %s, %s, 'running', %s::jsonb, %s::jsonb,
                            %s::jsonb, %s::jsonb, %s)
                    """,
                    (
                        str(request.run_id),
                        str(request.trace_id),
                        request.customer_id,
                        request.conversation_id,
                        str(request.message_id),
                        json.dumps(task_dispatch),
                        json.dumps(context_summary),
                        json.dumps(fact_manifest),
                        json.dumps(model_usage),
                        started_at,
                    ),
                )
            finally:
                cursor.close()

        return {
            "run_id": str(request.run_id),
            "trace_id": str(request.trace_id),
            "conversation_id": request.conversation_id,
            "message_id": str(request.message_id),
            "status": "running",
        }

    def upsert_expert_result(
        self,
        run_id: str,
        trace_id: str,
        result: ExpertResult,
    ) -> dict[str, Any]:
        """按运行和任务 ID 幂等保存专家结果。"""
        now = datetime.now(timezone.utc)
        task_id = result.task_id or result.expert_name
        with self._transaction() as connection:
            cursor = connection.cursor()
            try:
                cursor.execute(
                    """
                    INSERT INTO finance.agent_results
                        (result_id, run_id, trace_id, task_id, intent, expert_name, status,
                         schema_version, summary, result_data, fact_ids,
                         degradation_reason, error_code, created_at, updated_at)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s::jsonb,
                            %s, %s, %s, %s)
                    -- Legacy ON CONFLICT (run_id, expert_name) is no longer sufficient.
                    ON CONFLICT (run_id, task_id) DO UPDATE SET
                        trace_id = EXCLUDED.trace_id,
                        intent = EXCLUDED.intent,
                        expert_name = EXCLUDED.expert_name,
                        status = EXCLUDED.status,
                        schema_version = EXCLUDED.schema_version,
                        summary = EXCLUDED.summary,
                        result_data = EXCLUDED.result_data,
                        fact_ids = EXCLUDED.fact_ids,
                        degradation_reason = EXCLUDED.degradation_reason,
                        error_code = EXCLUDED.error_code,
                        updated_at = EXCLUDED.updated_at
                    """,
                    (
                        str(uuid5(UUID(run_id), task_id)),
                        run_id,
                        trace_id,
                        task_id,
                        result.intent.value if result.intent else "",
                        result.expert_name,
                        result.status.value,
                        result.schema_version,
                        result.summary,
                        json.dumps(result.result_data, ensure_ascii=False),
                        json.dumps(result.fact_ids),
                        result.degradation_reason,
                        result.error_code,
                        now,
                        now,
                    ),
                )
            finally:
                cursor.close()
        return {
            "run_id": run_id,
            "trace_id": trace_id,
            "task_id": task_id,
            "intent": result.intent.value if result.intent else "",
            "expert_name": result.expert_name,
            "status": result.status.value,
        }

    def complete_run(
        self,
        run_id: str,
        conversation_id: str,
        response: str,
        *,
        message_id: str,
        status: str = "completed",
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """原子写入 assistant 消息并将运行置为终态。"""
        completed_at = datetime.now(timezone.utc)
        message_metadata = {
            "schema_version": "1.0",
            "run_id": run_id,
            **(metadata or {}),
        }
        with self._transaction() as connection:
            cursor = connection.cursor()
            try:
                cursor.execute(
                    """
                    INSERT INTO finance.conversation_messages
                        (message_id, conversation_id, role, content, metadata, created_at)
                    VALUES (%s, %s, 'assistant', %s, %s::jsonb, %s)
                    """,
                    (
                        message_id,
                        conversation_id,
                        response,
                        json.dumps(message_metadata, ensure_ascii=False),
                        completed_at,
                    ),
                )
                cursor.execute(
                    """
                    UPDATE finance.agent_runs
                    SET status = %s, final_message_id = %s, completed_at = %s
                    WHERE run_id = %s
                    """,
                    (status, message_id, completed_at, run_id),
                )
            finally:
                cursor.close()
        return {
            "run_id": run_id,
            "conversation_id": conversation_id,
            "message_id": message_id,
            "status": status,
        }

    def cancel_run(self, run_id: str) -> dict[str, Any]:
        """持久化取消标志，保留已提交的专家结果。"""
        with self._transaction() as connection:
            cursor = connection.cursor()
            try:
                cursor.execute(
                    """
                    UPDATE finance.agent_runs
                    SET status = 'cancelled', completed_at = %s
                    WHERE run_id = %s AND status NOT IN ('completed', 'failed', 'cancelled')
                    """,
                    (datetime.now(timezone.utc), run_id),
                )
            finally:
                cursor.close()
        return {"run_id": run_id, "status": "cancelled"}

    def setup_schema(self) -> None:
        """应用业务基础表与运行审计表 DDL（幂等，唯一迁移序列）。"""
        run_migrations(self)

    def ensure_conversation(self, customer_id: str, conversation_id: str) -> None:
        """确保会话基础行存在（幂等）。"""
        with self._transaction() as connection:
            cursor = connection.cursor()
            try:
                cursor.execute(
                    "INSERT INTO finance.conversations (conversation_id, customer_id) VALUES (%s, %s) ON CONFLICT (conversation_id) DO NOTHING",
                    (conversation_id, customer_id),
                )
            finally:
                cursor.close()


__all__ = ["PostgresRuntimeRepository"]
