"""Agent 输出合规策略。"""

from finance_agent.safety.detector import find_sensitive_words


OUTPUT_BLOCKED_RESPONSE = "抱歉，本次回复未能通过合规校验，已为您拦截。请换一种方式提问。"


def check_sensitive_words(text: str) -> list[str]:
    """检查 Agent 输出中的全部敏感词。"""
    return find_sensitive_words(text or "")


__all__ = ["OUTPUT_BLOCKED_RESPONSE", "check_sensitive_words"]
