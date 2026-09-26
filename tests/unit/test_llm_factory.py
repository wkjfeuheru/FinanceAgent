"""Tests for provider model response content adaptation."""

from __future__ import annotations

import json
from types import SimpleNamespace

from finance_agent.infrastructure.llm.factory import build_chat_model_callable


def test_structured_content_is_encoded_as_json() -> None:
    class Model:
        def invoke(self, messages):
            return SimpleNamespace(content={"plan": ["research", "summarize"]})

    result = build_chat_model_callable(Model(), require_json=False)([])

    assert json.loads(result) == {"plan": ["research", "summarize"]}
