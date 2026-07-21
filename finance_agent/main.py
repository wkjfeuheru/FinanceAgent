"""FastAPI 应用入口。

启动方式：
    uvicorn finance_agent.main:app --reload --port 8000
"""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

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
            "GET  /api/profile/{customer_id}",
            "GET  /api/history/{customer_id}",
            "POST /api/reset/{customer_id}",
            "POST /api/admin/clear-records",
            "DELETE /api/account",
            "GET  /api/health",
        ],
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("finance_agent.main:app", host="127.0.0.1", port=8000, reload=True)
