"""SSE 流式响应封装。"""

from __future__ import annotations

import json
from typing import Any, AsyncIterator


def format_sse_event(data: dict[str, Any], event: str = "message") -> str:
    """格式化 SSE 事件。"""
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


async def sse_stream(events: AsyncIterator[dict[str, Any]]) -> AsyncIterator[str]:
    """将事件流转换为 SSE 格式字符串流。"""
    async for event in events:
        event_type = event.get("type", "message")
        yield format_sse_event(event, event_type)
