"""API 路由定义。"""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timedelta
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
    ThemeLeadResponse,
    ThemeLeadReviewRequest,
)
from finance_agent.api.sse import sse_stream
from finance_agent.config import ADMIN_CUSTOMER_IDS, get_postgres_connection_factory
from finance_agent.data.auth import get_user_store
from finance_agent.orchestrator.orchestrator import AdvisorSystem
from finance_agent.research.theme_repository import PostgresThemeRepository, ThemeRepository


router = APIRouter()

# 全局系统实例（延迟初始化）
_system: AdvisorSystem | None = None
_theme_repository: ThemeRepository | None = None


def get_theme_repository() -> ThemeRepository:
    """延迟构造 PostgreSQL 主题仓储，避免路由导入时连接数据库。"""
    global _theme_repository
    if _theme_repository is None:
        _theme_repository = PostgresThemeRepository(get_postgres_connection_factory())
    return _theme_repository


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


@router.post("/api/chat/stop")
async def chat_stop(
    http_request: Request,
    conversation_id: str = "",
    run_id: str = "",
) -> dict[str, Any]:
    """请求停止指定会话/运行的生成；已完成的专家结果保留。"""
    _require_customer_id(http_request)
    if not conversation_id and not run_id:
        raise HTTPException(status_code=400, detail="需提供 conversation_id 或 run_id")
    stopped = get_system().request_stop(conversation_id=conversation_id, run_id=run_id)
    return {"status": "ok", "stopped": stopped, "conversation_id": conversation_id, "run_id": run_id}


def _require_customer_id(request: Request) -> str:
    """从 Authorization: Bearer 解析并校验 token，返回 customer_id；失败抛 401。"""
    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="未登录")
    customer_id = get_user_store().verify_token(auth_header[7:].strip())
    if not customer_id:
        raise HTTPException(status_code=401, detail="令牌无效或已过期")
    return customer_id


def _authorize_customer(request: Request, path_customer_id: str) -> str:
    """要求已登录，且路径中的 customer_id 必须等于登录用户，否则 403。"""
    current = _require_customer_id(request)
    if str(current).upper() != str(path_customer_id).upper():
        raise HTTPException(status_code=403, detail="无权访问该客户资源")
    return current


def _resolve_customer_id(http_request: Request, request: ChatRequest, x_customer_id: str | None) -> str:
    """从有效 Bearer token 解析 customer_id；未登录请求统一拒绝。"""
    return _require_customer_id(http_request)


def _require_admin(request: Request) -> str:
    customer_id = _require_customer_id(request)
    if customer_id.upper() not in ADMIN_CUSTOMER_IDS:
        raise HTTPException(status_code=403, detail="仅管理员可审核主题线索")
    return customer_id


@router.get("/api/admin/themes/{theme_id}/leads", response_model=list[ThemeLeadResponse])
async def list_theme_leads(http_request: Request, theme_id: str) -> list[ThemeLeadResponse]:
    """仅管理员可见的待核验研究线索，不含评分和行动结论。"""
    _require_admin(http_request)
    return [
        ThemeLeadResponse(
            **lead.model_dump(),
            evidence_expires_at=lead.discovered_at + timedelta(days=30),
        )
        for lead in get_theme_repository().pending_leads(theme_id)
    ]


@router.post("/api/admin/theme-leads/{lead_id}/review")
async def review_theme_lead(
    lead_id: str, payload: ThemeLeadReviewRequest, http_request: Request,
) -> dict[str, Any]:
    """审核现有线索；不得修改原股票代码或证据内容。"""
    reviewer_id = _require_admin(http_request)
    try:
        expires_at = datetime.fromisoformat(payload.evidence_expires_at.replace("Z", "+00:00"))
        member = get_theme_repository().review_lead(
            lead_id, reviewer_id=reviewer_id, decision=payload.decision,
            expires_at=expires_at, note=payload.note,
        )
        return member.model_dump(mode="json")
    except KeyError:
        raise HTTPException(status_code=404, detail="待审核线索不存在")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.get("/api/profile/{customer_id}", response_model=ProfileResponse)
async def get_profile(http_request: Request, customer_id: str) -> ProfileResponse:
    """获取用户画像（从 checkpoint 读取）。"""
    _authorize_customer(http_request, customer_id)
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
async def get_history(http_request: Request, customer_id: str, limit: int = 100) -> HistoryResponse:
    """获取用户对话历史（跨会话，最近 limit 条，按时间正序）。"""
    _authorize_customer(http_request, customer_id)
    from finance_agent.orchestrator.database import get_database
    messages = get_database().get_customer_messages(customer_id, limit)
    return HistoryResponse(customer_id=customer_id.upper(), messages=messages)


# ── 对话管理（基于 finance_agent.db）───────────────────────────────────

@router.post("/api/conversations/{customer_id}")
async def create_conversation(http_request: Request, customer_id: str) -> dict[str, Any]:
    """创建一个新对话。"""
    _authorize_customer(http_request, customer_id)
    from finance_agent.orchestrator.database import get_database
    return get_database().create_conversation(customer_id)


