"""运行标识工具。"""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID, uuid4


@dataclass(frozen=True)
class RunIdentifiers:
    """一次运行的标识集合，用于从请求到专家结果的可追溯关联。"""

    run_id: UUID
    trace_id: UUID
    conversation_id: str
    message_id: UUID


def generate_identifiers(conversation_id: str) -> RunIdentifiers:
    """为给定会话生成一次运行的 run/trace/message 标识。"""
    return RunIdentifiers(
        run_id=uuid4(),
        trace_id=uuid4(),
        conversation_id=conversation_id,
        message_id=uuid4(),
    )
