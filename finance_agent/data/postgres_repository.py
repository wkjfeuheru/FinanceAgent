"""PostgreSQL 业务运行审计访问层。"""

from __future__ import annotations

import json
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any, Iterator
from uuid import UUID, uuid4, uuid5

from finance_agent.contracts import DispatchPlan, ExpertResult, RequestEnvelope


def _json_object(value: Any) -> Any:
    """把 JSONB 列读出的值统一为 Python 对象。

    psycopg 通常已把 JSONB 解码为对象，但驱动可配置为返回字符串；
    重放要求两种形态都能读，因此这里做一次兼容解析。
    """
    if value is None or isinstance(value, (dict, list)):
        return value
    try:
        return json.loads(value)
    except (TypeError, ValueError):
        return None


class PostgresRuntimeRepository:
    """使用 DB-API 连接执行运行审计事务。"""

    def __init__(self, connection_factory):
        self._connection_factory = connection_factory

    @contextmanager
    def _transaction(self) -> Iterator[Any]:
        """提交成功事务，异常时回滚并关闭连接。"""
        connection = self._connection_factory()
        try:
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def create_run(
        self,
        request: RequestEnvelope,
        dispatch_plan: DispatchPlan | None = None,
    ) -> dict[str, Any]:
        """确认用户和会话，并原子写入用户消息与初始运行记录。"""
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
        """应用业务基础表与运行审计表 DDL（幂等）。"""
        from finance_agent.data.postgres_schema import (
            AGENT_RUNTIME_SCHEMA_SQL,
            BASE_SCHEMA_SQL,
            IDENTITY_MIGRATION_SQL,
            RESEARCH_GOVERNANCE_SCHEMA_SQL,
        )

        with self._transaction() as connection:
            cursor = connection.cursor()
            try:
                cursor.execute(BASE_SCHEMA_SQL)
                cursor.execute(AGENT_RUNTIME_SCHEMA_SQL)
                cursor.execute(IDENTITY_MIGRATION_SQL)
                cursor.execute(RESEARCH_GOVERNANCE_SCHEMA_SQL)
            finally:
                cursor.close()

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


