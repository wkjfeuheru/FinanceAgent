"""API 请求/响应模型。"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class ChatRequest(BaseModel):
    """对话请求。"""
    message: str = Field(..., description="用户输入消息")
    customer_id: str = Field(default="CUST001", description="客户ID")
    chat_history: list[dict[str, Any]] = Field(default_factory=list, description="对话历史")
    conversation_id: str = Field(default="", description="当前会话ID")


class ChatResponse(BaseModel):
    """对话响应。"""
    response: str = Field(..., description="投顾回复")
    task_plan: list[str] = Field(default_factory=list, description="任务计划")
    user_profile: dict[str, Any] = Field(default_factory=dict, description="用户画像")
    stock_data: dict[str, Any] = Field(default_factory=dict, description="股票数据")
    fundamental_analysis: dict[str, Any] = Field(default_factory=dict, description="基本面分析")
    allocation_result: dict[str, Any] = Field(default_factory=dict, description="资产配置结果")
    compliance_result: dict[str, Any] = Field(default_factory=dict, description="合规审查结果")
    conversation_id: str = ""


class ProfileResponse(BaseModel):
    """用户画像响应。"""
    customer_id: str
    risk_preference: str = ""
    budget_amount: float = 0.0
    stock_codes: list[str] = Field(default_factory=list)
    holding_period: str = ""
    investment_goal: str = ""
    updated_at: str = ""


class HistoryResponse(BaseModel):
    """对话历史响应。"""
    customer_id: str
    messages: list[dict[str, Any]] = Field(default_factory=list)


class HealthResponse(BaseModel):
    """健康检查响应。"""
    status: str = "ok"
    redis_available: bool = False
    agents_initialized: bool = False


# ── 用户认证相关模型 ────────────────────────────────────────────

class RegisterRequest(BaseModel):
    """注册请求。"""
    username: str = Field(..., min_length=2, max_length=32, description="用户名")
    password: str = Field(..., min_length=6, max_length=64, description="密码")
    display_name: str = Field(default="", description="显示名称")


class LoginRequest(BaseModel):
    """登录请求。"""
    username: str = Field(..., description="用户名")
    password: str = Field(..., description="密码")


class UserInfo(BaseModel):
    """用户信息。"""
    customer_id: str
    username: str
    display_name: str = ""


class LoginResponse(BaseModel):
    """登录响应。"""
    customer_id: str
    username: str
    display_name: str = ""
    token: str
    expires_in: int = 7 * 24 * 3600


class RegisterResponse(BaseModel):
    """注册响应。"""
    customer_id: str
    username: str
    display_name: str = ""


class ClearRecordsResponse(BaseModel):
    """清除记录响应。"""
    status: str = "ok"
    cleared_keys: int = 0
    message: str = ""
