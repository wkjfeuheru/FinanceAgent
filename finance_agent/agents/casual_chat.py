"""闲聊最终文本生成（纯 helper，不拥有图或 checkpoint）。

V2 路径下会话由 Conversation ReAct 子图承载；本模块保留可复用的
“受约束闲聊叙述”函数，以及兼容旧编排路径的薄 Agent 包装（无图、无 checkpoint）。
"""

from __future__ import annotations

from typing import Any, Dict

from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate

from finance_agent.agents.base import ProceduralAgent
from finance_agent.config import get_supervisor_model

_FINANCE_GUIDANCE = "你好,我是你的智能投顾助手,主要协助处理投资理财、证券行情、选股研究和资产配置问题。你可以从这些方面继续问我。"


def generate_casual_response(query: str, context: str = "", *, finance_related: bool = True) -> str:
    """生成金融边界内的闲聊回复；失败时返回固定安全文案。"""
    if not finance_related:
        return _FINANCE_GUIDANCE

    prompt = ChatPromptTemplate.from_messages([
        (
            "system",
            "你是有同理心且审慎的理财交流助手。只回应给定的闲聊子请求，"
            "可以讨论投资情绪、经验、心态和一般金融知识；不要查询或编造行情数据，"
            "不要推荐具体证券，不要生成个人资产配置方案。回答简洁自然。",
        ),
        ("human", "近期对话：\n{context}\n\n闲聊子请求：{query}"),
    ])
    try:
        return (prompt | get_supervisor_model() | StrOutputParser()).invoke({
            "context": context or "无上下文",
            "query": query,
        }).strip()
    except Exception:
        return "暂时无法回应这部分交流内容，请稍后重试。"


class CasualChatAgent(ProceduralAgent):
    """兼容旧编排路径的闲聊包装；本身不拥有图或 checkpoint。"""

    agent_name = "casual_chat"

    def invoke(self, state: Dict[str, Any]) -> Dict[str, Any]:
        query = str(state.get("requirement", "")).strip() or str(state.get("user_message", "")).strip()
        response = generate_casual_response(
            query,
            str(state.get("memory_context", "")),
            finance_related=bool(state.get("finance_related", True)),
        )
        intent_results = state.get("intent_results", {}) or {}
        intent_results["casual_chat"] = {"status": "success", "content": response}
        state["intent_results"] = intent_results
        state["agent_response"] = response
        return state

