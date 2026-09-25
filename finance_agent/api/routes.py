"""API 路由定义。"""
from __future__ import annotations

import asyncio
import json
import uuid
from datetime import datetime, timedelta
from typing import Any

from fastapi import APIRouter, HTTPException, Header, Request, Response
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
    ThemeRegistryEntry,
    ThemeRegistryUpsertRequest,
)
from finance_agent.api.sse import sse_stream
from finance_agent.api.errors import http_500, sse_error_message
from finance_agent.config import ADMIN_CUSTOMER_IDS, ORCHESTRATION_TURN_TIMEOUT, get_postgres_connection_factory
from finance_agent.data.auth import get_user_store
from finance_agent.orchestrator.orchestrator import AdvisorSystem
from finance_agent.research.theme_registry import PostgresThemeRegistry, ThemeEntry as _ThemeEntry
from finance_agent.research.theme_repository import PostgresThemeRepository, ThemeRepository


router = APIRouter()

# 全局系统实例（延迟初始化）
_system: AdvisorSystem | None = None
_theme_repository: ThemeRepository | None = None
_theme_registry: PostgresThemeRegistry | None = None


def get_theme_repository() -> ThemeRepository:
    """延迟构造 PostgreSQL 主题仓储，避免路由导入时连接数据库。"""
    global _theme_repository
    if _theme_repository is None:
        _theme_repository = PostgresThemeRepository(get_postgres_connection_factory())
    return _theme_repository


def get_theme_registry() -> PostgresThemeRegistry:
    """延迟构造主题注册表（读 + 管理写路径）。"""
    global _theme_registry
    if _theme_registry is None:
        _theme_registry = PostgresThemeRegistry(get_postgres_connection_factory())
    return _theme_registry


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
        raise http_500("注册", exc) from exc


@router.post("/api/login", response_model=LoginResponse)
async def login(request: LoginRequest) -> LoginResponse:
    """用户登录。"""
    try:
        result = get_user_store().login(
            username=request.username,
            password=request.password,
        )
        # 认证存储也会返回 is_admin；以 _is_admin 的解析结果为准（它同时计入白名单），
        # 因此先摘掉存储里的同名字段，避免重复关键字。
        result.pop("is_admin", None)
        return LoginResponse(**result, is_admin=_is_admin(result["customer_id"]))
    except ValueError as exc:
        raise HTTPException(status_code=401, detail=str(exc))
    except Exception as exc:
        raise http_500("登录", exc) from exc


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
    return {**user, "is_admin": _is_admin(customer_id)}


def _postgres_ready() -> bool:
    """探针级探测：业务库可连接且能执行 SELECT 1。"""
    try:
        connection = get_postgres_connection_factory()()
        try:
            cursor = connection.cursor()
            try:
                cursor.execute("SELECT 1")
                cursor.fetchone()
            finally:
                cursor.close()
        finally:
            connection.close()
        return True
    except Exception:
        return False


@router.get("/api/health", response_model=HealthResponse)
async def health(response: Response) -> HealthResponse:
    """健康检查。PostgreSQL 不可用或编排无法初始化时返回 503。"""
    postgres_ok = _postgres_ready()
    redis_ok = False
    agents_ok = False
    try:
        system = get_system()
        redis_ok = system.memory.store.is_available()
        agents_ok = True
    except Exception:
        agents_ok = False
    status = "ok" if postgres_ok and agents_ok else "error"
    payload = HealthResponse(
        status=status,
        redis_available=redis_ok,
        postgres_available=postgres_ok,
        agents_initialized=agents_ok,
    )
    if status != "ok":
        response.status_code = 503
    return payload


@router.get("/api/health/degradation")
async def degradation_health(http_request: Request) -> dict[str, Any]:
    """暴露各类降级的累计计数，供运维发现"静默失败"。

    落库/记忆/审计都是尽力而为、失败不阻断回复，因此这些故障不会出现在任何
    响应里；没有这个出口就只能等用户投诉才知道审计长期写不进去。
    该接口仅管理员可访问，避免把内部故障分类暴露给未授权调用方。
    """
    _require_admin(http_request)
    system = get_system()
    counts = getattr(system, "degradation_counts", None)
    return {"degradation_counts": counts() if callable(counts) else {}}


def _authorize_conversation(customer_id: str, conversation_id: str) -> None:
    """校验会话归属；非本人会话一律 404，避免跨用户读写。

    空 conversation_id 表示新建会话，不做校验。
    """
    if not conversation_id:
        return
    from finance_agent.orchestrator.persistence.database import get_database

    if get_database().get_conversation(conversation_id, customer_id) is None:
        raise HTTPException(status_code=404, detail="对话不存在")


