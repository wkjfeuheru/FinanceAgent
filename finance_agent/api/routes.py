"""API 路由定义。"""

from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, HTTPException, Header, Request
from fastapi.responses import StreamingResponse

from finance_agent.api.schemas import (
    ChatRequest,
    ChatResponse,
    ClearRecordsResponse,
    HealthResponse,
    HistoryResponse,
    LoginRequest,
    LoginResponse,
    ProfileResponse,
    RegisterRequest,
    RegisterResponse,
)
from finance_agent.api.sse import sse_stream
from finance_agent.tools.auth import get_user_store
from finance_agent.core.orchestrator import AdvisorSystem


router = APIRouter()

# 全局系统实例（延迟初始化）
_system: AdvisorSystem | None = None


def get_system() -> AdvisorSystem:
    """获取或初始化投顾系统实例。"""
    global _system
    if _system is None:
        _system = AdvisorSystem()
    return _system


# ── 用户认证接口 ────────────────────────────────────────────────

@router.post("/api/register", response_model=RegisterResponse)
async def register(request: RegisterRequest) -> RegisterResponse:
    """用户注册。"""
    try:
        result = get_user_store().register(
            username=request.username,
            password=request.password,
            display_name=request.display_name,
        )
        return RegisterResponse(**result)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"注册失败：{exc}")


@router.post("/api/login", response_model=LoginResponse)
async def login(request: LoginRequest) -> LoginResponse:
    """用户登录。"""
    try:
        result = get_user_store().login(
            username=request.username,
            password=request.password,
        )
        return LoginResponse(**result)
    except ValueError as exc:
        raise HTTPException(status_code=401, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"登录失败：{exc}")


@router.post("/api/logout")
async def logout(request: Request) -> dict[str, Any]:
    """用户登出：撤销当前 token。"""
    auth_header = request.headers.get("Authorization", "")
    if auth_header.startswith("Bearer "):
        token = auth_header[7:].strip()
        get_user_store().logout(token)
    return {"status": "ok", "message": "已登出"}


@router.get("/api/me")
async def get_current_user(request: Request) -> dict[str, Any]:
    """获取当前登录用户信息。"""
    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="未登录")
    token = auth_header[7:].strip()
    customer_id = get_user_store().verify_token(token)
    if not customer_id:
        raise HTTPException(status_code=401, detail="令牌无效或已过期")
    user = get_user_store().get_user_by_customer_id(customer_id)
    if not user:
        raise HTTPException(status_code=404, detail="用户不存在")
    return user


