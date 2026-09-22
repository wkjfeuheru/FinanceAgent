"""运行标识工具与运行状态机。"""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID, uuid4

from finance_agent.contracts.schema.enums import RunStatus


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


def propagate_identifiers(identifiers: RunIdentifiers) -> dict[str, str]:
    """将运行标识展开为可注入契约对象的字典（标识以字符串形式传播）。"""
    return {
        "run_id": str(identifiers.run_id),
        "trace_id": str(identifiers.trace_id),
        "conversation_id": identifiers.conversation_id,
        "message_id": str(identifiers.message_id),
    }


_TERMINAL_STATUSES = frozenset({
    RunStatus.COMPLETED,
    RunStatus.FAILED,
    RunStatus.CANCELLED,
    RunStatus.PARTIAL,
})


def transition_run_status(current: RunStatus, target: RunStatus) -> RunStatus:
    """运行状态机：进入终态后只能重复写入同一终态，否则抛 ValueError。"""
    if current in _TERMINAL_STATUSES and target != current:
        raise ValueError(
            f"终态运行 {current.value!r} 不能转换为 {target.value!r}"
        )
    return target