@router.post("/api/chat", response_model=ChatResponse)
async def chat(
    request: ChatRequest,
    http_request: Request,
    x_customer_id: str | None = Header(default=None, alias="X-Customer-ID"),
) -> ChatResponse:
    """同步对话接口。身份只从 Authorization: Bearer 解析，忽略请求体与
    ``X-Customer-ID`` 中的 customer_id，避免客户端伪造身份。
    """
    customer_id = _resolve_customer_id(http_request, request, x_customer_id)
    _authorize_conversation(customer_id, request.conversation_id)
    try:
        system = get_system()
        # handle_message 是同步阻塞的（内部会调用 LLM、取数与量化轮询，单个请求
        # 可能持续数十秒）。必须放到工作线程执行，否则会占住整个 event loop，
        # 使其它请求（含健康检查与 SSE）全部排队等待。
        # 同时施加整轮墙钟上限：分项超时各自有界，但缺少整体上限时多个分项
        # 叠加仍可让单个请求长时间不返回。
        await_handle = asyncio.to_thread(
            system.handle_message,
            message=request.message,
            chat_history=request.chat_history,
            customer_id=customer_id,
            conversation_id=request.conversation_id,
            resume=request.resume,
            answers=request.answers,
        )
        if ORCHESTRATION_TURN_TIMEOUT > 0:
            result = await asyncio.wait_for(await_handle, timeout=ORCHESTRATION_TURN_TIMEOUT)
        else:
            result = await await_handle
        return ChatResponse(**result)
    except asyncio.TimeoutError:
        # 504 而非 500：这是"等超时"而非服务内部崩溃，调用方可据此重试。
        raise HTTPException(status_code=504, detail="处理超时，请稍后重试或缩小问题范围")
    except Exception as exc:
        raise http_500("处理", exc) from exc


@router.post("/api/chat/stream")
async def chat_stream(
    request: ChatRequest,
    http_request: Request,
    x_customer_id: str | None = Header(default=None, alias="X-Customer-ID"),
) -> StreamingResponse:
    """SSE 流式对话接口。"""
    customer_id = _resolve_customer_id(http_request, request, x_customer_id)
    _authorize_conversation(customer_id, request.conversation_id)
    system = get_system()

    async def event_generator():
        try:
            async for event in system.handle_message_stream(
                message=request.message,
                chat_history=request.chat_history,
                customer_id=customer_id,
                conversation_id=request.conversation_id,
                resume=request.resume,
                answers=request.answers,
            ):
                yield event
        except Exception as exc:
            yield {"type": "error", "message": sse_error_message(exc)}

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
    customer_id = _require_customer_id(http_request)
    if not conversation_id and not run_id:
        raise HTTPException(status_code=400, detail="需提供 conversation_id 或 run_id")
    if run_id:
        system = get_system()
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
        # 会话归属校验：stop 按 conversation_id 索引停止标记，若不校验归属，
        # 任何登录用户只要知道 id 就能停掉他人的运行。
        from finance_agent.orchestrator.persistence.database import get_database

        if get_database().get_conversation(conversation_id, customer_id) is None:
            raise HTTPException(status_code=404, detail="会话不存在或无权操作")
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


@router.get("/api/runs/{task_id}")
async def get_run_status(http_request: Request, task_id: str) -> dict[str, Any]:
    """查询异步运行状态；先校验客户归属再读取异步状态或恢复图。"""
    customer_id = _require_customer_id(http_request)
    system = get_system()
    resolver = getattr(system, "resolve_run_status", None)
    if resolver is None:
        raise HTTPException(status_code=404, detail="运行不存在")
    return resolver(task_id, customer_id)


def _authorize_customer(request: Request, path_customer_id: str) -> str:
    """要求已登录，且路径中的 customer_id 必须等于登录用户，否则 403。"""
    current = _require_customer_id(request)
    if str(current).upper() != str(path_customer_id).upper():
        raise HTTPException(status_code=403, detail="无权访问该客户资源")
    return current


def _resolve_customer_id(http_request: Request, request: ChatRequest, x_customer_id: str | None) -> str:
    """从有效 Bearer token 解析 customer_id；未登录请求统一拒绝。"""
    return _require_customer_id(http_request)


def _is_admin(customer_id: str) -> bool:
    """判断客户是否为管理员。

    两条路径取并集：命中 ``ADMIN_CUSTOMER_IDS`` 环境变量白名单，或库内
    ``finance.users.is_admin`` 为真。白名单保留是为了让"改配置即可授权"的既有
    运维方式继续可用；库内角色则是可持久、可在后台自助授予的正式路径。

    角色查询失败必须**失败关闭**：宁可把管理员操作拒掉，也不能因为库不可用
    就让任何人都成为管理员。
    """
    if str(customer_id).upper() in ADMIN_CUSTOMER_IDS:
        return True
    try:
        checker = getattr(get_user_store(), "is_admin", None)
        if checker is None:
            return False
        return bool(checker(customer_id))
    except Exception:  # noqa: BLE001 - 授权查询失败按"非管理员"处理
        return False


