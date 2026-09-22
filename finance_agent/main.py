"""FastAPI 应用入口。

启动方式：
    uvicorn finance_agent.main:app --reload --port 8000
"""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from finance_agent.api.admin_routes import router as admin_router
from finance_agent.api.portfolio_routes import router as portfolio_router
from finance_agent.api.routes import router


app = FastAPI(
    title="金融智能投顾 API",
    description="基于多Agent的金融智能投顾系统后端API",
    version="2.1.0",
)

# CORS 配置：允许 Vue3 开发服务器访问
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",   # Vue3 Vite 默认端口
        "http://127.0.0.1:5173",
        "http://localhost:3000",   # 备用端口
    ],
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


@app.get("/")
async def root():
    return {
        "service": "金融智能投顾 API",
        "version": "2.1.0",
        "docs": "/docs",
        "endpoints": [
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
        ],
    }


if __name__ == "__main__":
    import uvicorn
    # 默认使用单进程运行。自动重载会创建父子进程；当分析线程仍在执行时，
    # reloader 关闭可能等待 executor 数分钟，并留下占用端口的子进程。
    uvicorn.run("finance_agent.main:app", host="127.0.0.1", port=8000, reload=False)
