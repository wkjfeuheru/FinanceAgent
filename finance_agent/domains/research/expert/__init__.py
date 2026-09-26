"""股票研究专家：system prompt 与工具白名单。"""

from __future__ import annotations

from typing import Any

from finance_agent.shared import name_matching as name_match
from finance_agent.shared.prompts import load_prompt

STOCK_UNAVAILABLE = "股票研究暂不可用，请稍后重试。"
#: system prompt 已外置为包内文本文件（随 git 版本化），此处仅加载。
STOCK_SYSTEM_PROMPT = load_prompt("domains/research/expert/prompts/system.md")


def stock_tools() -> list[Any]:
    from finance_agent.domains.research.expert import screening as screening_impl
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
        # 主题/板块筛选：先在板块表里定位板块，再对成分做确定性评分排序。
        # 此前这两个位置是"按主题/板块自动筛选"的固定拒绝（下游守卫在模型调用前
        # 短路），现已换成真实取数 + 规则排序，并把清单口径与免责写进返回值。
        screening_impl.list_boards,
        screening_impl.screen_board_candidates,
        stock_impl.compute_technical,
        stock_impl.evaluate_research,
    ]


__all__ = [
    "STOCK_SYSTEM_PROMPT",
    "STOCK_UNAVAILABLE",
    "name_match",
    "stock_tools",
]
