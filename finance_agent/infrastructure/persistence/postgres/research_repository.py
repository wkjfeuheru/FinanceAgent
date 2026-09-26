"""PostgreSQL 可重放研究运行仓储。"""

from __future__ import annotations

import json
from typing import Any
from uuid import UUID, uuid4, uuid5

from finance_agent.infrastructure.persistence.postgres.transaction import TransactionRunner


def _json_object(value: Any) -> Any:
    """把 JSONB 列读出的值统一为 Python 对象。"""
    if value is None or isinstance(value, (dict, list)):
        return value
    try:
        return json.loads(value)
    except (TypeError, ValueError):
        return None


class ResearchRunRepository:
    """持久化可重放的确定性研究运行及其股票结论。"""

    #: 事务实现复用共享 runner（提交/回滚只有一处）。
    _transaction = TransactionRunner.transaction
    transaction = TransactionRunner.transaction

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
    ) -> str:
        """原子保存研究输入、快照清单、规则版本与每个标的的结论。"""
        if result.request is None:
            raise ValueError("研究结果缺少请求，无法持久化")
        return self.save_many(
            request=result.request, results=[result], snapshot_manifest=snapshot_manifest,
            run_id=run_id,
            customer_id=customer_id, conversation_id=conversation_id, status=status,
        )

    def save_many(
        self,
        *,
        request: Any,
        results: list[Any],
        snapshot_manifest: list[dict[str, Any]],
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
        manifest = {"snapshots": list(snapshot_manifest)}
        with self._transaction() as connection:
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
            finally:
                cursor.close()
        return research_run_id

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


__all__ = ["ResearchRunRepository"]
