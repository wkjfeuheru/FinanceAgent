"""编排层：多 Agent 流水线、记忆系统与工具调用。"""

from finance_agent.orchestrator.memory import AgentMemoryContext, RedisMemoryStore, UserProfileCard


def __getattr__(name: str):
    """Load the orchestrator lazily to avoid agent/core circular imports."""
    if name == "AdvisorSystem":
        from finance_agent.orchestrator.orchestrator import AdvisorSystem

        return AdvisorSystem
    raise AttributeError(f"module {name!r} has no attribute {name!r}")

__all__ = [
    "AdvisorSystem",
    "AgentMemoryContext",
    "RedisMemoryStore",
    "UserProfileCard",
]
