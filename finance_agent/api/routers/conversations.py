"""会话、对话历史与用户画像路由。"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request

from finance_agent.api.errors import http_500
from finance_agent.api.schemas.conversations import HistoryResponse, ProfileResponse
from finance_agent.api.dependencies import _authorize_conversation, _authorize_customer, get_system

router = APIRouter(tags=["conversations"])


@router.get("/api/profile/{customer_id}", response_model=ProfileResponse)
async def get_profile(http_request: Request, customer_id: str) -> ProfileResponse:
    _authorize_customer(http_request, customer_id)
    try:
        profile = get_system().get_user_profile(customer_id)
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
    _authorize_customer(http_request, customer_id)
    from finance_agent.orchestration.persistence_database import get_database
    messages = get_database().get_customer_messages(customer_id, limit)
    return HistoryResponse(customer_id=customer_id.upper(), messages=messages)


@router.post("/api/conversations/{customer_id}")
async def create_conversation(http_request: Request, customer_id: str) -> dict:
    _authorize_customer(http_request, customer_id)
    from finance_agent.orchestration.persistence_database import get_database
    return get_database().create_conversation(customer_id)


@router.get("/api/conversations/{customer_id}")
async def list_conversations(http_request: Request, customer_id: str) -> dict:
    _authorize_customer(http_request, customer_id)
    items = get_system().list_checkpoint_conversations(customer_id)
    return {"customer_id": customer_id.upper(), "conversations": items}


@router.get("/api/conversations/{customer_id}/{conversation_id}/messages")
async def get_conversation_messages(http_request: Request, customer_id: str,
                                   conversation_id: str, limit: int = 100) -> dict:
    _authorize_customer(http_request, customer_id)
    from finance_agent.orchestration.persistence_database import get_database
    if not get_database().get_conversation(conversation_id, customer_id):
        raise HTTPException(status_code=404, detail="对话不存在")
    return {"conversation_id": conversation_id,
            "messages": get_system().get_checkpoint_conversation_messages(conversation_id, limit)}


@router.delete("/api/conversations/{customer_id}/{conversation_id}")
async def delete_conversation(http_request: Request, customer_id: str, conversation_id: str) -> dict:
    _authorize_customer(http_request, customer_id)
    _authorize_conversation(customer_id, conversation_id)
    if not get_system().delete_checkpoint_conversation(conversation_id, customer_id):
        raise HTTPException(status_code=404, detail="对话不存在")
    return {"status": "ok", "conversation_id": conversation_id}


@router.post("/api/reset/{customer_id}")
async def reset_session(http_request: Request, customer_id: str) -> dict:
    _authorize_customer(http_request, customer_id)
    try:
        cleared = get_system().reset_session(customer_id)
        return {"status": "ok", "message": f"会话 {customer_id} 已重置", "cleared_conversations": cleared}
    except Exception as exc:
        raise http_500("重置", exc) from exc


__all__ = ["create_conversation", "delete_conversation", "get_conversation_messages", "get_history",
           "get_profile", "list_conversations", "reset_session", "router"]
