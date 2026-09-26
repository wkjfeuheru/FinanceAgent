"""健康检查响应模型。"""

from pydantic import BaseModel


class HealthResponse(BaseModel):
    status: str = "ok"
    redis_available: bool = False
    agents_initialized: bool = False


__all__ = ["HealthResponse"]
