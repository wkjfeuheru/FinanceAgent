"""编排层：LangGraph Supervisor Graph、领域子图、记忆系统与工具调用。"""

from finance_agent.orchestrator.memory import AgentMemoryContext, RedisMemoryStore, UserProfileCard


def __getattr__(name: str):
    """Load the orchestrator lazily to avoid import cycles."""
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
