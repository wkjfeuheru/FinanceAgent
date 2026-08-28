"""产品库查询 LangChain 工具。"""

from __future__ import annotations

import json

from langchain_core.tools import tool

from finance_agent.data.product_library import ProductLibrary


def _json(data: object) -> str:
    """将产品数据序列化为模型可读的 JSON。"""
    return json.dumps(data, ensure_ascii=False, default=str)


@tool
def query_product(product_code: str = "", product_name: str = "") -> str:
    """按产品代码或名称查询产品库中的结构化数据。"""
    try:
        library = ProductLibrary()
        product = library.query_by_code(product_code) if product_code.strip() else library.query_by_name(product_name)
        if product is None:
            return _json({"error": "产品库暂无该产品数据", "product_code": product_code, "product_name": product_name})
        return _json(product)
    except Exception:
        return _json({"error": "产品库暂时不可用，请稍后重试"})


@tool
def list_products(product_type: str = "fund") -> str:
    """列出产品库中指定类型的产品。"""
    try:
        return _json(ProductLibrary().list_products(product_type))
    except Exception:
        return _json({"error": "产品库暂时不可用，请稍后重试"})


__all__ = ["query_product", "list_products"]
