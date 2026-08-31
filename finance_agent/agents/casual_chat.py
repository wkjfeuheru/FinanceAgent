"""闲聊专家，负责金融边界内的自然交流。"""

from __future__ import annotations

from typing import Any, Dict

from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate

from finance_agent.agents.base import ProceduralAgent
from finance_agent.config import get_supervisor_model


_FINANCE_GUIDANCE = "我主要协助处理投资理财、证券行情、选股研究和资产配置问题。你可以从这些方面继续问我。"


class CasualChatAgent(ProceduralAgent):
    """闲聊专家，不调用金融数据工具。"""

    agent_name = "casual_chat"

    # 生成金融相关闲聊回复。
    def _generate_response(self, query: str, context: str) -> str:
        prompt = ChatPromptTemplate.from_messages([
            (
                "system",
                "你是有同理心且审慎的理财交流助手。只回应给定的闲聊子请求，"
                "可以讨论投资情绪、经验、心态和一般金融知识；不要查询或编造行情数据，"
                "不要推荐具体证券，不要生成个人资产配置方案。回答简洁自然。",
            ),
            ("human", "近期对话：\n{context}\n\n闲聊子请求：{query}"),
        ])
        return (prompt | get_supervisor_model() | StrOutputParser()).invoke({
            "context": context or "无上下文",
            "query": query,
        }).strip()

    # 处理总管传入的闲聊状态，并写回意图结果。
    def invoke(self, state: Dict[str, Any]) -> Dict[str, Any]:
        query = str(state.get("requirement", "")).strip() or str(
            state.get("user_message", "")
        ).strip()
        if not state.get("finance_related", True):
            response = _FINANCE_GUIDANCE
        else:
            try:
                response = self._generate_response(
                    query,
                    str(state.get("memory_context", "")),
                )
            except Exception:
                response = "暂时无法回应这部分交流内容，请稍后重试。"

        intent_results = state.get("intent_results", {}) or {}
        intent_results["casual_chat"] = {
            "status": "success",
            "content": response,
        }
        state["intent_results"] = intent_results
        state["agent_response"] = response
        return state
