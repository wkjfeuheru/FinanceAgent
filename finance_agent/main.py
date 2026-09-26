"""公开 ASGI/CLI 入口；应用组装集中在 ``finance_agent.api.app``。"""

from __future__ import annotations

from finance_agent.api.app import app

__all__ = ["app"]


if __name__ == "__main__":
    import uvicorn

    from finance_agent.infrastructure.settings import UVICORN_HOST, UVICORN_PORT

    uvicorn.run(
        "finance_agent.main:app",
        host=UVICORN_HOST,
        port=UVICORN_PORT,
        reload=False,
    )
