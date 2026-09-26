"""客户隔离的 LangGraph 线程键。"""

from __future__ import annotations


_THREAD_KEY_VERSION = "v1"


def build_thread_id(customer_id: str, conversation_id: str) -> str:
    """构造稳定的 ``v1:{customer_id}:{conversation_id}`` 线程键。"""
    if not customer_id or ":" in customer_id or not conversation_id or ":" in conversation_id:
        raise ValueError("invalid thread key component")
    return f"{_THREAD_KEY_VERSION}:{customer_id.upper()}:{conversation_id}"


def parse_thread_id(thread_id: str) -> tuple[str, str]:
    """验证并拆解由 :func:`build_thread_id` 生成的线程键。"""
    parts = thread_id.split(":")
    if len(parts) != 3 or parts[0] != _THREAD_KEY_VERSION:
        raise ValueError("invalid thread key")
    customer_id, conversation_id = parts[1:]
    if not customer_id or not conversation_id:
        raise ValueError("invalid thread key")
    return customer_id, conversation_id
