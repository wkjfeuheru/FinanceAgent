"""多 Agent 数据流契约层。

定义请求、分派、事实快照、专家结果和响应等数据包，以及运行标识
工具，作为 Agent 之间显式传递的强类型、可 JSON Schema 校验的边界。
"""

from finance_agent.contracts.schema import (
    DispatchPlan,
    ExpertResult,
    ExpertStatus,
    FactSnapshot,
    IntentKind,
    RequestEnvelope,
    ResponseEnvelope,
    RunIdentifiers,
    RunStatus,
    Task,
    TaskKind,
    TaskStatus,
    generate_identifiers,
)

__all__ = [
    "DispatchPlan",
    "ExpertResult",
    "ExpertStatus",
    "IntentKind",
    "FactSnapshot",
    "RequestEnvelope",
    "ResponseEnvelope",
    "RunIdentifiers",
    "RunStatus",
    "Task",
    "TaskKind",
    "TaskStatus",
    "generate_identifiers",
]
