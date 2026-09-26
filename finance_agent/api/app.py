"""FastAPI 应用组装。ASGI 部署入口继续通过 ``finance_agent.main:app`` 导出。"""

from __future__ import annotations

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from starlette.responses import JSONResponse

from finance_agent.api.rate_limit import enforce_auth_rate_limit
from finance_agent.api.routers.admin import root_router as admin_root_router
from finance_agent.api.routers.admin import router as admin_router
from finance_agent.api.routers.auth import router as auth_router
from finance_agent.api.routers.chat import router as chat_router
from finance_agent.api.routers.conversations import router as conversations_router
from finance_agent.api.routers.health import router as health_router
from finance_agent.api.routers.portfolio import router as portfolio_router
from finance_agent.infrastructure.settings import CORS_ALLOW_ORIGINS, IS_PRODUCTION


app = FastAPI(
    title="金融智能投顾 API",
    description="基于多Agent的金融智能投顾系统后端API",
    version="2.1.0",
    docs_url=None if IS_PRODUCTION else "/docs",
    redoc_url=None if IS_PRODUCTION else "/redoc",
    openapi_url=None if IS_PRODUCTION else "/openapi.json",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ALLOW_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth_router)
app.include_router(chat_router)
app.include_router(conversations_router)
app.include_router(health_router)
app.include_router(portfolio_router)
app.include_router(admin_router)
app.include_router(admin_root_router)


@app.get("/")
async def root():
    payload = {
        "service": "金融智能投顾 API",
        "version": "2.1.0",
        "health": "/api/health",
    }
    if not IS_PRODUCTION:
        payload["docs"] = "/docs"
        payload["endpoints"] = [
            "POST /api/register",
            "POST /api/login",
            "POST /api/logout",
            "GET  /api/me",
            "POST /api/chat",
            "POST /api/chat/stream",
            "POST /api/chat/stop",
            "GET  /api/profile/{customer_id}",
            "GET  /api/history/{customer_id}",
            "POST /api/conversations/{customer_id}",
            "GET  /api/conversations/{customer_id}",
            "GET  /api/conversations/{customer_id}/{conversation_id}/messages",
            "DELETE /api/conversations/{customer_id}/{conversation_id}",
            "POST /api/reset/{customer_id}",
            "POST /api/admin/clear-records",
            "GET  /api/admin/users",
            "GET  /api/admin/users/{customer_id}/portfolio",
            "GET  /api/admin/products",
            "POST /api/admin/products",
            "POST /api/admin/products/{code}/offline",
            "POST /api/admin/products/{code}/publish",
            "DELETE /api/account",
            "GET  /api/health",
            "GET  /api/portfolio/products",
            "GET  /api/portfolio/products/{code}",
            "GET  /api/portfolio/account",
            "GET  /api/portfolio/positions",
            "POST /api/portfolio/deposit",
            "POST /api/portfolio/orders",
            "POST /api/portfolio/liquidate",
            "GET  /api/portfolio/orders",
            "GET  /api/portfolio/transactions",
        ]
    return payload


@app.middleware("http")
async def auth_rate_limit_middleware(request, call_next):
    """登录/注册进程内限流，抵御凭据爆破。"""
    path = request.url.path.rstrip("/")
    if request.method == "POST" and path in {"/api/login", "/api/register"}:
        action = "login" if path.endswith("login") else "register"
        try:
            enforce_auth_rate_limit(request, action)
        except HTTPException as exc:
            return JSONResponse({"detail": exc.detail}, status_code=exc.status_code)
    return await call_next(request)
