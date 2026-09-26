"""产品库目录查询工具：只返回结构化字段，不生成评估报告。"""

from __future__ import annotations

import json
from typing import Any

from langchain_core.runnables import RunnableConfig
from langchain_core.tools import tool

from finance_agent.infrastructure.persistence.postgres.registry import get_product_library
from finance_agent.orchestration.experts.base import sink_of

PRODUCT_UNAVAILABLE = "产品研究暂不可用，请稍后重试。"


def _json(data: Any) -> str:
    return json.dumps(data, ensure_ascii=False, default=str)


@tool
def query_product(
    config: RunnableConfig,
    product_code: str = "",
    product_name: str = "",
) -> str:
    """按产品代码或名称查询产品库中的结构化数据。"""
    sink = sink_of(config)
    try:
        library = get_product_library()
        product = (
            library.query_by_code(product_code)
            if str(product_code or "").strip()
            else library.query_by_name(product_name)
        )
    except Exception:  # noqa: BLE001
        if sink is not None:
            sink.fail("product_catalog_failed")
        return _json({"error": PRODUCT_UNAVAILABLE})

    if product is None:
        if sink is not None:
            sink.limit("product_not_found")
        return _json({
            "error": "产品库暂无该产品数据",
            "product_code": product_code,
            "product_name": product_name,
        })

    payload = dict(product) if isinstance(product, dict) else product
    if sink is not None:
        products = list(sink.structured.get("products") or [])
        products.append(payload)
        sink.record("query_product", payload={"products": products, "product": payload})
    return _json(payload)


@tool
def list_products(config: RunnableConfig, product_type: str = "fund") -> str:
    """列出产品库中指定类型的产品。"""
    sink = sink_of(config)
    try:
        items = get_product_library().list_products(product_type)
    except Exception:  # noqa: BLE001
        if sink is not None:
            sink.fail("product_catalog_failed")
        return _json({"error": PRODUCT_UNAVAILABLE})

    if sink is not None:
        sink.record("list_products", payload={"product_list": items})
    return _json(items)


__all__ = [
    "PRODUCT_UNAVAILABLE",
    "list_products",
    "query_product",
]
