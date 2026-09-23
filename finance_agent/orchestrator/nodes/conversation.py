"""Conversation 子图的节点函数（casual chat 与 FAQ ReAct）。"""

from __future__ import annotations

from typing import Any, Callable

from finance_agent.orchestrator.graphs.conversation_graph import ConversationState


def make_respond_node(
    retriever: Any,
    model: Callable[[list[dict[str, Any]]], Any],
    *,
    max_steps: int | None = None,
) -> Callable[[ConversationState], dict[str, Any]]:
    """respond 节点工厂；``max_steps`` 为 None 时由 run_conversation 取默认。"""

    def respond(state: ConversationState) -> dict[str, Any]:
        from finance_agent.orchestrator.graphs.conversation_graph import run_conversation

        kwargs: dict[str, Any] = {
            "user_message": str(state.get("user_message", "")),
            "history": str(state.get("history", "") or ""),
        }
        if max_steps is not None:
            kwargs["max_steps"] = max_steps
        return run_conversation(retriever, model, **kwargs)

    return respond
