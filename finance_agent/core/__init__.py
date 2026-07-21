"""核心编排模块：多 Agent 流水线、记忆系统、共享状态。"""

from finance_agent.core.memory import AgentMemoryContext, RedisMemoryStore, UserProfileCard
from finance_agent.core.shared_state import SharedWorkingMemory


def __getattr__(name: str):
    """Load the orchestrator lazily to avoid agent/core circular imports."""
    if name == "AdvisorSystem":
        from finance_agent.core.orchestrator import AdvisorSystem

        return AdvisorSystem
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

__all__ = [
    "AdvisorSystem",
    "AgentMemoryContext",
    "RedisMemoryStore",
    "UserProfileCard",
    "SharedWorkingMemory",
]
