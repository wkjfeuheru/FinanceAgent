"""SSE 流式响应封装。"""

from __future__ import annotations

import json
from typing import Any, AsyncIterator

from finance_agent.api.schemas import ChatResponse, to_chat_response
from finance_agent.contracts.models import ResponseEnvelope


def format_sse_event(data: dict[str, Any], event: str = "message") -> str:
    """格式化 SSE 事件。"""
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


def build_final_response_event(
    result: ResponseEnvelope | dict[str, Any] | ChatResponse,
) -> dict[str, Any]:
    """构造保留旧 response/content/data 形状的最终 SSE 事件。"""
    response = to_chat_response(result)
    return {
        "type": "response",
        "content": response.response,
        "data": response.model_dump(mode="json"),
    }


def build_async_task_event(task_id: str, status: str) -> dict[str, Any]:
    """构造异步量化任务进度事件（新增阶段事件，不改变既有事件形状）。"""
    return {"type": "async_task", "task_id": task_id, "status": status}


async def sse_stream(events: AsyncIterator[dict[str, Any]]) -> AsyncIterator[str]:
    """将事件流转换为 SSE 格式字符串流。"""
    async for event in events:
        event_type = event.get("type", "message")
        yield format_sse_event(event, event_type)
