"""运行审计协调器，组合运行时与研究仓储。"""

from __future__ import annotations

import threading
from typing import Any

from finance_agent.infrastructure.persistence.postgres.runtime_repository import PostgresRuntimeRepository
from finance_agent.infrastructure.persistence.postgres.research_repository import ResearchRunRepository


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
        # 懒建表只应执行一次；会话并发后需显式互斥，避免并发 DDL 竞争。
        self._schema_lock = threading.Lock()

    @classmethod
    def from_config(cls):
        from finance_agent.infrastructure.settings import get_postgres_connection_factory
        return cls(get_postgres_connection_factory())

    def is_available(self) -> bool:
        return self._repository is not None

    def _ensure_schema(self) -> None:
        if self._schema_ready or not self._repository:
            return
        with self._schema_lock:
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
                run_id=run_id,
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


__all__ = ["PostgresAuditStore"]
