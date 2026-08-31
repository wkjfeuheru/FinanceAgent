"""多 Agent 数据流契约数据定义。

定义请求、分派、事实快照、专家结果与响应等 Pydantic 数据包，
作为 Agent 之间显式传递的强类型边界，可生成 JSON Schema 并拒绝未知字段。
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from finance_agent.contracts.schema.enums import ExpertStatus, TaskKind


def _utcnow() -> datetime:
    """返回 UTC 当前时间，作为请求时间戳默认值。"""
    return datetime.now(timezone.utc)


class _ContractModel(BaseModel):
    """所有契约对象禁止未知字段，使拼写错误与未声明字段在边界被拒绝。"""

    model_config = ConfigDict(extra="forbid")


class RequestEnvelope(_ContractModel):
    """一次请求的输入包，携带完整运行/会话/消息标识。"""

    run_id: UUID
    trace_id: UUID
    user_id: UUID
    customer_id: str
    conversation_id: str
    message_id: UUID
    message: str
    requested_at: datetime = Field(default_factory=_utcnow)


class Task(_ContractModel):
    """总管分派的单个任务。"""

    task_id: str
    kind: TaskKind


class DispatchPlan(_ContractModel):
    """总管分派计划，包含一个或多个任务。"""

    tasks: list[Task] = Field(default_factory=list)


class FactSnapshot(_ContractModel):
    """带来源、获取时间与有效期的运行事实快照。"""

    fact_id: str
    domain: str
    source: str
    fetched_at: datetime
    valid_until: datetime | None = None
    payload: dict[str, Any] = Field(default_factory=dict)


class PreparedContext(_ContractModel):
    """数据准备阶段的上下文，包含本轮事实快照。"""

    facts: list[FactSnapshot] = Field(default_factory=list)


class ExpertResult(_ContractModel):
    """专家结果包；未知或无效结构化输出不得进入最终合成。"""

    expert_name: str
    status: ExpertStatus
    schema_version: str = "1.0"
    summary: str
    result_data: dict[str, Any] = Field(default_factory=dict)
    fact_ids: list[str] = Field(default_factory=list)
    degradation_reason: str | None = None


class ResponseEnvelope(_ContractModel):
    """最终响应包，包含合成文本与各专家结果。"""

    run_id: UUID
    trace_id: UUID
    conversation_id: str
    message_id: UUID
    response: str
    results: list[ExpertResult] = Field(default_factory=list)