def _require_admin(request: Request) -> str:
    customer_id = _require_customer_id(request)
    if not _is_admin(customer_id):
        raise HTTPException(status_code=403, detail="仅管理员可访问该接口")
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


@router.get("/api/admin/themes", response_model=list[ThemeRegistryEntry])
async def list_registered_themes(http_request: Request) -> list[ThemeRegistryEntry]:
    """管理员查看主题注册表（名称/别名 → theme_id 的映射来源）。"""
    _require_admin(http_request)
    return [
        ThemeRegistryEntry(
            theme_id=entry.theme_id, display_name=entry.display_name,
            aliases=list(entry.aliases),
            representative_codes=list(entry.representative_codes),
            active=entry.active,
        )
        for entry in get_theme_registry().list_themes()
    ]


@router.post("/api/admin/themes", response_model=ThemeRegistryEntry)
async def upsert_registered_theme(
    payload: ThemeRegistryUpsertRequest, http_request: Request,
) -> ThemeRegistryEntry:
    """新增或更新主题注册记录；写盘一律以本表为解析来源。"""
    _require_admin(http_request)
    theme_id = payload.theme_id.strip()
    if theme_id in {"", "market_insight"}:
        raise HTTPException(status_code=400, detail="theme_id 非法")
    aliases = list(dict.fromkeys(
        alias.strip() for alias in payload.aliases if alias.strip()
    ))
    representative_codes = list(dict.fromkeys(
        code.strip() for code in payload.representative_codes if code.strip()
    ))
    entry = get_theme_registry().upsert(
        _ThemeEntry(
            theme_id=theme_id,
            display_name=payload.display_name.strip(),
            aliases=aliases,
            representative_codes=representative_codes,
            active=payload.active,
        )
    )
    return ThemeRegistryEntry(
        theme_id=entry.theme_id, display_name=entry.display_name,
        aliases=list(entry.aliases),
        representative_codes=list(entry.representative_codes),
        active=entry.active,
    )


@router.delete("/api/admin/themes/{theme_id}")
async def deactivate_registered_theme(http_request: Request, theme_id: str) -> dict[str, Any]:
    """软删除主题（置 active=false）：保留历史映射，仅停止参与解析。"""
    _require_admin(http_request)
    if not get_theme_registry().deactivate(theme_id):
        raise HTTPException(status_code=404, detail="主题不存在")
    return {"theme_id": theme_id, "active": False}


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
        raise http_500("获取画像", exc) from exc


@router.get("/api/history/{customer_id}", response_model=HistoryResponse)
async def get_history(http_request: Request, customer_id: str, limit: int = 100) -> HistoryResponse:
    """获取用户对话历史（跨会话，最近 limit 条，按时间正序）。"""
    _authorize_customer(http_request, customer_id)
    from finance_agent.orchestrator.persistence.database import get_database
    messages = get_database().get_customer_messages(customer_id, limit)
    return HistoryResponse(customer_id=customer_id.upper(), messages=messages)


# ── 对话管理（基于 finance_agent.db）───────────────────────────────────

@router.post("/api/conversations/{customer_id}")
async def create_conversation(http_request: Request, customer_id: str) -> dict[str, Any]:
    """创建一个新对话。"""
    _authorize_customer(http_request, customer_id)
    from finance_agent.orchestrator.persistence.database import get_database
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
    from finance_agent.orchestrator.persistence.database import get_database
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
    # 删除前校验归属：与消息接口一致，非本人会话不得清除任何数据。
    _authorize_conversation(customer_id, conversation_id)
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
        raise http_500("重置", exc) from exc


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
    if customer_id is None and not _is_admin(current):
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
            from finance_agent.orchestrator.persistence.database import get_database
            for conv in get_database().list_conversations(customer_id):
                cleared += int(
                    system.memory.store.clear_conversation(customer_id, conv["conversation_id"])
                )
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
        raise http_500("清除", exc) from exc


@router.delete("/api/account")
async def delete_account(request: Request) -> dict[str, Any]:
    """注销当前登录账号：删除用户记录与该客户所有对话/画像数据。"""
    customer_id = _require_customer_id(request)

    user = get_user_store().get_user_by_customer_id(customer_id)
    if not user:
        raise HTTPException(status_code=404, detail="用户不存在")

    try:
        system = get_system()
        from finance_agent.orchestrator.persistence.database import get_database
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
        raise http_500("注销", exc) from exc
