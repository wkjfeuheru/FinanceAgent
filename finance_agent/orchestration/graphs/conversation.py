"""Conversation 工作流（阶段 6.3）：casual chat 与投资规则 FAQ。

本模块把该工作流的**状态、节点、边与装配**放在一处：``ConversationState``、
``make_respond_node``、``run_conversation`` 与 ``build_conversation_graph`` 同源，
不再像旧结构那样分居 ``nodes/`` 与 ``graphs/`` 两处并靠惰性导入绕圈。

使用与领域专家同一套 LangGraph 原生 ``create_agent`` 工具循环；只暴露
``faq_search`` 一个工具；步数上限由 ``ModelCallLimitMiddleware`` 强制；未命中
知识库时必须明确说明"没有可靠答案"，不得依据低质量片段编造投资规则。
"""

from __future__ import annotations

import json
from typing import Any, Callable

from langgraph.graph import END, START, StateGraph
from typing_extensions import TypedDict

from finance_agent.orchestration.experts.base import _final_text

CONVERSATION_REFUSAL = "暂时无法执行该操作。"

_NO_RELIABLE_ANSWER = "FAQ 知识库中没有可靠答案。"

_CONVERSATION_PROMPT = (
    "你是审慎的智能投顾助手，负责金融边界内的闲聊回应与投资规则 FAQ 问答。"
    "需要投资规则知识时调用 faq_search；FAQ 没有可靠答案时如实说明，"
    "不得编造行情数据、推荐具体证券或承诺收益。"
    "直接用知识库内容作答，不要复述或重复用户的提问，回答简洁自然。"

    # 只写"闲聊 + FAQ"会让系统看起来只有两项能力：股票研究/市场洞察/产品研究/
    # 账户持仓由 Supervisor Graph 按意图路由到各领域子图，不在本节点执行，因此本节点
    # 看不到它们。"你能做什么"必须如实作答，否则用户会以为系统只会聊天，从此不再
    # 提出本可执行的问题（实测回答曾只列出闲聊与 FAQ 两项）。
    # 能力自述面向用户，不暴露内部实现（"系统会自动路由""模块"这类词会让用户
    # 觉得在跟一套机制对话）；只说"直接问就行"，传达同样的含义。
    "用户询问你能做什么时，如实、自然地介绍下面的完整能力，并告诉用户直接提问就行："
    "① 个股基本面/技术面/风险分析与多股比较；"
    "② 大盘指数、市场情绪、资金流向与政策影响的解读（仅市场层面，不涉个股）；"
    "③ 基金等理财产品的基本资料、持仓、业绩、费率与适配度分析；"
    "④ 查看本人账户资金与持仓，并基于持仓给出配置诊断与优化参考"
    "（只读；下单与充值需由用户在页面完成）；"
    "⑤ 投资规则与常识问答，以及金融相关闲聊。"
    "这些都属于研究参考，不构成投资建议。"
)


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


def build_faq_tool(retriever: Any):
    """构造 ``faq_search`` LangChain 工具；命中原文时把回答直接作为工具输出。

    工具输出即受信语料原文，模型据此作答；``found`` 状态与命中数写进返回值，
    供上层判定 ``cited_faq``（合规出口对受信内容只审计、不改写）。
    """
    from langchain_core.tools import tool

    @tool
    def faq_search(query: str) -> str:
        """检索投资规则知识库，返回审核过的规则问答原文。

        Args:
            query: 用户问题的检索词。
        """
        result = retriever.search(query)
        status = getattr(result, "status", "not_found")
        matches = list(getattr(result, "matches", None) or [])
        if status != "found" or not matches:
            return json.dumps(
                {"status": "not_found", "answer": _NO_RELIABLE_ANSWER}, ensure_ascii=False,
            )
        answer = "\n\n".join(
            match.answer.strip() for match in matches if match.answer.strip()
        )
        return json.dumps(
            {"status": "found", "count": len(matches), "answer": answer}, ensure_ascii=False,
        )

    return faq_search


def _faq_payloads(messages: list[Any]) -> list[dict[str, Any]]:
    """所有 ``status=found`` 的 faq_search 返回载荷（按出现顺序）。"""
    from langchain_core.messages import ToolMessage

    payloads: list[dict[str, Any]] = []
    for message in messages or []:
        if not isinstance(message, ToolMessage):
            continue
        content = message.content
        if isinstance(content, list):
            content = "".join(
                part.get("text", "") if isinstance(part, dict) else str(part)
                for part in content
            )
        try:
            payload = json.loads(str(content))
        except (json.JSONDecodeError, TypeError):
            continue
        if isinstance(payload, dict) and payload.get("status") == "found" and payload.get("count"):
            payloads.append(payload)
    return payloads


def _faq_hits(messages: list[Any]) -> bool:
    """回答是否引用了 FAQ 知识库原文（有 found 命中）。

    命中即代表内容来自运维审核过的受信语料，合规出口据此做**逐句**受信判定：
    风险词汇（如"保证收益""操纵市场"）在解释规则的语境里合法，删词会把答案
    改成病句（例："什么是操纵市场？"会被删成"什么是？"）；但只有确实有原文
    支撑的句子才享受豁免，模型自由发挥的部分照常走常规合规。
    """
    return bool(_faq_payloads(messages))


def _faq_sources(messages: list[Any]) -> list[str]:
    """本轮命中的 FAQ 原文（供合规出口做受信判定）。"""
    return [
        str(payload.get("answer") or "").strip()
        for payload in _faq_payloads(messages)
        if str(payload.get("answer") or "").strip()
    ]


