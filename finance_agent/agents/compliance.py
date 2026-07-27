"""合规审查 Agent：敏感词与投资表述检查。"""

from __future__ import annotations

from typing import Any, Dict, List

from finance_agent.agents.base import BaseFinanceAgent
from finance_agent.tools.compliance import check_sensitive_words


class ComplianceAgent(BaseFinanceAgent):
    """只检查回复中的敏感词和投资表述。"""

    agent_name: str = "compliance"

    def _get_tools(self) -> list:
        return []

    def _get_system_prompt(self) -> str:
        return "检查投顾回复中的敏感词，并给出需要向用户补充询问的信息。"

    def review(
        self,
        agent_response: str,
        **_: Any,
    ) -> Dict[str, Any]:
        """执行确定性的敏感词检查，不调用大模型。"""
        sensitive_words = check_sensitive_words(agent_response)

        suggestions: list[str] = []
        if sensitive_words:
            suggestions.append("请删除或改写敏感表述，避免承诺收益、绝对化判断或直接买卖指令。")

        result: Dict[str, Any] = {
            "pass": not sensitive_words,
            "sensitive_words_found": sensitive_words,
            "suggestions": suggestions,
            "reason": (
                f"回复包含敏感词：{', '.join(sensitive_words)}"
                if sensitive_words
                else "未发现敏感词"
            ),
        }

        if self.shared_memory:
            self.shared_memory.publish_fact(
                f"compliance_review_{hash(agent_response) % 10000}",
                {
                    "pass": result["pass"],
                    "sensitive_count": len(sensitive_words),
                },
                source=self.agent_name,
            )
        return result

    def handle(
        self,
        message: str = "",
        customer_id: str = "",
        chat_history: List[Dict[str, str]] | None = None,
        thread_id: str | None = None,
        **_: Any,
    ) -> str:
        return ""
