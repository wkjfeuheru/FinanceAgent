"""唯一的敏感词表、文本归一化和敏感词检测实现。"""

from __future__ import annotations

import os
import unicodedata


_DEFAULT_SENSITIVE_WORDS = (
    "保证收益", "保本", "保本保息", "稳赚不赔", "零风险", "绝对盈利",
    "确保盈利", "承诺收益", "固定收益", "无风险套利", "保证不亏",
    "内幕消息", "内幕信息", "内幕交易", "操纵市场", "操纵股价",
    "坐庄", "对倒", "虚假申报", "蛊惑交易", "抢帽子", "拉抬打压",
    "老鼠仓", "洗钱", "非法集资", "场外配资", "庞氏骗局", "资金盘",
    "代客理财", "代客操作", "代客决策", "暴富", "稳赚", "必涨", "必跌",
    "翻倍", "荐股", "非法荐股", "推荐买入", "推荐卖出", "明确买卖点",
)


def _configured_words() -> tuple[str, ...]:
    """返回环境变量配置的敏感词或默认词表。"""
    configured = os.getenv("SENSITIVE_WORDS", "")
    words = configured.split(",") if configured else _DEFAULT_SENSITIVE_WORDS
    return tuple(word.strip() for word in words if word.strip())


def normalise(text: str) -> str:
    """NFKC 归一化 + 大小写折叠，防止 Unicode 变体绕过。"""
    return unicodedata.normalize("NFKC", text).casefold()


def find_sensitive_word(text: str) -> str | None:
    """返回第一个命中的敏感词；不判断是否应拦截。"""
    content = normalise(text or "")
    for word in _configured_words():
        if normalise(word) in content:
            return word
    return None


def find_sensitive_words(text: str) -> list[str]:
    """返回全部命中词，保持词表顺序且不重复。"""
    content = normalise(text or "")
    return [word for word in _configured_words() if normalise(word) in content]


__all__ = ["find_sensitive_word", "find_sensitive_words", "normalise"]
