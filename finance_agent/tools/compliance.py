"""合规敏感词检查工具。"""

from __future__ import annotations


SENSITIVE_WORDS: list[str] = [
    "保证收益", "保本", "保本保息", "稳赚不赔", "零风险", "绝对盈利",
    "确保盈利", "承诺收益", "固定收益", "无风险套利",
    "内幕消息", "内幕信息", "操纵市场", "老鼠仓",
    "代客理财", "代客操作", "代客决策", "保证不亏",
    "暴富", "稳赚", "必涨", "必跌", "翻倍",
    "荐股", "推荐买入", "推荐卖出", "明确买卖点",
]


def check_sensitive_words(text: str) -> list[str]:
    """返回回复中命中的敏感词，保持规则表顺序且不重复。"""
    return [word for word in SENSITIVE_WORDS if word in (text or "")]
