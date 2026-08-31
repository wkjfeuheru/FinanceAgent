"""输入守卫与输出合规敏感词检查。

find_sensitive_words 用于 API 入口拦截用户输入；
check_sensitive_words 用于对 Agent 输出进行合规审查。
"""

from __future__ import annotations

import os
import unicodedata
from typing import Any

from langchain.agents.middleware import AgentState, before_agent
from langchain_core.messages import AIMessage
from langgraph.runtime import Runtime


BLOCKED_RESPONSE = "抱歉，您的输入包含不适宜的内容，暂时无法回答您的问题。"
OUTPUT_BLOCKED_RESPONSE = "抱歉，本次回复未能通过合规校验，已为您拦截。请换一种方式提问。"

# 完整的敏感词表，合并了原 compliance.py 的输出检查词表。
# 可通过环境变量 SENSITIVE_WORDS="word1,word2" 覆盖。
_DEFAULT_SENSITIVE_WORDS = (
    # ── 收益承诺类 ──
    "保证收益", "保本", "保本保息", "稳赚不赔", "零风险", "绝对盈利",
    "确保盈利", "承诺收益", "固定收益", "无风险套利", "保证不亏",
    # ── 内幕与操纵类 ──
    "内幕消息", "内幕信息", "操纵市场", "操纵股价", "老鼠仓", "洗钱",
    # ── 代客操作类 ──
    "代客理财", "代客操作", "代客决策",
    # ── 夸大宣传类 ──
    "暴富", "稳赚", "必涨", "必跌", "翻倍",
    # ── 非法荐股类 ──
    "荐股", "非法荐股", "推荐买入", "推荐卖出", "明确买卖点",
)


def _configured_words() -> tuple[str, ...]:
    """返回环境变量配置的敏感词或默认词表。"""
    configured = os.getenv("SENSITIVE_WORDS", "")
    words = configured.split(",") if configured else _DEFAULT_SENSITIVE_WORDS
    return tuple(word.strip() for word in words if word.strip())


def _normalise(text: str) -> str:
    """NFKC 归一化 + 大小写折叠，防止 Unicode 变体绕过。"""
    return unicodedata.normalize("NFKC", text).casefold()


def find_sensitive_word(text: str) -> str | None:
    """检查用户输入是否命中敏感词，返回第一个命中项。"""
    content = _normalise(text)
    for word in _configured_words():
        if _normalise(word) in content:
            return word
    return None


def check_sensitive_words(text: str) -> list[str]:
    """检查 Agent 输出中命中的全部敏感词，保持词表顺序且不重复。"""
    content = _normalise(text or "")
    return [
        word for word in _configured_words()
        if _normalise(word) in content
    ]


def _message_text(message: Any) -> str:
    """从 LangChain 消息对象中提取纯文本。"""
    content = getattr(message, "content", "")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return " ".join(
            str(block.get("text", "")) if isinstance(block, dict) else str(block)
            for block in content
        )
    return str(content)


@before_agent(can_jump_to=["end"])
def content_filter(
    state: AgentState, runtime: Runtime
) -> dict[str, Any] | None:
    """在模型/工具执行前拦截命中敏感词的用户输入。"""
    del runtime
    messages = state.get("messages", [])
    if not messages:
        return None

    last_message = messages[-1]
    if getattr(last_message, "type", "") != "human":
        return None
    if find_sensitive_word(_message_text(last_message)) is None:
        return None

    return {
        "messages": [AIMessage(content=BLOCKED_RESPONSE)],
        "jump_to": "end",
    }
