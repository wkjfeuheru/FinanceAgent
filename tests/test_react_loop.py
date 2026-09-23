"""四轮受限 ReAct 内核：白名单、schema 校验、循环上限与协议修复。"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel

from finance_agent.orchestrator.runtime.react import ToolSpec, build_chat_model_callable, run_bounded_react


class _Query(BaseModel):
    query: str


class _Answer(BaseModel):
    answer: str


def _tool(payload: _Query) -> _Answer:
    return _Answer(answer=f"echo:{payload.query}")


def _faq_tool() -> ToolSpec:
    return ToolSpec(
        name="faq_search",
        input_model=_Query,
        output_model=_Answer,
        handler=_tool,
    )


def _always_calls_tool() -> Any:
    calls: list[list[dict[str, Any]]] = []

    def model(messages: list[dict[str, Any]]) -> dict[str, Any]:
        calls.append(list(messages))
        return {"action": "tool", "tool_name": "faq_search", "tool_input": {"query": "涨跌停"}}

    model.calls = calls  # type: ignore[attr-defined]
    return model


def _returns_final(text: str = "最终回答") -> Any:
    def model(messages: list[dict[str, Any]]) -> dict[str, Any]:
        del messages
        return {"action": "final", "final_text": text}

    return model


def test_react_stops_after_four_observations():
    outcome = run_bounded_react(
        model=_always_calls_tool(),
        tools={"faq_search": _faq_tool()},
        system_prompt="system",
        user_message="涨跌停怎么算",
        max_steps=4,
    )

    assert outcome.status == "partial"
    assert outcome.metadata["react_steps"] == 4
    assert len(outcome.observations) == 4
    assert [observation.tool for observation in outcome.observations] == ["faq_search"] * 4


def test_react_returns_final_without_calling_tools():
    outcome = run_bounded_react(
        model=_returns_final("你好，我是投顾助手。"),
        tools={"faq_search": _faq_tool()},
        system_prompt="system",
        user_message="你好",
        max_steps=4,
    )

    assert outcome.status == "success"
    assert outcome.final_text == "你好，我是投顾助手。"
    assert outcome.observations == []
    assert outcome.metadata["react_steps"] == 1


def test_react_rejects_tool_outside_whitelist():
    def model(messages: list[dict[str, Any]]) -> dict[str, Any]:
        del messages
        return {"action": "tool", "tool_name": "stock_quote", "tool_input": {"query": "600519"}}

    outcome = run_bounded_react(
        model=model,
        tools={"faq_search": _faq_tool()},
        system_prompt="system",
        user_message="查行情",
        max_steps=4,
        refusal_text="暂时无法执行该操作。",
    )

    assert outcome.status == "failed"
    assert outcome.final_text == "暂时无法执行该操作。"
    assert outcome.metadata["error"] == "tool_not_allowed"
    assert outcome.observations == []


def test_react_repairs_invalid_tool_input_once():
    responses = iter(
        [
            {"action": "tool", "tool_name": "faq_search", "tool_input": {}},
            {"action": "tool", "tool_name": "faq_search", "tool_input": {"query": "涨跌停"}},
            {"action": "final", "final_text": "已根据 FAQ 回答。"},
        ]
    )

    def model(messages: list[dict[str, Any]]) -> dict[str, Any]:
        del messages
        return next(responses)

    outcome = run_bounded_react(
        model=model,
        tools={"faq_search": _faq_tool()},
        system_prompt="system",
        user_message="涨跌停怎么算",
        max_steps=4,
    )

    assert outcome.status == "success"
    assert outcome.final_text == "已根据 FAQ 回答。"
    # 失败的一次不计入 observation，但计入步骤预算。
    assert len(outcome.observations) == 1
    assert outcome.metadata["react_steps"] == 3
    assert outcome.metadata["protocol_repairs"] == 1


def test_react_degrades_when_model_call_raises():
    """模型不可用/接口报错时必须降级为安全文案，而不是让整轮请求崩溃。"""
    def exploding_model(messages: list[dict[str, Any]]) -> Any:
        del messages
        raise RuntimeError("openai.BadRequestError: 400")

    outcome = run_bounded_react(
        model=exploding_model,
        tools={"faq_search": _faq_tool()},
        system_prompt="system",
        user_message="你好",
        max_steps=4,
        refusal_text="暂时无法执行该操作。",
    )

    assert outcome.status == "failed"
    assert outcome.final_text == "暂时无法执行该操作。"
    assert outcome.metadata["error"] == "model_unavailable"


def test_react_system_prompt_mentions_json_for_response_format():
    """OpenAI 兼容接口在 response_format=json_object 时要求提示词含 "json"。"""
    captured: list[list[dict[str, Any]]] = []

    def model(messages: list[dict[str, Any]]) -> Any:
        captured.append(list(messages))
        return {"action": "final", "final_text": "ok"}

    run_bounded_react(
        model=model,
        tools={"faq_search": _faq_tool()},
        system_prompt="你是投顾助手。",
        user_message="你好",
        max_steps=4,
    )

    joined = " ".join(str(m.get("content", "")) for m in captured[0])
    assert "json" in joined.lower()


def test_chat_model_callable_binds_json_object_response_format():
    """适配器必须以 json_object 约束输出，供 _coerce_decision 解析。"""
    seen: dict[str, Any] = {}

    class _Model:
        def bind(self, **kwargs):
            seen.update(kwargs)
            return self

        def invoke(self, messages):
            del messages

            class _R:
                content = '{"action": "final", "final_text": "hi"}'

            return _R()

    call = build_chat_model_callable(_Model(), require_json=True)
    result = call([{"role": "user", "content": "hi"}])

    assert seen.get("response_format") == {"type": "json_object"}
    assert result == '{"action": "final", "final_text": "hi"}'