class ResearchRunRepository:
    """持久化可重放的确定性研究运行及其股票结论。"""

    def __init__(self, connection_factory):
        self._connection_factory = connection_factory

    def save(
        self,
        result: Any,
        *,
        snapshot_manifest: list[dict[str, Any]],
        run_id: str | None,
        customer_id: str,
        conversation_id: str,
        status: str = "completed",
        exclusion_reason: str = "",
    ) -> str:
        """原子保存研究输入、快照清单、规则版本与每个标的的结论。"""
        if result.request is None:
            raise ValueError("研究结果缺少请求，无法持久化")
        exclusions = ([
            {"stock_code": code, "reason": exclusion_reason}
            for code in result.request.stock_codes if exclusion_reason
        ])
        return self.save_many(
            request=result.request, results=[result], snapshot_manifest=snapshot_manifest,
            active_members=[], exclusions=exclusions, run_id=run_id,
            customer_id=customer_id, conversation_id=conversation_id, status=status,
        )

    def save_many(
        self,
        *,
        request: Any,
        results: list[Any],
        snapshot_manifest: list[dict[str, Any]],
        active_members: list[dict[str, Any]],
        exclusions: list[dict[str, Any]],
        run_id: str | None,
        customer_id: str,
        conversation_id: str,
        status: str = "completed",
    ) -> str:
        """原子保存一次研究运行及多个标的独立结果。"""
        if request is None:
            raise ValueError("研究运行缺少请求，无法持久化")
        research_run_id = str(uuid4())
        if run_id:
            try:
                research_run_id = str(uuid5(UUID(str(run_id)), "research"))
            except (ValueError, AttributeError):
                pass
        request_data = request.model_dump(mode="json") if hasattr(request, "model_dump") else dict(request)
        request_data["profile_complete"] = bool(getattr(request, "profile_complete", False))
        rule_version = next((str(getattr(item, "rule_version", "")) for item in results if getattr(item, "rule_version", "")), "")
        manifest = {"snapshots": list(snapshot_manifest), "active_members": list(active_members), "exclusions": list(exclusions)}
        connection = self._connection_factory()
        try:
            cursor = connection.cursor()
            try:
                cursor.execute(
                    """
                    INSERT INTO finance.research_runs
                    (research_run_id, agent_run_id, customer_id, conversation_id, request_data,
                     snapshot_manifest, rule_version, status)
                    VALUES (%s, %s, %s, %s, %s::jsonb, %s::jsonb, %s, %s)
                    ON CONFLICT (research_run_id) DO UPDATE SET
                        request_data = EXCLUDED.request_data,
                        snapshot_manifest = EXCLUDED.snapshot_manifest,
                        rule_version = EXCLUDED.rule_version,
                        status = EXCLUDED.status
                    """,
                    (
                        research_run_id,
                        run_id,
                        customer_id,
                        conversation_id,
                        json.dumps(request_data, ensure_ascii=False),
                        json.dumps(manifest, ensure_ascii=False),
                        rule_version,
                        status,
                    ),
                )
                cursor.execute(
                    "DELETE FROM finance.research_results WHERE research_run_id = %s",
                    (research_run_id,),
                )
                for item in results:
                    item_request = getattr(item, "request", None)
                    stock_codes = list(getattr(item_request, "stock_codes", []) or [])
                    stock_code = stock_codes[0] if stock_codes else ""
                    cursor.execute(
                        """
                        INSERT INTO finance.research_results
                        (result_id, research_run_id, stock_code, action, scores, fact_ids, exclusion_reason)
                        VALUES (%s, %s, %s, %s, %s::jsonb, %s::jsonb, %s)
                        """,
                        (
                            str(uuid4()),
                            research_run_id,
                            stock_code,
                            item.action.value,
                            json.dumps(item.scores, ensure_ascii=False),
                            json.dumps(item.evidence_ids, ensure_ascii=False),
                            "",
                        ),
                    )
                for exclusion in exclusions:
                    cursor.execute(
                        """
                        INSERT INTO finance.research_results
                        (result_id, research_run_id, stock_code, action, scores, fact_ids, exclusion_reason)
                        VALUES (%s, %s, %s, %s, %s::jsonb, %s::jsonb, %s)
                        """,
                        (str(uuid4()), research_run_id, str(exclusion.get("stock_code", "")),
                         "数据不足", "{}", "[]", str(exclusion.get("reason", ""))),
                    )
            finally:
                cursor.close()
            connection.commit()
            return research_run_id
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def load(self, research_run_id: str) -> dict[str, Any] | None:
        """读取一次研究运行及其标的结论，供审计重放复算使用。"""
        if not research_run_id:
            return None
        connection = self._connection_factory()
        try:
            cursor = connection.cursor()
            try:
                cursor.execute(
                    """
                    SELECT research_run_id, agent_run_id, customer_id, conversation_id,
                           request_data, snapshot_manifest, rule_version, status
                    FROM finance.research_runs
                    WHERE research_run_id = %s
                    """,
                    (research_run_id,),
                )
                run = cursor.fetchone()
                if not run:
                    return None
                cursor.execute(
                    """
                    SELECT stock_code, action, scores, fact_ids, exclusion_reason
                    FROM finance.research_results
                    WHERE research_run_id = %s
                    ORDER BY stock_code
                    """,
                    (research_run_id,),
                )
                rows = cursor.fetchall() or []
            finally:
                cursor.close()
        finally:
            connection.close()
        return {
            "research_run_id": str(run[0]),
            "agent_run_id": str(run[1]) if run[1] else None,
            "customer_id": run[2],
            "conversation_id": run[3],
            "request_data": _json_object(run[4]),
            "snapshot_manifest": _json_object(run[5]) or [],
            "rule_version": run[6],
            "status": run[7],
            "results": [
                {
                    "stock_code": row[0],
                    "action": row[1],
                    "scores": _json_object(row[2]) or {},
                    "fact_ids": _json_object(row[3]) or [],
                    "exclusion_reason": row[4] or "",
                }
                for row in rows
            ],
        }


