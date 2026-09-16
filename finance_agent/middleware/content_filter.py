"""输入守卫与输出合规敏感词检查。

should_block_input 用于 API 入口拦截用户输入（会区分“问规则”与“求操作”）；
find_sensitive_word 是纯检测原语；
check_sensitive_words 用于对 Agent 输出进行合规审查。
（编排层在 handle_message 入口直接调用，因此不提供 create_agent 中间件形态。）
"""

from __future__ import annotations

import os
import unicodedata


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

# 概念性/规则性提问标记：用户在“问这条规则是什么”，属于合规的知识咨询。
# 命中敏感词本身不足以拦截——FAQ 语料就以“操纵市场”“内幕信息”“保证收益”
# 等作为条目主题，若一律拦截，用户连这些规则都不能问。
_EDUCATIONAL_MARKERS = (
    "什么是", "是什么", "是指什么", "是什么意思", "什么意思", "的含义", "含义",
    "指的是", "定义", "概念", "怎么理解", "如何理解", "如何识别", "怎么识别",
    "如何判断", "怎么判断", "如何防范", "怎么防范", "如何避免", "怎么避免",
    "如何应对", "怎么应对", "有哪些", "常见手法", "常见情形", "常见类型",
    "为什么", "为何", "可以吗", "可以么", "是否", "算不算",
    "违法吗", "违规吗", "合法吗", "合规吗", "区别", "有什么不同",
    "风险", "危害", "后果", "处罚", "法律责任",
    "了解一下", "科普", "介绍一下", "解释一下", "怎么看", "怎么办",
)

# 求助执行/操作类标记：出现即视为“要做事”而非“问规则”，维持拦截（fail-closed）。
_ACTION_MARKERS = (
    "帮我", "替我", "给我", "我要", "我想", "教我", "带我",
    "怎么才能", "怎样才能", "如何操作", "怎么操作", "具体操作", "操作步骤",
    "帮我做", "帮我操作", "帮我买", "帮我卖", "帮忙操作",
    "推荐买入", "推荐卖出", "买卖点", "什么点位", "带我操作",
)

# 句末疑问语气：整句在问问题（配合“无操作类措辞”使用）。
_QUESTION_TAILS = ("吗？", "吗?", "吗", "呢？", "呢?", "呢", "？", "?")


def _configured_words() -> tuple[str, ...]:
    """返回环境变量配置的敏感词或默认词表。"""
    configured = os.getenv("SENSITIVE_WORDS", "")
    words = configured.split(",") if configured else _DEFAULT_SENSITIVE_WORDS
    return tuple(word.strip() for word in words if word.strip())


def _normalise(text: str) -> str:
    """NFKC 归一化 + 大小写折叠，防止 Unicode 变体绕过。"""
    return unicodedata.normalize("NFKC", text).casefold()


def find_sensitive_word(text: str) -> str | None:
    """纯检测：返回第一个命中的敏感词；不做“该不该拦”的业务判断。"""
    content = _normalise(text)
    for word in _configured_words():
        if _normalise(word) in content:
            return word
    return None


def is_educational_question(text: str) -> bool:
    """整句是否属于“问规则/概念”而非“求操作”。

    判定要求同时满足：含概念性提问标记或以疑问语气结尾；且**不含**任何
    求助执行类措辞（“帮我操纵股价”“怎么才能内幕交易”必须继续拦截）。
    """
    content = _normalise(text or "")
    if not content:
        return False
    if any(_normalise(marker) in content for marker in _ACTION_MARKERS):
        return False
    if any(_normalise(marker) in content for marker in _EDUCATIONAL_MARKERS):
        return True
    return content.rstrip().endswith(tuple(_normalise(t) for t in _QUESTION_TAILS))


def should_block_input(text: str) -> bool:
    """API 入口的输入拦截判定。

    只在“命中敏感词、且不是明显的概念性提问”时拦截。默认 fail-closed：
    无法确认是知识咨询时仍然拦截，避免把可执行违规请求放进来。
    """
    if find_sensitive_word(text) is None:
        return False
    if is_educational_question(text):
        return False
    return True


def check_sensitive_words(text: str) -> list[str]:
    """检查 Agent 输出中命中的全部敏感词，保持词表顺序且不重复。"""
    content = _normalise(text or "")
    return [
        word for word in _configured_words()
        if _normalise(word) in content
    ]

