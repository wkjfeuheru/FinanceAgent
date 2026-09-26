"""账户/持仓专家：system prompt 与只读工具白名单。"""

from __future__ import annotations

from typing import Any

from finance_agent.shared.prompts import load_prompt

ACCOUNT_UNAVAILABLE = "账户数据暂不可用，请稍后在「账户」页面查看，或稍后重试。"
#: system prompt 已外置为包内文本文件（随 git 版本化），此处仅加载。
ACCOUNT_SYSTEM_PROMPT = load_prompt("domains/portfolio/expert/prompts/system.md")


def account_tools() -> list[Any]:
    from finance_agent.domains.portfolio.expert import tools as account_impl

    return [account_impl.get_positions, account_impl.review_allocation]


__all__ = [
    "ACCOUNT_SYSTEM_PROMPT",
    "ACCOUNT_UNAVAILABLE",
    "account_tools",
]
