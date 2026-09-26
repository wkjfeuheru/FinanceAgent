"""聊天接口请求/响应模型及旧响应适配。"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from pydantic import BaseModel, Field

from finance_agent.shared.contracts import ResponseEnvelope


class ChatRequest(BaseModel):
    message: str = Field(..., description="用户输入消息")
    customer_id: str = Field(default="CUST001", description="客户ID")
    chat_history: list[dict[str, Any]] = Field(default_factory=list, description="对话历史")
    conversation_id: str = Field(default="", description="当前会话ID")
    resume: bool = Field(default=False, description="本轮是否为对上一轮追问的答复")
    answers: dict[str, Any] = Field(default_factory=dict, description="弹窗提交的参数")


class ChatResponse(BaseModel):
    response: str = Field(..., description="投顾回复")
    task_plan: list[str] = Field(default_factory=list, description="任务计划")
    user_profile: dict[str, Any] = Field(default_factory=dict, description="用户画像")
    stock_data: dict[str, Any] = Field(default_factory=dict, description="股票数据")
    fundamental_analysis: dict[str, Any] = Field(default_factory=dict, description="基本面分析")
    stock_analysis: dict[str, Any] = Field(default_factory=dict, description="股票综合分析")
    technical_analysis: dict[str, Any] = Field(default_factory=dict, description="技术面分析")
    analysis_results: list[dict[str, Any]] = Field(default_factory=list, description="结构化研究结果")
    personalization_status: str = ""
    compliance_result: dict[str, Any] = Field(default_factory=dict, description="合规审查结果")
    product_analysis: dict[str, Any] | None = Field(default=None, description="产品解读结果")
    account: dict[str, Any] = Field(default_factory=dict, description="账户与持仓快照（只读）")
    conversation_id: str = ""
    tasks: list[dict[str, Any]] = Field(default_factory=list)
    task_results: dict[str, Any] = Field(default_factory=dict)
    run_status: str = "completed"
    warnings: list[str] = Field(default_factory=list)
    task_id: str = ""
    pending_task_ids: list[str] = Field(default_factory=list)
    pending_input: dict[str, Any] | None = Field(default=None, description="缺参追问表单")
    interrupt_id: str = Field(default="", description="挂起的追问标识")


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
                    "analysis_results", "personalization_status",
                ) if key in data})
            elif expert_result.expert_name == "product_analysis":
                nested = data.get("product_analysis")
                payload["product_analysis"] = nested if isinstance(nested, dict) else data
        return ChatResponse.model_validate(payload)
    return ChatResponse.model_validate(dict(result))


__all__ = ["ChatRequest", "ChatResponse", "to_chat_response"]
