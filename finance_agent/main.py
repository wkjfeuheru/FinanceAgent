"""FastAPI 应用入口。

启动方式：
    uvicorn finance_agent.main:app --reload --port 8000
"""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from starlette.responses import JSONResponse

from finance_agent.api.admin_routes import router as admin_router
from finance_agent.api.portfolio_routes import router as portfolio_router
from finance_agent.api.rate_limit import enforce_auth_rate_limit
from finance_agent.api.routes import router
from finance_agent.config import CORS_ALLOW_ORIGINS, IS_PRODUCTION


def fastapi_docs_kwargs(*, is_production: bool = IS_PRODUCTION) -> dict[str, None]:
    """生产环境关闭 OpenAPI 文档，避免把完整攻击面公开在 /docs。"""
    if is_production:
        return {"docs_url": None, "redoc_url": None, "openapi_url": None}
    return {}


_docs_kwargs = fastapi_docs_kwargs()

app = FastAPI(
    title="金融智能投顾 API",
    description="基于多Agent的金融智能投顾系统后端API",
    version="2.1.0",
    **_docs_kwargs,
)

# CORS：默认仅本地开发源；生产通过 CORS_ALLOW_ORIGINS 显式配置。
app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ALLOW_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 挂载路由
app.include_router(router)
# 模拟交易：商品展示、购买、持仓、清仓与账户面板
app.include_router(portfolio_router)
# 管理后台：商品发行/上下架与全站用户总览（仅管理员）
app.include_router(admin_router)


@app.middleware("http")
async def auth_rate_limit_middleware(request, call_next):
    """登录/注册的进程内滑动窗口，避免把 Request 塞进路由签名。"""
    from fastapi import HTTPException

    path = request.url.path.rstrip("/")
    if request.method == "POST" and path in {"/api/login", "/api/register"}:
        action = "login" if path.endswith("login") else "register"
        try:
            enforce_auth_rate_limit(request, action)
        except HTTPException as exc:
            return JSONResponse({"detail": exc.detail}, status_code=exc.status_code)
    return await call_next(request)


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


if __name__ == "__main__":
    import uvicorn

    from finance_agent.config import UVICORN_HOST, UVICORN_PORT

    # 默认使用单进程运行。自动重载会创建父子进程；当分析线程仍在执行时，
    # reloader 关闭可能等待 executor 数分钟，并留下占用端口的子进程。
    # 本地默认 127.0.0.1；容器内通过 UVICORN_HOST=0.0.0.0 对外服务。
    uvicorn.run(
        "finance_agent.main:app",
        host=UVICORN_HOST,
        port=UVICORN_PORT,
        reload=False,
    )
