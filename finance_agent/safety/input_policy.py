"""用户输入的敏感内容与交易请求入口策略。"""

from __future__ import annotations

from finance_agent.safety.detector import find_sensitive_word, normalise


BLOCKED_RESPONSE = "抱歉，您的输入包含不适宜的内容，暂时无法回答您的问题。"
TRADE_REJECTED_RESPONSE = (
    "投顾助手仅提供投资研究与分析，不代客下单、充值或执行任何交易操作。"
    "如需交易，请在「商品」页面完成申购、在「持仓」页面完成卖出或一键清仓，"
    "充值入口在「账户」页面。交易规则说明可以直接提问，例如申购费率、"
    "赎回到账时间等。"
)

_TRADE_ACTION_WORDS = (
    "买", "卖", "申购", "赎回", "清仓", "平仓", "加仓", "补仓", "减仓",
    "止盈", "止损", "充值", "入金", "转账", "撤单", "下单", "定投",
    "转换", "买入", "卖出", "卖掉", "交易", "一单", "一笔",
)
_TRADE_REQUEST_MARKERS = (
    "帮我", "替我", "给我", "我要", "我想", "请帮我", "麻烦你", "麻烦您",
    "能不能", "可不可以", "可以帮我", "带我", "教我", "来一单", "来一笔",
    "下一单", "帮我来", "现在就", "直接", "立即", "马上", "下单吧",
)
_TRADE_EDUCATIONAL_MARKERS = (
    "什么是", "是什么", "什么意思", "怎么理解", "如何理解", "含义", "指的是",
    "定义", "规则", "流程", "步骤", "手续费", "费率", "多久", "什么时候",
    "时间", "可以吗", "支持吗", "支持不", "行吗", "区别", "有什么",
    "有哪些", "怎么算", "如何计", "交易日", "t+1", "到账", "限额", "门槛",
    "条件", "要求",
)
_EDUCATIONAL_MARKERS = (
    "什么是", "是什么", "是指什么", "是什么意思", "什么意思", "的含义", "含义",
    "指的是", "定义", "概念", "怎么理解", "如何理解", "如何识别", "怎么识别",
    "如何判断", "怎么判断", "如何防范", "怎么防范", "如何避免", "怎么避免",
    "如何应对", "怎么应对", "有哪些", "常见手法", "常见情形", "常见类型",
    "为什么", "为何", "可以吗", "可以么", "是否", "算不算", "违法吗", "违规吗",
    "合法吗", "合规吗", "区别", "有什么不同", "风险", "危害", "后果", "处罚",
    "法律责任", "了解一下", "科普", "介绍一下", "解释一下", "怎么看", "怎么办",
)
_ACTION_MARKERS = (
    "帮我", "替我", "给我", "我要", "我想", "教我", "带我", "怎么才能", "怎样才能",
    "如何操作", "怎么操作", "具体操作", "操作步骤", "帮我做", "帮我操作", "帮我买",
    "帮我卖", "帮忙操作", "推荐买入", "推荐卖出", "买卖点", "什么点位", "带我操作",
)
_QUESTION_TAILS = ("吗？", "吗?", "吗", "呢？", "呢?", "呢", "？", "?")


def is_educational_question(text: str) -> bool:
    """判断是否在询问概念或规则，而非求助执行操作。"""
    content = normalise(text or "")
    if not content:
        return False
    if any(normalise(marker) in content for marker in _ACTION_MARKERS):
        return False
    if any(normalise(marker) in content for marker in _EDUCATIONAL_MARKERS):
        return True
    return content.rstrip().endswith(tuple(normalise(t) for t in _QUESTION_TAILS))


def is_trade_request(text: str) -> bool:
    """动作词、执行措辞同时出现且不在咨询交易规则时拒绝。"""
    content = normalise(text or "")
    if not content:
        return False
    if not any(normalise(word) in content for word in _TRADE_ACTION_WORDS):
        return False
    if any(normalise(marker) in content for marker in _TRADE_EDUCATIONAL_MARKERS):
        return False
    return any(normalise(marker) in content for marker in _TRADE_REQUEST_MARKERS)


def should_block_input(text: str) -> bool:
    """命中敏感词且不是概念/规则提问时拦截。"""
    if find_sensitive_word(text) is None:
        return False
    return not is_educational_question(text)


__all__ = [
    "BLOCKED_RESPONSE", "TRADE_REJECTED_RESPONSE", "is_educational_question",
    "is_trade_request", "should_block_input",
]
