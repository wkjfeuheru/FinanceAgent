"""API 请求/响应模型。"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from finance_agent.contracts.models import ResponseEnvelope


class ChatRequest(BaseModel):
    """对话请求。"""
    message: str = Field(..., description="用户输入消息")
    customer_id: str = Field(default="CUST001", description="客户ID")
    chat_history: list[dict[str, Any]] = Field(default_factory=list, description="对话历史")
    conversation_id: str = Field(default="", description="当前会话ID")


class DebateSummary(BaseModel):
    """辩论摘要，可按需返回部分字段。"""
    summary: str | None = None
    rationale: str | None = None
    bull_arguments: list[str] = Field(default_factory=list)
    bear_arguments: list[str] = Field(default_factory=list)
    disagreements: list[str] = Field(default_factory=list)
    convergences: list[str] = Field(default_factory=list)


class AllocationResult(BaseModel):
    """资产配置结果，保留未知字段以兼容历史结果。"""
    model_config = ConfigDict(extra="allow")

    weights: dict[str, float] = Field(default_factory=dict)
    expected_return: float | None = None
    expected_volatility: float | None = None
    sharpe_ratio: float | None = None
    allocation_amounts: dict[str, float] = Field(default_factory=dict)
    debate: DebateSummary | None = None


class ChatResponse(BaseModel):
    """对话响应。"""
    response: str = Field(..., description="投顾回复")
    task_plan: list[str] = Field(default_factory=list, description="任务计划")
    user_profile: dict[str, Any] = Field(default_factory=dict, description="用户画像")
    stock_data: dict[str, Any] = Field(default_factory=dict, description="股票数据")
    fundamental_analysis: dict[str, Any] = Field(default_factory=dict, description="基本面分析")
    stock_analysis: dict[str, Any] = Field(default_factory=dict, description="股票综合分析")
    technical_analysis: dict[str, Any] = Field(default_factory=dict, description="技术面分析")
    analysis_results: list[dict[str, Any]] = Field(default_factory=list, description="结构化研究结果")
    theme_screening: dict[str, Any] = Field(default_factory=dict, description="主题筛选结果")
    theme_screening_status: str = ""
    theme_candidates: list[dict[str, Any]] = Field(default_factory=list)
    pending_leads: list[dict[str, Any]] = Field(default_factory=list)
    personalization_status: str = ""
    allocation_result: AllocationResult = Field(default_factory=AllocationResult, description="资产配置结果")
    debate_result: dict[str, Any] = Field(default_factory=dict, description="辩论结果")
    compliance_result: dict[str, Any] = Field(default_factory=dict, description="合规审查结果")
    product_analysis: dict[str, Any] | None = Field(default=None, description="产品解读结果")
    market_insight: dict[str, Any] = Field(default_factory=dict, description="市场洞察结果")
    conversation_id: str = ""
    tasks: list[dict[str, Any]] = Field(default_factory=list)
    task_results: dict[str, Any] = Field(default_factory=dict)
    run_status: str = "completed"
    warnings: list[str] = Field(default_factory=list)


def to_chat_response(result: ResponseEnvelope | Mapping[str, Any] | ChatResponse) -> ChatResponse:
    """将新响应包或历史结果字典转换为旧 ChatResponse 契约。"""
    if isinstance(result, ChatResponse):
        return result
    if isinstance(result, ResponseEnvelope):
        payload: dict[str, Any] = {
            "response": result.response,
            "task_plan": list(dict.fromkeys(
                item.expert_name for item in (result.tasks or result.results)
            )),
            "tasks": [item.model_dump(mode="json") for item in result.tasks],
            "task_results": {
                item.task_id: item.model_dump(mode="json") for item in result.results
            },
            "run_status": result.run_status.value,
            "warnings": list(result.warnings),
            "conversation_id": result.conversation_id,
        }
        for expert_result in result.results:
            data = dict(expert_result.result_data)
            if expert_result.expert_name == "stock_analysis":
                payload.update({key: data[key] for key in (
                    "stock_data", "fundamental_analysis", "stock_analysis", "technical_analysis",
                    "analysis_results",
                    "theme_screening",
                    "theme_screening_status", "theme_candidates", "pending_leads", "personalization_status",
                ) if key in data})
            elif expert_result.expert_name == "asset_allocation":
                payload["allocation_result"] = data
                if "debate" in data:
                    payload["debate_result"] = data["debate"]
            elif expert_result.expert_name == "market_insight":
                payload["market_insight"] = data.get("market_insight", data)
            elif expert_result.expert_name == "product_analysis":
                # 专家结果可能把产品 payload 嵌在 product_analysis 键下，也可能是扁平结构。
                nested = data.get("product_analysis")
                payload["product_analysis"] = nested if isinstance(nested, dict) else data
        return ChatResponse.model_validate(payload)
    return ChatResponse.model_validate(dict(result))


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


class ThemeLeadReviewRequest(BaseModel):
    """管理员对主题待审核线索的不可变审核输入。"""

    decision: str = Field(..., pattern="^(approve|reject)$")
    evidence_expires_at: str
    note: str = ""


class ThemeLeadResponse(BaseModel):
    id: str
    theme_id: str
    stock_code: str
    industry: str = ""
    source_name: str
    source_class: str
    source_uri: str
    evidence_excerpt: str
    evidence_hash: str
    discovered_at: datetime
    evidence_expires_at: datetime


class ThemeRegistryUpsertRequest(BaseModel):
    """管理员新增/更新主题注册记录（名称与别名用于解析用户自由文本）。"""

    theme_id: str = Field(..., min_length=1, max_length=128)
    display_name: str = Field(..., min_length=1, max_length=128)
    aliases: list[str] = Field(default_factory=list)
    representative_codes: list[str] = Field(default_factory=list)
    active: bool = True


class ThemeRegistryEntry(BaseModel):
    theme_id: str
    display_name: str
    aliases: list[str] = Field(default_factory=list)
    representative_codes: list[str] = Field(default_factory=list)
    active: bool = True