@router.get("/api/conversations/{customer_id}")
async def list_conversations(http_request: Request, customer_id: str) -> dict[str, Any]:
    """获取用户的历史对话列表（从 finance_agent.db 查询）。"""
    _authorize_customer(http_request, customer_id)
    system = get_system()
    items = system.list_checkpoint_conversations(customer_id)
    return {"customer_id": customer_id.upper(), "conversations": items}


@router.get("/api/conversations/{customer_id}/{conversation_id}/messages")
async def get_conversation_messages(
    http_request: Request, customer_id: str, conversation_id: str, limit: int = 100,
) -> dict[str, Any]:
    """读取指定对话的消息（从 finance_agent.db 查询）。"""
    _authorize_customer(http_request, customer_id)
    from finance_agent.orchestrator.database import get_database
    # 确认对话属于该 customer
    conv = get_database().get_conversation(conversation_id, customer_id)
    if not conv:
        raise HTTPException(status_code=404, detail="对话不存在")
    system = get_system()
    return {
        "conversation_id": conversation_id,
        "messages": system.get_checkpoint_conversation_messages(conversation_id, limit),
    }


@router.delete("/api/conversations/{customer_id}/{conversation_id}")
async def delete_conversation(http_request: Request, customer_id: str, conversation_id: str) -> dict[str, Any]:
    """删除指定历史对话及其全部数据。"""
    _authorize_customer(http_request, customer_id)
    deleted = get_system().delete_checkpoint_conversation(conversation_id, customer_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="对话不存在")
    return {"status": "ok", "conversation_id": conversation_id}


@router.post("/api/reset/{customer_id}")
async def reset_session(http_request: Request, customer_id: str) -> dict[str, Any]:
    """重置会话：清除该客户所有会话的短期记忆（窗口 + 摘要）。"""
    _authorize_customer(http_request, customer_id)
    try:
        system = get_system()
        cleared = system.reset_session(customer_id)
        return {"status": "ok", "message": f"会话 {customer_id} 已重置", "cleared_conversations": cleared}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"重置失败：{exc}")


# ── 管理接口：清除旧记录 ─────────────────────────────────────────

@router.post("/api/admin/clear-records", response_model=ClearRecordsResponse)
async def clear_records(
    http_request: Request,
    customer_id: str | None = None,
    keep_users: bool = True,
) -> ClearRecordsResponse:
    """清除对话记录。

    用途：清除 Redis 中残留的旧对话/画像/摘要记录 + checkpoint 画像。

    参数：
    - customer_id: 指定客户则只清该客户；不传则清除所有 finance_cs:* 对话数据
    - keep_users: 是否保留用户账号（finance_cs:user:* / finance_cs:token:* / finance_cs:user_index:*）
    """
    current = _require_customer_id(http_request)
    if customer_id and str(customer_id).upper() != str(current).upper():
        raise HTTPException(status_code=403, detail="无权清除其他客户记录")
    if customer_id is None and str(current).upper() not in ADMIN_CUSTOMER_IDS:
        raise HTTPException(status_code=403, detail="仅管理员可清除全部记录")
    try:
        system = get_system()
        client = system.memory.store._get_client()
        cleared = 0

        if customer_id:
            # 仅清除指定客户的记录
            cid_upper = customer_id.upper()
            # 旧格式残留键（历史版本）
            for suffix in ("messages", "recent_summary", "window"):
                cleared += client.delete(f"finance_cs:{cid_upper}:{suffix}")
            # 当前格式：按会话清除窗口/摘要
            from finance_agent.orchestrator.database import get_database
            for conv in get_database().list_conversations(customer_id):
                cleared += int(system.memory.store.clear_conversation(conv["conversation_id"]))
            cleared += system.clear_profile(customer_id)
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
            cleared += system.clear_profile()

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
    """注销当前登录账号：删除用户记录与该客户所有对话/画像数据。"""
    customer_id = _require_customer_id(request)

    user = get_user_store().get_user_by_customer_id(customer_id)
    if not user:
        raise HTTPException(status_code=404, detail="用户不存在")

    try:
        system = get_system()
        from finance_agent.orchestrator.database import get_database
        client = system.memory.store._get_client()
        cleared = 0
        # 旧格式残留键
        for suffix in ("messages", "recent_summary", "window"):
            cleared += client.delete(f"finance_cs:{customer_id.upper()}:{suffix}")
        # 逐会话删除：业务库会话/消息 + checkpoint + 记忆窗口/摘要
        for conv in get_database().list_conversations(customer_id):
            if system.delete_checkpoint_conversation(conv["conversation_id"], customer_id):
                cleared += 1
        # 清除画像
        cleared += system.clear_profile(customer_id)
        # 删除用户认证记录
        if get_user_store().delete_user(customer_id):
            cleared += 1
        return {"status": "ok", "message": f"账号已注销（{cleared} 个键已删除）"}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"注销失败：{exc}")
