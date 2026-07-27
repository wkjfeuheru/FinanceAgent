"""Deterministic input guardrail for user supplied text."""

from __future__ import annotations

import os
import unicodedata
from typing import Any

from langchain.agents.middleware import AgentState, before_agent
from langchain_core.messages import AIMessage
from langgraph.runtime import Runtime


BLOCKED_RESPONSE = "抱歉，您的输入包含不适宜的内容，暂时无法回答您的问题。"

# The list can be replaced without a code change, for example:
# SENSITIVE_WORDS="hack,exploit,malware,自定义敏感词"
_DEFAULT_SENSITIVE_WORDS = (
    "操纵股价",
    "内幕消息",
    "保证收益",
    "稳赚不赔",
    "代客理财",
    "非法荐股",
    "老鼠仓",
    "洗钱",
)


def _configured_words() -> tuple[str, ...]:
    configured = os.getenv("SENSITIVE_WORDS", "")
    words = configured.split(",") if configured else _DEFAULT_SENSITIVE_WORDS
    return tuple(word.strip() for word in words if word.strip())


def _normalise(text: str) -> str:
    return unicodedata.normalize("NFKC", text).casefold()


def find_sensitive_word(text: str) -> str | None:
    """Return the first matching configured word, without exposing it to users."""
    content = _normalise(text)
    for word in _configured_words():
        if _normalise(word) in content:
            return word
    return None


def _message_text(message: Any) -> str:
    content = getattr(message, "content", "")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return " ".join(
            str(block.get("text", "")) if isinstance(block, dict) else str(block)
            for block in content
        )
    return str(content)


@before_agent(can_jump_to=["end"])
def content_filter(
    state: AgentState, runtime: Runtime
) -> dict[str, Any] | None:
    """Stop an agent before model/tool execution when the latest user input is blocked."""
    del runtime
    messages = state.get("messages", [])
    if not messages:
        return None

    last_message = messages[-1]
    if getattr(last_message, "type", "") != "human":
        return None
    if find_sensitive_word(_message_text(last_message)) is None:
        return None

    return {
        "messages": [AIMessage(content=BLOCKED_RESPONSE)],
        "jump_to": "end",
    }
