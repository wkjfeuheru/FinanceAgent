"""认证与账户生命周期路由。"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Request

from finance_agent.api.errors import http_500
from finance_agent.api.schemas.auth import LoginRequest, LoginResponse, RegisterRequest, RegisterResponse
from finance_agent.api.dependencies import _is_admin, _require_customer_id, get_system, get_user_store

router = APIRouter(tags=["auth"])


@router.post("/api/register", response_model=RegisterResponse)
async def register(request: RegisterRequest) -> RegisterResponse:
    try:
        return RegisterResponse(**get_user_store().register(
            username=request.username, password=request.password, display_name=request.display_name,
        ))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise http_500("注册", exc) from exc


@router.post("/api/login", response_model=LoginResponse)
async def login(request: LoginRequest) -> LoginResponse:
    try:
        result = get_user_store().login(username=request.username, password=request.password)
        result.pop("is_admin", None)
        return LoginResponse(**result, is_admin=_is_admin(result["customer_id"] if "customer_id" in result else ""))
    except ValueError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc
    except Exception as exc:
        raise http_500("登录", exc) from exc


@router.post("/api/logout")
async def logout(request: Request) -> dict[str, Any]:
    auth_header = request.headers.get("Authorization", "")
    if auth_header.startswith("Bearer "):
        get_user_store().logout(auth_header[7:].strip())
    return {"status": "ok", "message": "已登出"}


@router.get("/api/me")
async def get_current_user(request: Request) -> dict[str, Any]:
    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="未登录")
    customer_id = get_user_store().verify_token(auth_header[7:].strip())
    if not customer_id:
        raise HTTPException(status_code=401, detail="令牌无效或已过期")
    user = get_user_store().get_user_by_customer_id(customer_id)
    if not user:
        raise HTTPException(status_code=404, detail="用户不存在")
    return {**user, "is_admin": _is_admin(customer_id)}


@router.delete("/api/account")
async def delete_account(request: Request) -> dict[str, Any]:
    customer_id = _require_customer_id(request)
    user = get_user_store().get_user_by_customer_id(customer_id)
    if not user:
        raise HTTPException(status_code=404, detail="用户不存在")
    try:
        from finance_agent.orchestration.persistence_database import get_database

        system = get_system()
        client = system.memory.store._get_client()
        cleared = 0
        for suffix in ("messages", "recent_summary", "window"):
            cleared += client.delete(f"finance_cs:{customer_id.upper()}:{suffix}")
        for conv in get_database().list_conversations(customer_id):
            if system.delete_checkpoint_conversation(conv["conversation_id"], customer_id):
                cleared += 1
        cleared += system.clear_profile(customer_id)
        if get_user_store().delete_user(customer_id):
            cleared += 1
        return {"status": "ok", "message": f"账号已注销（{cleared} 个键已删除）"}
    except Exception as exc:
        raise http_500("注销", exc) from exc


__all__ = ["delete_account", "get_current_user", "login", "logout", "register", "router"]
