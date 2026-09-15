"""Conversation ReAct 子图：casual chat 与投资规则 FAQ（设计 §6.3）。

只暴露 ``faq_search`` 一个工具；四轮上限；未命中知识库时必须明确说明
“没有可靠答案”，不得依据低质量片段编造投资规则。
"""

from __future__ import annotations

from typing import Any, Callable

from langgraph.graph import END, START, StateGraph
from pydantic import BaseModel
from typing_extensions import TypedDict

from finance_agent.orchestrator.react import ToolSpec, run_bounded_react

CONVERSATION_REFUSAL = "暂时无法执行该操作。"

_NO_RELIABLE_ANSWER = "FAQ 知识库中没有可靠答案。"

_CONVERSATION_PROMPT = (
    "你是审慎的智能投顾助手，负责金融边界内的闲聊回应与投资规则 FAQ 问答。"
    "需要投资规则知识时调用 faq_search；FAQ 没有可靠答案时如实说明，"
    "不得编造行情数据、推荐具体证券或承诺收益。回答简洁自然。"
)


class FaqQuery(BaseModel):
    query: str


class ConversationState(TypedDict, total=False):
    user_message: str
    customer_id: str
    conversation_id: str
    history: str
    final_response: str
    status: str
    observations: list[dict[str, Any]]
    tool_trace: list[str]
    react_steps: int
    warnings: list[str]
    cited_faq: bool


def _render_faq(result: Any) -> str:
    matches = getattr(result, "matches", None) or []
    if getattr(result, "status", "not_found") != "found" or not matches:
        return _NO_RELIABLE_ANSWER
    return "\n\n".join(match.content for match in matches)


def build_faq_tool(retriever: Any) -> ToolSpec:
    from finance_agent.faq.contracts import FaqSearchResult

    def handler(payload: FaqQuery) -> FaqSearchResult:
        return retriever.search(payload.query)

    return ToolSpec(
        name="faq_search",
        input_model=FaqQuery,
        output_model=FaqSearchResult,
        handler=handler,
        render=_render_faq,
    )


def _cited_faq(outcome: Any) -> bool:
    """回答是否引用了 FAQ 知识库原文（有 found 命中）。

    命中即代表内容来自运维审核过的受信语料，合规出口据此只审计、不改写：
    风险词汇（如“保证收益”“操纵市场”）在解释规则的语境里合法，删词会把
    答案改成病句（例：“什么是操纵市场？”会被删成“什么是？”）。
    """
    for observation in getattr(outcome, "observations", []) or []:
        output = getattr(observation, "output", None) or {}
        if output.get("status") == "found" and output.get("matches"):
            return True
    return False


def run_conversation(
    retriever: Any,
    model: Callable[[list[dict[str, Any]]], Any],
    *,
    user_message: str,
    history: str = "",
    max_steps: int = 4,
) -> dict[str, Any]:
    """运行会话 ReAct 并返回可直接并入图状态的字典。"""
    outcome = run_bounded_react(
        model=model,
        tools={"faq_search": build_faq_tool(retriever)},
        system_prompt=_CONVERSATION_PROMPT,
        user_message=user_message,
        history=history,
        max_steps=max_steps,
        refusal_text=CONVERSATION_REFUSAL,
    )

    warnings: list[str] = []
    if outcome.status == "success":
        final_response = outcome.final_text
    elif outcome.status == "failed":
        final_response = outcome.final_text or CONVERSATION_REFUSAL
        # 失败原因必须可诊断：只暴露安全的原因码与工具名（不含异常原文，
        # 避免把内部细节/连接串等泄露给用户），否则下次同类问题只能看到
        # 笼统的“暂时无法执行该操作”，无从定位（例如依赖缺失）。
        error = str(outcome.metadata.get("error", "unknown"))
        tool = str(outcome.metadata.get("tool", "") or "")
        warnings.append(f"conversation_failed:{error}" + (f":{tool}" if tool else ""))
    else:
        # 达到四轮上限：保留可靠 observation，明确缺失项。
        final_response = outcome.observations[-1].text if outcome.observations else _NO_RELIABLE_ANSWER

    return {
        "final_response": final_response,
        "status": outcome.status,
        "observations": [observation.model_dump() for observation in outcome.observations],
        "tool_trace": outcome.tool_trace,
        "react_steps": outcome.metadata.get("react_steps", 0),
        "warnings": warnings,
        "cited_faq": _cited_faq(outcome),
    }


def build_conversation_graph(
    retriever: Any,
    model: Callable[[list[dict[str, Any]]], Any],
    *,
    max_steps: int = 4,
):
    """编译只含会话节点的 LangGraph 子图。"""

    def respond(state: ConversationState) -> dict[str, Any]:
        return run_conversation(
            retriever,
            model,
            user_message=str(state.get("user_message", "")),
            history=str(state.get("history", "") or ""),
            max_steps=max_steps,
        )

    graph = StateGraph(ConversationState)
    graph.add_node("respond", respond)
    graph.add_edge(START, "respond")
    graph.add_edge("respond", END)
    return graph.compile()