def _build_conversation_agent(retriever: Any, model: Any, max_steps: int):
    from langchain.agents import create_agent
    from langchain.agents.middleware import ModelCallLimitMiddleware

    from finance_agent.orchestration.experts.base import build_stop_middleware

    return create_agent(
        model,
        tools=[build_faq_tool(retriever)],
        system_prompt=_CONVERSATION_PROMPT,
        middleware=[
            ModelCallLimitMiddleware(run_limit=max_steps, exit_behavior="end"),
            build_stop_middleware(),
        ],
        name="conversation",
    )


def run_conversation(
    retriever: Any,
    model: Any,
    *,
    user_message: str,
    history: str = "",
    max_steps: int | None = None,
    stop_check: Any = None,
) -> dict[str, Any]:
    """运行会话 ReAct 并返回可直接并入图状态的字典。

    ``model`` 是 chat model（默认由 ``get_supervisor_model()`` 提供）。
    ``max_steps`` 为 None 时取 ``config.ORCHESTRATION_REACT_STEPS``
    （经 ``RunBudgets`` 校验的单一数值源）；显式传入仅供测试收紧。
    ``stop_check`` 是宿主下发的停止/截止查询（``() -> 原因码``）；命中时在下一个
    模型轮次边界退出，并把原因码放进 warnings 供上层归约 run_status。
    """
    from langchain_core.messages import HumanMessage

    from finance_agent.orchestration.experts.base import STOP_CHECK_KEY

    if max_steps is None:
        from finance_agent.infrastructure import settings as config

        max_steps = config.ORCHESTRATION_REACT_STEPS

    agent = _build_conversation_agent(retriever, model, max_steps)

    contents = user_message
    if history:
        contents = f"近期对话：\n{history}\n\n当前消息：{user_message}"
    warnings: list[str] = []
    try:
        result = agent.invoke(
            {"messages": [HumanMessage(content=contents)]},
            config={"configurable": {STOP_CHECK_KEY: stop_check}},
        )
    except Exception as exc:  # noqa: BLE001 - 模型不可用时降级，不让整轮崩溃
        return {
            "final_response": CONVERSATION_REFUSAL,
            "status": "failed",
            "observations": [],
            "tool_trace": [],
            "react_steps": 0,
            "warnings": [f"conversation_failed:model_unavailable:{type(exc).__name__}"],
            "cited_faq": False,
            "cited_sources": [],
        }

    messages = list((result or {}).get("messages") or [])
    final_text, truncated = _final_text(messages, max_steps)
    tool_trace = [
        str(call.get("name"))
        for message in messages
        for call in (getattr(message, "tool_calls", None) or [])
        if isinstance(call, dict) and call.get("name")
    ]
    cited = _faq_hits(messages)
    sources = _faq_sources(messages)

    halt = ""
    if stop_check is not None:
        try:
            halt = str(stop_check() or "")
        except Exception:  # noqa: BLE001 - 停止查询失败按"未停止"处理
            halt = ""

    if halt:
        # 已停止/超时：不补"没有可靠答案"这类会误导的文案，正文留给上层按
        # 停止原因收尾（已完成的部分文本仍然保留）。
        warnings.append(halt)
        status = "partial"
        final_response = final_text
    elif truncated:
        status = "partial"
        final_response = final_text or _NO_RELIABLE_ANSWER
        warnings.append("conversation_step_limit")
    elif final_text:
        status = "success"
        final_response = final_text
    else:
        status = "partial"
        final_response = _NO_RELIABLE_ANSWER

    return {
        "final_response": final_response,
        "status": status,
        "observations": [],
        "tool_trace": tool_trace,
        "react_steps": len(tool_trace),
        "warnings": warnings,
        "cited_faq": cited,
        "cited_sources": sources,
    }


def make_respond_node(
    retriever: Any,
    model: Any,
    *,
    max_steps: int | None = None,
    stop_check: Any = None,
) -> Callable[[ConversationState], dict[str, Any]]:
    """respond 节点工厂；``model`` 为 chat model，``max_steps`` 为 None 时取默认。"""

    def respond(state: ConversationState) -> dict[str, Any]:
        kwargs: dict[str, Any] = {
            "user_message": str(state.get("user_message", "")),
            "history": str(state.get("history", "") or ""),
            "stop_check": stop_check,
        }
        if max_steps is not None:
            kwargs["max_steps"] = max_steps
        return run_conversation(retriever, model, **kwargs)

    return respond


def build_conversation_graph(retriever: Any, model: Any, *, max_steps: int | None = None):
    """编译只含会话节点的 LangGraph 子图（测试用）。"""
    if max_steps is None:
        from finance_agent.infrastructure import settings as config

        max_steps = config.ORCHESTRATION_REACT_STEPS
    agent = _build_conversation_agent(retriever, model, max_steps)

    def respond(state: ConversationState) -> dict[str, Any]:
        message = str(state.get("user_message", ""))
        history = str(state.get("history", "") or "")
        contents = f"近期对话：\n{history}\n\n当前消息：{message}" if history else message
        result = agent.invoke({"messages": [{"role": "user", "content": contents}]})
        messages = list((result or {}).get("messages") or [])
        text, truncated = _final_text(messages, max_steps)
        return {
            "final_response": text or _NO_RELIABLE_ANSWER,
            "status": "partial" if truncated else "success",
            "cited_faq": _faq_hits(messages),
        }

    graph = StateGraph(ConversationState)
    graph.add_node("respond", respond)
    graph.add_edge(START, "respond")
    graph.add_edge("respond", END)
    return graph.compile()


__all__ = [
    "CONVERSATION_REFUSAL",
    "ConversationState",
    "build_conversation_graph",
    "build_faq_tool",
    "make_respond_node",
    "run_conversation",
]
