"""健康检查与降级指标路由。

handler 一律是同步 ``def``：``get_system()`` 会惰性构造整个 AdvisorSystem（
checkpointer、业务库、Redis、分类器），属于阻塞调用。写成 ``async def`` 会让它在
事件循环里执行，一旦卡住连存活探针都失效 —— 而探针正是用来发现这种故障的。
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter

from finance_agent.api.dependencies import get_system
from finance_agent.api.schemas.health import HealthResponse

router = APIRouter(tags=["health"])


@router.get("/api/health", response_model=HealthResponse)
def health() -> HealthResponse:
    try:
        redis_ok = get_system().memory.store.is_available()
        return HealthResponse(status="ok", redis_available=redis_ok, agents_initialized=True)
    except Exception:
        return HealthResponse(status="error", redis_available=False, agents_initialized=False)


@router.get("/api/health/degradation")
def degradation_health() -> dict[str, Any]:
    system = get_system()
    counts = getattr(system, "degradation_counts", None)
    return {"degradation_counts": counts() if callable(counts) else {}}


__all__ = ["degradation_health", "health", "router"]
