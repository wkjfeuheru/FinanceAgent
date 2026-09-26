"""会话与用户画像接口响应模型。"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class ProfileResponse(BaseModel):
    customer_id: str
    risk_preference: str = ""
    budget_amount: float = 0.0
    stock_codes: list[str] = Field(default_factory=list)
    holding_period: str = ""
    investment_goal: str = ""
    updated_at: str = ""


class HistoryResponse(BaseModel):
    customer_id: str
    messages: list[dict[str, Any]] = Field(default_factory=list)


__all__ = ["HistoryResponse", "ProfileResponse"]
