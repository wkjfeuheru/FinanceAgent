"""市场洞察专家：system prompt 与采集工具白名单。"""

from __future__ import annotations

from typing import Any

from finance_agent.shared.prompts import load_prompt

#: system prompt 已外置为包内文本文件（随 git 版本化），此处仅加载。
MARKET_SYSTEM_PROMPT = load_prompt("domains/market/expert/prompts/system.md")


def market_tools() -> list[Any]:
    from finance_agent.domains.market.expert import tools as market_impl

    return [
        market_impl.get_market_overview,
        market_impl.get_market_sentiment,
        market_impl.get_capital_flow,
        market_impl.get_policy_impact,
    ]


__all__ = [
    "MARKET_SYSTEM_PROMPT",
    "market_tools",
]
