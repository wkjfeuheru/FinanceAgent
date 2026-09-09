"""业务数据库只读 LangChain 工具。

涵盖用户画像/会话记录（orchestrator.database）与产品库查询（data.product_library），
合并原 database.py 与 product.py 的所有业务库查询工具。
"""

from __future__ import annotations

import json
from typing import Any

from langchain_core.tools import tool

from finance_agent.data.product_library import get_product_library
from finance_agent.orchestrator.database import get_database


def _json(data: Any) -> str:
    return json.dumps(data, ensure_ascii=False, default=str)


def _required(value: str, field: str) -> str | None:
    value = str(value or "").strip()
    return value or f"缺少必要参数: {field}"


@tool
def query_user_profile(customer_id: str) -> str:
    """查询当前登录用户的投资画像，只返回业务画像字段。"""
    customer = _required(customer_id, "customer_id")
    if customer is None:
        return _json({"error": "customer_id 无效"})
    try:
        profile = get_database().get_profile(customer)
        return _json(profile or {"customer_id": customer, "message": "暂无投资画像"})
    except Exception:
        return _json({"error": "用户画像暂时不可用"})


@tool
def list_user_conversations(customer_id: str, limit: int = 20) -> str:
    """查询当前登录用户的会话摘要，最多返回指定数量。"""
    customer = _required(customer_id, "customer_id")
    if customer is None:
        return _json({"error": "customer_id 无效"})
    try:
        size = max(1, min(int(limit), 100))
        return _json(get_database().list_conversations(customer)[:size])
    except Exception:
        return _json({"error": "会话列表暂时不可用"})


@tool
def get_user_conversation_messages(
    customer_id: str, conversation_id: str, limit: int = 100
) -> str:
    """查询当前登录用户指定会话的消息，先校验会话归属。"""
    customer = _required(customer_id, "customer_id")
    conversation = _required(conversation_id, "conversation_id")
    if customer is None or conversation is None:
        return _json({"error": "customer_id 或 conversation_id 无效"})
    try:
        database = get_database()
        if database.get_conversation(conversation, customer) is None:
            return _json({"error": "会话不存在或无权访问"})
        size = max(1, min(int(limit), 200))
        return _json(database.get_conversation_messages(conversation, size))
    except Exception:
        return _json({"error": "会话消息暂时不可用"})


@tool
def query_product(product_code: str = "", product_name: str = "") -> str:
    """按产品代码或名称查询产品库中的结构化数据。"""
    try:
        library = get_product_library()
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
        return _json(get_product_library().list_products(product_type))
    except Exception:
        return _json({"error": "产品库暂时不可用，请稍后重试"})


__all__ = [
    "query_user_profile",
    "list_user_conversations",
    "get_user_conversation_messages",
    "query_product",
    "list_products",
]
