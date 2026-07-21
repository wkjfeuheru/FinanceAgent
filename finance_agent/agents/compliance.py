"""合规审查 Agent：敏感词检查与补充信息建议。"""

from __future__ import annotations

from typing import Any, Dict, List

from finance_agent.agents.base import BaseFinanceAgent
from finance_agent.tools.compliance import check_sensitive_words


_QUESTION_MAP = {
    "risk_preference": "请问您的风险偏好是保守、稳健、平衡还是进取？",
    "budget_amount": "请问本次计划投入的资金大约是多少？",
    "budget": "请问本次计划投入的资金大约是多少？",
    "holding_period": "请问计划持有多长时间？",
    "stock_codes": "请提供希望分析的股票名称或六位股票代码。",
    "investment_goal": "请问本次投资的主要目标是稳健增值、获取现金流还是追求成长？",
}


class ComplianceAgent(BaseFinanceAgent):
    """只检查回复敏感词，并判断是否需要向用户补充提问。"""

    agent_name: str = "compliance"

    def _get_tools(self) -> list:
        return []

    def _get_system_prompt(self) -> str:
        return "检查投顾回复中的敏感词，并给出需要向用户补充询问的信息。"

    def review(
        self,
        agent_response: str,
        missing_info: List[str] | None = None,
        **_: Any,
    ) -> Dict[str, Any]:
        """执行确定性的敏感词与补充信息检查，不调用大模型。"""
        sensitive_words = check_sensitive_words(agent_response)
        normalized_missing = list(dict.fromkeys(
            str(item).strip() for item in (missing_info or []) if str(item).strip()
        ))
        questions = [
            _QUESTION_MAP[item] for item in normalized_missing if item in _QUESTION_MAP
        ]
        unknown_fields = [item for item in normalized_missing if item not in _QUESTION_MAP]
        questions.extend(f"请补充以下信息：{field}。" for field in unknown_fields)

        suggestions: list[str] = []
        if sensitive_words:
            suggestions.append("请删除或改写敏感表述，避免承诺收益、绝对化判断或直接买卖指令。")
        if questions:
            suggestions.append("建议在给出个性化配置或明确结论前，先向用户确认缺失信息。")

        result: Dict[str, Any] = {
            "pass": not sensitive_words,
            "sensitive_words_found": sensitive_words,
            "needs_follow_up": bool(questions),
            "missing_info": normalized_missing,
            "follow_up_questions": questions,
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
                    "needs_follow_up": result["needs_follow_up"],
                },
                source=self.agent_name,
            )
        return result

    def handle(
        self,
        message: str = "",
        compressed_context: str = "",
        customer_id: str = "",
        chat_history: List[Dict[str, str]] | None = None,
        thread_id: str | None = None,
        **_: Any,
    ) -> str:
        return ""
