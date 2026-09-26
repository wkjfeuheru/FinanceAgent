"""会话与用户画像只读 LangChain 工具（未进四个专家白名单）。"""

from __future__ import annotations

import json
from typing import Any

from langchain_core.tools import tool

from finance_agent.orchestration.persistence_database import get_database


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


__all__ = [
    "query_user_profile",
    "list_user_conversations",
    "get_user_conversation_messages",
]
