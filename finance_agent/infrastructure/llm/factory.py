"""JSON 结构化输出的 chat model 适配器。

把 LangChain chat model 包装为 ``messages → content`` 的函数，并以
``response_format={"type": "json_object"}`` 约束输出。供 **任务改写器**与
**跨领域 Planner** 这类"要求模型返回一段 JSON、由代码解析"的场景使用——
它们不是工具循环，因此不需要 agent；领域专家与会话 FAQ 则一律走
``create_agent`` 原生工具循环。
"""

from __future__ import annotations

import json
from typing import Any, Callable, Sequence

from langchain.chat_models import init_chat_model

from finance_agent.infrastructure.settings import (
    DEEPSEEK_API_KEY,
    EXPERT_STEPS_ACCOUNT,
    EXPERT_STEPS_MARKET,
    EXPERT_STEPS_PRODUCT,
    EXPERT_STEPS_STOCK,
    INTENT_MODEL_API_KEY,
    INTENT_MODEL_BASE_URL,
    INTENT_MODEL_MAX_RETRIES,
    INTENT_MODEL_MAX_TOKENS,
    INTENT_MODEL_TIMEOUT,
    INTENT_MODEL,
    LLM_MAX_RETRIES,
    LLM_REQUEST_TIMEOUT,
    PRODUCT_ANALYSIS_TEMPERATURE,
    SYNTHESIS_TEMPERATURE,
)


AGENT_TEMPERATURES = {
    "supervisor": 0.2,
    "slot_extraction": 0.1,
    "fundamental": 0.3,
    "stock_analysis": 0.3,
    "market_insight": 0.2,
    "product_analysis": PRODUCT_ANALYSIS_TEMPERATURE,
    "expert": 0.2,
    "synthesis": SYNTHESIS_TEMPERATURE,
}

EXPERT_STEP_BUDGETS: dict[str, int] = {
    "stock_research": EXPERT_STEPS_STOCK,
    "market_insight": EXPERT_STEPS_MARKET,
    "product_research": EXPERT_STEPS_PRODUCT,
    "account_portfolio": EXPERT_STEPS_ACCOUNT,
}


def get_expert_model(*, timeout: float | None = None, max_retries: int | None = None):
    """领域 ReAct 专家的模型：工具选择与多步推理对模型能力敏感，统一用 pro。"""
    return get_model_for_agent("expert", timeout=timeout, max_retries=max_retries)


def get_model_for_agent(
    agent_name: str,
    *,
    timeout: float | None = None,
    max_retries: int | None = None,
):
    """根据 Agent 名称获取对应温度的模型实例。"""
    temperature = AGENT_TEMPERATURES.get(agent_name, 0.3)
    return init_chat_model(
        "deepseek:deepseek-v4-pro",
        api_key=DEEPSEEK_API_KEY,
        temperature=temperature,
        timeout=timeout if timeout is not None else LLM_REQUEST_TIMEOUT,
        max_retries=max_retries if max_retries is not None else LLM_MAX_RETRIES,
    )


def get_supervisor_model():
    """返回监督者用于工具决策与闲聊生成的轻量模型。"""
    return init_chat_model(
        "deepseek:deepseek-v4-flash",
        api_key=DEEPSEEK_API_KEY,
        temperature=0,
        timeout=LLM_REQUEST_TIMEOUT,
        max_retries=LLM_MAX_RETRIES,
    )


def get_intent_model(*, max_tokens: int | None = None):
    """构造意图分类/跨领域规划模型；未配置密钥时返回 None。"""
    if not INTENT_MODEL_API_KEY:
        return None
    base_url = INTENT_MODEL_BASE_URL
    for suffix in ("/chat/completions", "/completions", "/chat"):
        if base_url.endswith(suffix):
            base_url = base_url[: -len(suffix)]
            break
    return init_chat_model(
        f"openai:{INTENT_MODEL}",
        api_key=INTENT_MODEL_API_KEY,
        base_url=base_url,
        temperature=0,
        timeout=INTENT_MODEL_TIMEOUT,
        max_retries=INTENT_MODEL_MAX_RETRIES,
        max_tokens=max_tokens or INTENT_MODEL_MAX_TOKENS,
    )


def to_langchain_messages(messages: Sequence[dict[str, Any]]) -> list[Any]:
    """把 ``[{role, content}]`` 转为 LangChain 消息对象。"""
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
            converted.append(HumanMessage(content=content))
    return converted


def build_chat_model_callable(
    chat_model: Any, *, require_json: bool = True,
) -> Callable[[list[dict[str, Any]]], str]:
    """把 chat model 适配为 ``messages → 文本`` 的调用函数。

    ``require_json`` 为真时绑定 ``response_format=json_object``：OpenAI 兼容接口
    在该模式下要求提示词中出现 "json" 字样，否则直接 400——调用方的提示词必须
    显式提到 JSON。
    """

    def call(messages: list[dict[str, Any]]) -> str:
        bound = chat_model
        if require_json:
            bind = getattr(chat_model, "bind", None)
            if callable(bind):
                bound = bind(response_format={"type": "json_object"})
        response = bound.invoke(to_langchain_messages(messages))
        content = getattr(response, "content", response)
        if isinstance(content, list):
            content = "".join(
                part.get("text", "") if isinstance(part, dict) else str(part)
                for part in content
            )
        elif isinstance(content, dict):
            content = json.dumps(content, ensure_ascii=False)
        return str(content or "")

    return call


__all__ = [
    "AGENT_TEMPERATURES",
    "EXPERT_STEP_BUDGETS",
    "build_chat_model_callable",
    "get_expert_model",
    "get_intent_model",
    "get_model_for_agent",
    "get_supervisor_model",
    "to_langchain_messages",
]