@router.get("/api/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    """健康检查。"""
    try:
        system = get_system()
        redis_ok = system.memory.store.is_available()
        return HealthResponse(
            status="ok",
            redis_available=redis_ok,
            agents_initialized=True,
        )
    except Exception as exc:
        return HealthResponse(
            status="error",
            redis_available=False,
            agents_initialized=False,
        )


@router.post("/api/chat", response_model=ChatResponse)
async def chat(
    request: ChatRequest,
    http_request: Request,
    x_customer_id: str | None = Header(default=None, alias="X-Customer-ID"),
) -> ChatResponse:
    """同步对话接口。

    customer_id 解析优先级：
    1. Authorization: Bearer <token> 中的 customer_id
    2. X-Customer-ID 请求头
    3. ChatRequest.customer_id 字段（兼容旧客户端）
    """
    customer_id = _resolve_customer_id(http_request, request, x_customer_id)
    try:
        system = get_system()
        result = system.handle_message(
            message=request.message,
            chat_history=request.chat_history,
            customer_id=customer_id,
            conversation_id=request.conversation_id,
        )
        return ChatResponse(**result)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"处理失败：{exc}")


@router.post("/api/chat/stream")
async def chat_stream(
    request: ChatRequest,
    http_request: Request,
    x_customer_id: str | None = Header(default=None, alias="X-Customer-ID"),
) -> StreamingResponse:
    """SSE 流式对话接口。"""
    customer_id = _resolve_customer_id(http_request, request, x_customer_id)
    system = get_system()

    async def event_generator():
        try:
            async for event in system.handle_message_stream(
                message=request.message,
                chat_history=request.chat_history,
                customer_id=customer_id,
                conversation_id=request.conversation_id,
            ):
                yield event
        except Exception as exc:
            yield {"type": "error", "message": str(exc)}

    return StreamingResponse(
        sse_stream(event_generator()),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


def _resolve_customer_id(http_request: Request, request: ChatRequest, x_customer_id: str | None) -> str:
    """优先从 Authorization token 解析 customer_id，回退到 X-Customer-ID 头，最后回退到请求体。"""
    auth_header = http_request.headers.get("Authorization", "")
    if auth_header.startswith("Bearer "):
        token = auth_header[7:].strip()
        customer_id = get_user_store().verify_token(token)
        if customer_id:
            return customer_id
    if x_customer_id:
        return x_customer_id
    return request.customer_id


@router.get("/api/profile/{customer_id}", response_model=ProfileResponse)
async def get_profile(customer_id: str) -> ProfileResponse:
    """获取用户画像。"""
    try:
        system = get_system()
        profile = system.get_user_profile(customer_id)
        return ProfileResponse(
            customer_id=profile.get("customer_id", customer_id),
            risk_preference=profile.get("risk_preference", ""),
            budget_amount=float(profile.get("budget_amount", 0) or 0),
            stock_codes=profile.get("stock_codes", []),
            holding_period=profile.get("holding_period", ""),
            investment_goal=profile.get("investment_goal", ""),
            updated_at=profile.get("updated_at", ""),
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"获取画像失败：{exc}")


@router.get("/api/history/{customer_id}", response_model=HistoryResponse)
async def get_history(customer_id: str, limit: int = 50) -> HistoryResponse:
    """获取对话历史。"""
    try:
        system = get_system()
        messages = system.memory.store.get_messages(customer_id, limit=limit)
        return HistoryResponse(customer_id=customer_id, messages=messages)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"获取历史失败：{exc}")


@router.post("/api/conversations/{customer_id}")
async def create_conversation(customer_id: str) -> dict[str, Any]:
    """创建一个独立的新对话。"""
    return get_system().memory.database.create_conversation(customer_id)


@router.get("/api/conversations/{customer_id}")
async def list_conversations(customer_id: str) -> dict[str, Any]:
    """获取用户的历史会话列表。"""
    system = get_system()
    database = system.memory.database
    items = database.list_conversations(customer_id)
    # One-time migration of the pre-conversation Redis sliding window
    # (by customer_id, not conversation_id).
    if not items:
        legacy_messages = system.memory.store.get_messages(customer_id)
        if legacy_messages:
            first_user = next(
                (str(item.get("content", "")) for item in legacy_messages if item.get("role") == "user"),
                "历史对话",
            )
            conversation = database.create_conversation(customer_id, first_user[:28])
            for item in legacy_messages:
                content = str(item.get("content", "")).strip()
                if content:
                    database.append_conversation_message(
                        conversation["conversation_id"],
                        "user" if item.get("role") == "user" else "assistant",
                        content,
                        item.get("metadata") if isinstance(item.get("metadata"), dict) else {},
                    )
            items = database.list_conversations(customer_id)
    return {"customer_id": customer_id.upper(), "conversations": items}


@router.get("/api/conversations/{customer_id}/{conversation_id}/messages")
async def get_conversation_messages(
    customer_id: str, conversation_id: str, limit: int = 100,
) -> dict[str, Any]:
    """读取指定会话，校验会话属于当前客户。"""
    database = get_system().memory.database
    if not database.get_conversation(conversation_id, customer_id):
        raise HTTPException(status_code=404, detail="对话不存在")
    return {
        "conversation_id": conversation_id,
        "messages": database.get_conversation_messages(conversation_id, limit),
    }


@router.delete("/api/conversations/{customer_id}/{conversation_id}")
async def delete_conversation(customer_id: str, conversation_id: str) -> dict[str, Any]:
    """删除指定历史对话及其全部消息。"""
    deleted = get_system().memory.database.delete_conversation(conversation_id, customer_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="对话不存在")
    return {"status": "ok", "conversation_id": conversation_id}


@router.post("/api/reset/{customer_id}")
async def reset_session(customer_id: str) -> dict[str, Any]:
    """重置会话。"""
    try:
        system = get_system()
        system.reset_session(customer_id)
        return {"status": "ok", "message": f"会话 {customer_id} 已重置"}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"重置失败：{exc}")


# ── 管理接口：清除旧记录 ─────────────────────────────────────────

@router.post("/api/admin/clear-records", response_model=ClearRecordsResponse)
async def clear_records(
    customer_id: str | None = None,
    keep_users: bool = True,
) -> ClearRecordsResponse:
    """清除对话记录。

    用途：清除 Redis 中残留的旧对话/画像/摘要记录。

    参数：
    - customer_id: 指定客户则只清该客户；不传则清除所有 finance_cs:* 对话数据
    - keep_users: 是否保留用户账号（finance_cs:user:* / finance_cs:token:* / finance_cs:user_index:*）
    """
    try:
        system = get_system()
        client = system.memory.store._get_client()
        cleared = 0

        if customer_id:
            # 仅清除指定客户的记录
            cid_upper = customer_id.upper()
            keys_to_delete = [
                f"finance_cs:{cid_upper}:messages",
                f"finance_cs:{cid_upper}:recent_summary",
                f"finance_cs:{cid_upper}:window",
            ]
            for key in keys_to_delete:
                cleared += client.delete(key)
            cleared += system.memory.database.delete_profiles(customer_id)
        else:
            # 扫描所有 finance_cs:* 键，按需保留用户数据
            for key in client.scan_iter(match="finance_cs:*", count=200):
                key_str = str(key)
                if keep_users and (
                    key_str.startswith("finance_cs:user:")
                    or key_str.startswith("finance_cs:token:")
                    or key_str.startswith("finance_cs:user_index:")
                    or key_str == "finance_cs:user_counter"
                ):
                    continue
                cleared += client.delete(key)
            # 同时重置共享内存和压缩器缓存
            system.shared_memory.reset()
            system.compressor.reset_cache()
            cleared += system.memory.database.delete_profiles()

        msg = (
            f"已清除客户 {customer_id} 的记录（{cleared} 个键）"
            if customer_id
            else f"已清除所有对话记录（{cleared} 个键）"
        )
        return ClearRecordsResponse(status="ok", cleared_keys=int(cleared), message=msg)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"清除失败：{exc}")


@router.delete("/api/account")
async def delete_account(request: Request) -> dict[str, Any]:
    """注销当前登录账号：删除用户记录与该客户所有对话数据。"""
    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="未登录")
    token = auth_header[7:].strip()
    customer_id = get_user_store().verify_token(token)
    if not customer_id:
        raise HTTPException(status_code=401, detail="令牌无效或已过期")

    user = get_user_store().get_user_by_customer_id(customer_id)
    if not user:
        raise HTTPException(status_code=404, detail="用户不存在")

    try:
        client = get_system().memory.store._get_client()
        cleared = 0
        # 清除该用户对话数据
        for suffix in ("messages", "recent_summary", "window"):
            cleared += client.delete(f"finance_cs:{customer_id.upper()}:{suffix}")
        # 清除用户索引与用户记录
        if get_user_store().delete_user(customer_id):
            cleared += 1
        # 撤销令牌
        return {"status": "ok", "message": f"账号已注销（{cleared} 个键已删除）"}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"注销失败：{exc}")
