"""同步、流式与异步运行状态路由。"""

from __future__ import annotations

import asyncio
from typing import Any

from fastapi import APIRouter, Header, HTTPException, Request
from fastapi.responses import StreamingResponse

from finance_agent.api.schemas.chat import ChatRequest, ChatResponse
from finance_agent.api.errors import http_500, sse_error_message
from finance_agent.api.dependencies import (
    _authorize_conversation, _require_customer_id, _resolve_customer_id, get_system,
)
from finance_agent.api.sse import sse_stream
from finance_agent.infrastructure.settings import ORCHESTRATION_TURN_TIMEOUT

router = APIRouter(tags=["chat"])


@router.post("/api/chat", response_model=ChatResponse)
async def chat(request: ChatRequest, http_request: Request,
               x_customer_id: str | None = Header(default=None, alias="X-Customer-ID")) -> ChatResponse:
    customer_id = _resolve_customer_id(http_request, request, x_customer_id)
    _authorize_conversation(customer_id, request.conversation_id)
    try:
        system = get_system()
        await_handle = asyncio.to_thread(
            system.handle_message, message=request.message, chat_history=request.chat_history,
            customer_id=customer_id, conversation_id=request.conversation_id,
            resume=request.resume, answers=request.answers,
        )
        if ORCHESTRATION_TURN_TIMEOUT > 0:
            result = await asyncio.wait_for(await_handle, timeout=ORCHESTRATION_TURN_TIMEOUT)
        else:
            result = await await_handle
        return ChatResponse(**result)
    except asyncio.TimeoutError as exc:
        raise HTTPException(status_code=504, detail="处理超时，请稍后重试或缩小问题范围") from exc
    except HTTPException:
        raise
    except Exception as exc:
        raise http_500("处理", exc) from exc


@router.post("/api/chat/stream")
async def chat_stream(request: ChatRequest, http_request: Request,
                      x_customer_id: str | None = Header(default=None, alias="X-Customer-ID")) -> StreamingResponse:
    customer_id = _resolve_customer_id(http_request, request, x_customer_id)
    _authorize_conversation(customer_id, request.conversation_id)
    system = get_system()

    async def event_generator():
        try:
            async for event in system.handle_message_stream(
                message=request.message, chat_history=request.chat_history, customer_id=customer_id,
                conversation_id=request.conversation_id, resume=request.resume, answers=request.answers,
            ):
                yield event
        except Exception as exc:
            yield {"type": "error", "message": sse_error_message(exc)}

    return StreamingResponse(
        sse_stream(event_generator()), media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive", "X-Accel-Buffering": "no"},
    )


@router.post("/api/chat/stop")
async def chat_stop(http_request: Request, conversation_id: str = "", run_id: str = "") -> dict[str, Any]:
    customer_id = _require_customer_id(http_request)
    if not conversation_id and not run_id:
        raise HTTPException(status_code=400, detail="需提供 conversation_id 或 run_id")
    system = get_system()
    if run_id:
        owner = getattr(system, "lookup_active_run", None)
        active = owner(run_id) if callable(owner) else None
        if active is None:
            raise HTTPException(status_code=404, detail="运行不存在或无权操作")
        run_conversation_id, run_customer_id = active
        if not run_customer_id or run_customer_id.upper() != customer_id.upper():
            raise HTTPException(status_code=404, detail="运行不存在或无权操作")
        if conversation_id and run_conversation_id and conversation_id != run_conversation_id:
            raise HTTPException(status_code=404, detail="运行不存在或无权操作")
        conversation_id = conversation_id or run_conversation_id
    if conversation_id:
        from finance_agent.orchestration.persistence_database import get_database
        if get_database().get_conversation(conversation_id, customer_id) is None:
            raise HTTPException(status_code=404, detail="会话不存在或无权操作")
    stopped = system.request_stop(conversation_id=conversation_id, run_id=run_id)
    return {"status": "ok", "stopped": stopped, "conversation_id": conversation_id, "run_id": run_id}


@router.get("/api/runs/{task_id}")
async def get_run_status(http_request: Request, task_id: str) -> dict[str, Any]:
    customer_id = _require_customer_id(http_request)
    resolver = getattr(get_system(), "resolve_run_status", None)
    if resolver is None:
        raise HTTPException(status_code=404, detail="运行不存在")
    return resolver(task_id, customer_id)


__all__ = ["chat", "chat_stop", "chat_stream", "get_run_status", "router"]
