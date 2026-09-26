"""FAQ persistence ports used by the domain and orchestration layers."""

from __future__ import annotations

from typing import Any, Protocol, Sequence

from finance_agent.shared.contracts import AsyncJobRef


class FaqRepository(Protocol):
    """FAQ 索引发布和查询的持久化边界。"""

    def publish_index(
        self,
        *,
        index_version: str,
        documents: Sequence[dict[str, Any]],
        chunks: Sequence[dict[str, Any]],
    ) -> None: ...

    def search(
        self,
        *,
        query_embedding: Sequence[float],
        query_text: str,
        limit: int,
    ) -> list[dict[str, Any]]: ...


class AsyncRunRepository(Protocol):
    def save_job_ref(
        self,
        *,
        customer_id: str,
        thread_id: str,
        run_id: str,
        job: AsyncJobRef,
        idempotency_key: str,
    ) -> None: ...

    def get_job_ref(self, job_id: str, customer_id: str) -> AsyncJobRef | None: ...

    def save_pending_outcome(
        self,
        *,
        customer_id: str,
        thread_id: str,
        run_id: str,
        conversation_id: str,
        job_id: str,
        outcome: dict[str, Any],
    ) -> None: ...

    def get_pending_outcome(self, job_id: str, customer_id: str) -> dict[str, Any] | None: ...

    def delete_pending_outcome(self, job_id: str) -> None: ...