class PostgresAuditStore:
    """可选的 PostgreSQL 运行审计存储。

    未配置 POSTGRES_DSN 或驱动缺失时 ``is_available()`` 返回 False，
    所有操作退化为 no-op，不阻断主流程。
    """

    def __init__(self, connection_factory=None):
        self._repository = (
            PostgresRuntimeRepository(connection_factory) if connection_factory else None
        )
        self._research_repository = (
            ResearchRunRepository(connection_factory) if connection_factory else None
        )
        self._schema_ready = False

    @classmethod
    def from_config(cls):
        from finance_agent.config import get_postgres_connection_factory
        return cls(get_postgres_connection_factory())

    def is_available(self) -> bool:
        return self._repository is not None

    def _ensure_schema(self) -> None:
        if self._schema_ready or not self._repository:
            return
        try:
            self._repository.setup_schema()
            self._schema_ready = True
        except Exception:
            pass

    def create_run(self, request: Any, dispatch_plan: Any = None) -> dict[str, Any] | None:
        if not self._repository:
            return None
        try:
            self._ensure_schema()
            self._repository.ensure_conversation(request.customer_id, request.conversation_id)
            return self._repository.create_run(request, dispatch_plan)
        except Exception:
            return None

    def upsert_expert_result(self, run_id: str, trace_id: str, result: Any) -> dict[str, Any] | None:
        if not self._repository or not run_id:
            return None
        try:
            return self._repository.upsert_expert_result(run_id, trace_id, result)
        except Exception:
            return None

    def complete_run(
        self, run_id: str, conversation_id: str, response: str,
        *, message_id: str, status: str = "completed", metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any] | None:
        if not self._repository or not run_id:
            return None
        try:
            return self._repository.complete_run(
                run_id, conversation_id, response,
                message_id=message_id, status=status, metadata=metadata,
            )
        except Exception:
            return None

    def cancel_run(self, run_id: str) -> dict[str, Any] | None:
        if not self._repository or not run_id:
            return None
        try:
            return self._repository.cancel_run(run_id)
        except Exception:
            return None

    def save_research_result(
        self,
        result: Any,
        *,
        snapshot_manifest: list[dict[str, Any]],
        run_id: str,
        customer_id: str,
        conversation_id: str,
    ) -> str | None:
        """保存可重放研究结果；审计不可用时不影响对话主流程。"""
        if not self._research_repository:
            return None
        try:
            self._ensure_schema()
            return self._research_repository.save(
                result,
                snapshot_manifest=snapshot_manifest,
                run_id=run_id,
                customer_id=customer_id,
                conversation_id=conversation_id,
            )
        except Exception:
            return None

    def save_research_run(
        self,
        *,
        request: Any,
        results: list[Any],
        snapshot_manifest: list[dict[str, Any]],
        active_members: list[dict[str, Any]],
        exclusions: list[dict[str, Any]],
        run_id: str,
        customer_id: str,
        conversation_id: str,
        status: str,
    ) -> str | None:
        """保存一次可重放的多标的研究运行。"""
        if not self._research_repository:
            return None
        try:
            self._ensure_schema()
            return self._research_repository.save_many(
                request=request, results=results, snapshot_manifest=snapshot_manifest,
                active_members=active_members, exclusions=exclusions, run_id=run_id,
                customer_id=customer_id, conversation_id=conversation_id, status=status,
            )
        except Exception:
            return None

    def load_research_run(self, research_run_id: str) -> dict[str, Any] | None:
        """读取已保存的研究运行；审计不可用时返回 None，不影响调用方。"""
        if not self._research_repository or not research_run_id:
            return None
        try:
            return self._research_repository.load(research_run_id)
        except Exception:
            return None
