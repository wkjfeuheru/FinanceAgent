"""产品研究专家：system prompt 与目录查询工具白名单。"""

from __future__ import annotations

from typing import Any

from finance_agent.shared.prompts import load_prompt

PRODUCT_UNAVAILABLE = "产品研究暂不可用，请稍后重试。"
#: system prompt 已外置为包内文本文件（随 git 版本化），此处仅加载。
PRODUCT_SYSTEM_PROMPT = load_prompt("domains/products/expert/prompts/system.md")


def product_tools() -> list[Any]:
    from finance_agent.domains.products.expert import catalog as catalog_impl

    return [
        catalog_impl.query_product,
        catalog_impl.list_products,
    ]


__all__ = [
    "PRODUCT_SYSTEM_PROMPT",
    "PRODUCT_UNAVAILABLE",
    "product_tools",
]
