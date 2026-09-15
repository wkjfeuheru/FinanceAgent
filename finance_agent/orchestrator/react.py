"""四轮受限 ReAct 内核（设计 §9）。

LLM 每轮只输出一个 ``ReactDecision``（``tool`` 或 ``final``）。工具选择必须命中
调用方提供的白名单，工具输入/输出必须先通过 Pydantic 契约校验才会进入
observation。预算由调用方注入，只递减，LLM 无权修改。
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Callable, Literal, Mapping, Sequence

from pydantic import BaseModel, Field, ValidationError

from finance_agent.orchestrator.contracts import ReactDecision


class ReactProtocolError(RuntimeError):
    """模型输出无法解析为 ReactDecision。"""


@dataclass(frozen=True)
class ToolSpec:
    """一个领域工具的输入/输出契约与处理器。"""

    name: str
    input_model: type[BaseModel]
    output_model: type[BaseModel]
    handler: Callable[[BaseModel], Any]
    render: Callable[[BaseModel], str] | None = None


class Observation(BaseModel):
    """工具执行后进入 transcript 的一条只读记录。"""

    tool: str
    input: dict[str, Any] = Field(default_factory=dict)
    output: dict[str, Any] = Field(default_factory=dict)
    text: str = ""


class ReactOutcome(BaseModel):
    """受限 ReAct 的统一终态。"""

    status: Literal["success", "partial", "failed"]
    final_text: str = ""
    observations: list[Observation] = Field(default_factory=list)
    tool_trace: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


def _coerce_decision(raw: Any) -> ReactDecision:
    if isinstance(raw, ReactDecision):
        return raw
    if isinstance(raw, bytes):
        raw = raw.decode("utf-8")
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ReactProtocolError("model output is not valid JSON") from exc
    if isinstance(raw, BaseModel):
        raw = raw.model_dump()
    try:
        return ReactDecision.model_validate(raw)
    except ValidationError as exc:
        raise ReactProtocolError("model output does not match ReactDecision") from exc


def _render_output(spec: ToolSpec, output: BaseModel) -> str:
    if spec.render is not None:
        return spec.render(output)
    return json.dumps(output.model_dump(), ensure_ascii=False)


def _to_langchain_messages(messages: Sequence[dict[str, Any]]) -> list[Any]:
    from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

    converted: list[Any] = []
    for message in messages:
        role = str(message.get("role", "human"))
        content = str(message.get("content", ""))
        if role == "system":
            converted.append(SystemMessage(content=content))
        elif role == "assistant":
            converted.append(AIMessage(content=content))
        else:
            # observation 也以人类消息回灌，避免模型把它当作自身输出。
            converted.append(HumanMessage(content=content))
    return converted


def build_chat_model_callable(chat_model: Any, *, require_json: bool = True) -> Callable[[list[dict[str, Any]]], Any]:
    """把 LangChain chat model 适配为 ``run_bounded_react`` 需要的 messages→decision 函数。"""

    def call(messages: list[dict[str, Any]]) -> Any:
        bound = chat_model
        if require_json:
            bind = getattr(chat_model, "bind", None)
            if callable(bind):
                bound = bind(response_format={"type": "json_object"})
        response = bound.invoke(_to_langchain_messages(messages))
        content = getattr(response, "content", response)
        if isinstance(content, list):
            content = "".join(
                part.get("text", "") if isinstance(part, dict) else str(part) for part in content
            )
        return content

    return call


def run_bounded_react(
    *,
    model: Callable[[list[dict[str, Any]]], Any],
    tools: Mapping[str, ToolSpec],
    system_prompt: str,
    user_message: str,
    history: str = "",
    max_steps: int = 4,
    refusal_text: str = "暂时无法执行该操作。",
) -> ReactOutcome:
    """在 ``max_steps`` 次模型调用内运行受限 ReAct 循环。"""
    if max_steps < 1:
        raise ValueError("max_steps must be positive")

    messages: list[dict[str, Any]] = [{"role": "system", "content": system_prompt}]
    if history:
        messages.append({"role": "system", "content": f"近期对话：\n{history}"})
    messages.append({"role": "user", "content": user_message})
    messages.append(
        {
            "role": "system",
            "content": (
                # 显式要求 JSON 输出：OpenAI 兼容接口在 response_format=json_object 时
                # 要求提示词中出现 "json" 字样，否则直接 400。
                "你每一轮都必须只输出一个 JSON 对象，不要输出其它文字或 Markdown 代码块。"
                "只允许调用这些工具：" + ", ".join(sorted(tools)) + "。"
                "需要工具时输出 {\"action\":\"tool\",\"tool_name\":...,\"tool_input\":{...}}；"
                "可以作答时输出 {\"action\":\"final\",\"final_text\":...}。"
            ),
        }
    )

    observations: list[Observation] = []
    tool_trace: list[str] = []
    repairs = 0
    steps = 0

    while steps < max_steps:
        steps += 1
        try:
            raw_decision = model(list(messages))
        except Exception as exc:  # noqa: BLE001 - LLM 不可用时降级，不让整轮请求崩溃
            return ReactOutcome(
                status="failed",
                final_text=refusal_text,
                observations=observations,
                tool_trace=tool_trace,
                metadata={
                    "react_steps": steps,
                    "error": "model_unavailable",
                    "detail": type(exc).__name__,
                },
            )
        try:
            decision = _coerce_decision(raw_decision)
        except ReactProtocolError as exc:
            return ReactOutcome(
                status="failed",
                final_text="暂时无法理解该请求，请稍后重试。",
                observations=observations,
                tool_trace=tool_trace,
                metadata={"react_steps": steps, "error": "protocol_error", "detail": str(exc)},
            )

        if decision.action == "final":
            return ReactOutcome(
                status="success",
                final_text=decision.final_text,
                observations=observations,
                tool_trace=tool_trace,
                metadata={"react_steps": steps, "protocol_repairs": repairs},
            )

        spec = tools.get(decision.tool_name)
        if spec is None:
            return ReactOutcome(
                status="failed",
                final_text=refusal_text,
                observations=observations,
                tool_trace=tool_trace,
                metadata={
                    "react_steps": steps,
                    "error": "tool_not_allowed",
                    "tool": decision.tool_name,
                },
            )

        try:
            tool_input = spec.input_model.model_validate(decision.tool_input)
        except ValidationError as exc:
            if repairs >= 1:
                return ReactOutcome(
                    status="failed",
                    final_text=refusal_text,
                    observations=observations,
                    tool_trace=tool_trace,
                    metadata={"react_steps": steps, "error": "tool_input_invalid"},
                )
            repairs += 1
            messages.append(
                {
                    "role": "observation",
                    "content": f"工具 {spec.name} 输入字段错误：{exc.errors()}。请修正后重试一次。",
                }
            )
            continue

        try:
            raw_output = spec.handler(tool_input)
        except Exception as exc:  # noqa: BLE001 - 工具失败降级，不让整轮请求崩溃
            return ReactOutcome(
                status="failed",
                final_text=refusal_text,
                observations=observations,
                tool_trace=tool_trace + [spec.name],
                metadata={
                    "react_steps": steps,
                    "error": "tool_failed",
                    "tool": spec.name,
                    "detail": type(exc).__name__,
                },
            )
        try:
            tool_output = spec.output_model.model_validate(raw_output)
        except ValidationError as exc:
            return ReactOutcome(
                status="failed",
                final_text=refusal_text,
                observations=observations,
                tool_trace=tool_trace,
                metadata={"react_steps": steps, "error": "tool_output_invalid", "detail": str(exc)},
            )

        observation = Observation(
            tool=spec.name,
            input=tool_input.model_dump(),
            output=tool_output.model_dump(),
            text=_render_output(spec, tool_output),
        )
        observations.append(observation)
        tool_trace.append(spec.name)
        messages.append({"role": "observation", "content": observation.text})

    return ReactOutcome(
        status="partial",
        final_text="",
        observations=observations,
        tool_trace=tool_trace,
        metadata={
            "react_steps": steps,
            "protocol_repairs": repairs,
            "degraded": "react_step_limit",
        },
    )
