"""股票研究专家：system prompt、筛选守卫与工具白名单。"""

from __future__ import annotations

import re
from typing import Any

from finance_agent.shared import name_matching as name_match
from finance_agent.shared.prompts import load_prompt

STOCK_UNAVAILABLE = "股票研究暂不可用，请稍后重试。"
#: system prompt 已外置为包内文本文件（随 git 版本化），此处仅加载。
STOCK_SYSTEM_PROMPT = load_prompt("domains/research/expert/prompts/system.md")

_A_SHARE_CODE_RE = re.compile(r"(?<!\d)(?:60\d{4}|00\d{4}|30\d{4}|68\d{4}|8\d{5}|4\d{5})(?!\d)")
_SCREENING_SCOPE_RE = re.compile(r"主题|板块|行业|概念|赛道")
_SCREENING_ACTION_RE = re.compile(r"推荐|筛选|选股|有哪些|找|搜索|寻找|列举|候选|龙头")
_MULTI_STOCK_RE = re.compile(r"几只|几支|多只|多支|一些|若干|两只|三只|四只|五只|[2-9]\d*只|[2-9]\d*支")
_STOCK_COLLECTION_RE = re.compile(r"(?:股|股票|个股)")
UNSUPPORTED_SCREENING_MESSAGE = "当前不支持按主题或板块自动筛选股票，请提供具体股票名称或代码进行分析。"


def is_unsupported_stock_screening_request(text: str) -> bool:
    """识别没有明确个股代码的主题或板块筛选请求。"""
    value = str(text or "")
    return bool(
        not _A_SHARE_CODE_RE.search(value)
        and _SCREENING_ACTION_RE.search(value)
        and (
            _SCREENING_SCOPE_RE.search(value)
            or (_MULTI_STOCK_RE.search(value) and _STOCK_COLLECTION_RE.search(value))
        )
    )


def stock_tools() -> list[Any]:
    from finance_agent.domains.research.expert import stockdata as stockdata_impl
    from finance_agent.domains.research.expert import tools as stock_impl

    return [
        stock_impl.resolve_stock_names,
        stockdata_impl.get_stock_quote,
        stockdata_impl.get_stock_history,
        stockdata_impl.get_financial_indicators,
        stockdata_impl.get_stock_basic_info,
        stockdata_impl.get_valuation_indicators,
        stockdata_impl.get_income_statement,
        stockdata_impl.search_candidates,
        stock_impl.compute_technical,
        stock_impl.evaluate_research,
    ]


__all__ = [
    "STOCK_SYSTEM_PROMPT",
    "STOCK_UNAVAILABLE",
    "UNSUPPORTED_SCREENING_MESSAGE",
    "is_unsupported_stock_screening_request",
    "name_match",
    "stock_tools",
]
