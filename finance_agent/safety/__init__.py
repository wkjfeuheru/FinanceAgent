"""Agent 合规与守卫工具。"""

from finance_agent.safety.detector import find_sensitive_word
from finance_agent.safety.input_policy import (
    BLOCKED_RESPONSE,
    TRADE_REJECTED_RESPONSE,
    is_educational_question,
    is_trade_request,
    should_block_input,
)
from finance_agent.safety.output_policy import OUTPUT_BLOCKED_RESPONSE, check_sensitive_words

__all__ = [
    "BLOCKED_RESPONSE",
    "OUTPUT_BLOCKED_RESPONSE",
    "TRADE_REJECTED_RESPONSE",
    "check_sensitive_words",
    "find_sensitive_word",
    "is_educational_question",
    "is_trade_request",
    "should_block_input",
]
